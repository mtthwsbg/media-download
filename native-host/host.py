"""
host.py - the bridge between the Chrome extension and download.py.

Chrome starts this program when the extension opens the pipe and kills it when
the pipe closes. While it is alive it takes as many links as you send it and
works through them one at a time - that queue is the point. Click download on
one tab, move to the next, click again; nothing waits for anything.

Two threads, for one reason: a download blocks for a long time, and a "cancel"
has to be heard while it's blocking. So a reader thread does nothing but drain
the pipe, and the main thread does nothing but download.

The pipe format Chrome uses: every message is 4 bytes saying how long it is
(little-endian), followed by that many bytes of JSON. Anything else that ends
up on stdout corrupts the stream and Chrome hangs up - which is why the very
first thing this file does is take stdout away from everybody else.
"""

import collections
import json
import os
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

# Built into host.exe for sharing, or run from the source folder here. When
# frozen, __file__ points inside the bundle, so the log has to be anchored on
# the executable instead - otherwise it lands somewhere nobody can find.
FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys.executable if FROZEN else __file__).resolve().parent
PROJECT = HERE.parent
LOG = HERE / "host.log"
LOG_MAX_BYTES = 1_000_000

# ---------------------------------------------------------------
#  Claim stdout before anything can print to it
# ---------------------------------------------------------------
if sys.platform == "win32":
    # Windows would otherwise turn every \n in our binary length prefix into
    # \r\n, which silently corrupts the message length.
    import msvcrt

    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)

CHANNEL = sys.stdout.buffer  # the real pipe to Chrome; only send() writes here
READER = sys.stdin.buffer

# download.py prints progress lines. Send them to stderr, which Chrome ignores.
sys.stdout = sys.stderr

# Safe to import now that print() can no longer reach the pipe. In the frozen
# build download.py is packed inside the bundle and is already importable.
if not FROZEN:
    sys.path.insert(0, str(PROJECT))
from download import clean_link, fetch  # noqa: E402
from yt_dlp.utils import DownloadError  # noqa: E402


def log(text):
    """A native host's stderr goes nowhere visible, so failures need a file."""
    try:
        if LOG.exists() and LOG.stat().st_size > LOG_MAX_BYTES:
            LOG.unlink()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {text}\n")
    except Exception:
        pass  # logging must never be the thing that breaks a download


class Cancelled(Exception):
    """This download was told to stop - by the user, or by Chrome hanging up."""


class Closed(Exception):
    """Chrome hung up. Nothing more is coming and nothing more can be sent."""


# ---------------------------------------------------------------
#  Talking to Chrome
# ---------------------------------------------------------------

# Only one thread ever writes to the pipe, but the reader thread can decide to
# stop everything, so guard the flag rather than the socket.
_send_lock = threading.Lock()


def send(payload):
    """Write one message back to Chrome in the format it expects."""
    data = json.dumps(payload).encode("utf-8")
    with _send_lock:
        try:
            CHANNEL.write(struct.pack("<I", len(data)))
            CHANNEL.write(data)
            CHANNEL.flush()
        except OSError as err:
            # Nobody is listening any more.
            raise Closed from err


def receive():
    """Read one message from Chrome. Returns None when the pipe closes."""
    header = READER.read(4)
    if len(header) < 4:
        return None
    length = struct.unpack("<I", header)[0]
    body = READER.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------
#  The queue
# ---------------------------------------------------------------

pending = collections.deque()
queue_lock = threading.Lock()
work_arrived = threading.Event()

# Set by the reader thread, read by the download thread.
cancel_current = threading.Event()
pipe_closed = threading.Event()


def reader_thread():
    """
    Drain the pipe forever, so a cancel is heard mid-download.

    This thread never downloads anything and never blocks on anything except
    the pipe, which is exactly what makes it able to interrupt.
    """
    while True:
        try:
            message = receive()
        except Exception:
            message = None

        if message is None:
            pipe_closed.set()
            cancel_current.set()
            work_arrived.set()
            return

        command = message.get("cmd")
        if command == "cancel":
            log("cancel: current item")
            cancel_current.set()
        elif command == "clear":
            with queue_lock:
                dropped = len(pending)
                pending.clear()
            log(f"clear: dropped {dropped} queued, cancelling current")
            cancel_current.set()
        else:
            with queue_lock:
                pending.append(message)
            work_arrived.set()


def cookie_file(text):
    """
    Park the cookies the extension sent us in a file yt-dlp can read.

    They arrive as Netscape cookie-file text. They never leave this machine -
    the extension read them out of your own Chrome profile and handed them
    straight over the pipe.
    """
    if not text:
        return None
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="mediadl-cookies-",
        delete=False, encoding="utf-8",
    )
    try:
        handle.write(text)
    finally:
        handle.close()
    return Path(handle.name)


def tidy_error(err):
    """Turn a yt-dlp error into one line a person can read on a notification."""
    text = str(err).replace("\n", " ").strip()
    if text.startswith("ERROR: "):
        text = text[len("ERROR: "):]
    # yt-dlp colours its output; the escape codes look like garbage in a popup.
    while "\x1b[" in text:
        start = text.index("\x1b[")
        end = text.find("m", start)
        if end == -1:
            break
        text = text[:start] + text[end + 1:]
    if len(text) > 250:
        text = text[:250] + "..."
    return text or "Unknown error."


def handle(message):
    """Do one item off the queue, and tell Chrome how it went."""
    item_id = message.get("id")
    url = clean_link(str(message.get("url", "")))
    log(f"request: {url}")

    if not url:
        send({"status": "error", "id": item_id, "message": "No link was sent."})
        return

    cookies = cookie_file(message.get("cookies"))
    last_percent = [-1]

    def check_cancel():
        if cancel_current.is_set():
            raise Cancelled

    def on_progress(state):
        """yt-dlp calls this as bytes arrive.

        Doing triple duty: it drives the percentage on the toolbar icon, each
        message resets Chrome's idle timer so a long download doesn't get the
        extension shut down underneath it, and it is the point at which a
        cancel actually takes effect.
        """
        check_cancel()
        if state.get("status") != "downloading":
            return
        total = state.get("total_bytes") or state.get("total_bytes_estimate")
        if not total:
            return
        percent = int((state.get("downloaded_bytes") or 0) * 100 / total)
        if percent != last_percent[0]:
            last_percent[0] = percent
            send({"status": "progress", "id": item_id, "percent": percent})

    def on_status(note):
        """Stages that aren't a percentage - shrinking pictures, transcribing."""
        check_cancel()
        send({"status": "stage", "id": item_id, "stage": note})

    try:
        result = fetch(
            url,
            cookiefile=cookies,
            extra_options={
                "progress_hooks": [on_progress],
                "quiet": True,
                "no_progress": True,
                "noprogress": True,
            },
            on_status=on_status,
        )
    except Cancelled:
        log("cancelled")
        send({"status": "cancelled", "id": item_id})
        return
    except DownloadError as err:
        # A cancel mid-download surfaces as our Cancelled wrapped by yt-dlp.
        # exc_info is None on a DownloadError we raised ourselves rather than
        # one yt-dlp raised, so it has to be defaulted before it is indexed -
        # getattr's default doesn't help when the attribute exists and is None.
        wrapped = (getattr(err, "exc_info", None) or (None, None, None))[1]
        if isinstance(err.__cause__, Cancelled) or isinstance(wrapped, Cancelled):
            log("cancelled")
            send({"status": "cancelled", "id": item_id})
            return
        log(f"failed: {err}")
        send({"status": "error", "id": item_id, "message": tidy_error(err)})
        return
    except Exception as err:  # noqa: BLE001 - a crash must still reach the user
        log(f"crashed: {type(err).__name__}: {err}")
        send({"status": "error", "id": item_id,
              "message": f"{type(err).__name__}: {err}"})
        return
    finally:
        if cookies:
            try:
                cookies.unlink()
            except OSError:
                pass

    saved = Path(str(result.path))
    log(f"saved: {saved}")
    send({
        "status": "done",
        "id": item_id,
        "kind": result.kind,
        "path": str(saved),
        "name": saved.name,
        "folder": str(result.folder) if result.folder else str(saved.parent),
    })


def heartbeat_thread():
    """
    Say something every so often, even when there is nothing to say.

    Chrome shuts an idle extension down after about thirty seconds. Shrinking
    pictures or transcoding a video is thirty quiet seconds with nothing to
    report, and losing the extension mid-queue takes the whole queue with it.
    """
    while not pipe_closed.is_set():
        time.sleep(20)
        try:
            send({"status": "tick"})
        except Closed:
            return


def main():
    watcher = threading.Thread(target=reader_thread, daemon=True)
    watcher.start()
    threading.Thread(target=heartbeat_thread, daemon=True).start()

    while True:
        # Chrome hanging up ends everything, including whatever is still
        # queued - there is nobody left to tell about it.
        if pipe_closed.is_set():
            return

        with queue_lock:
            item = pending.popleft() if pending else None

        if item is None:
            # Nothing to do; sleep until the reader hands us something.
            work_arrived.wait(timeout=1.0)
            work_arrived.clear()
            continue

        # A cancel applies to the item that was running when it was clicked,
        # not to the one that comes next.
        cancel_current.clear()

        # One bad link must never take the rest of the queue with it. handle()
        # already reports every failure it can name; this is the backstop for
        # the ones it can't, and it is the difference between losing one
        # download and losing eight.
        try:
            handle(item)
        except Closed:
            raise
        except Exception as err:  # noqa: BLE001
            log(f"item crashed: {type(err).__name__}: {err}")
            try:
                send({"status": "error", "id": item.get("id"),
                      "message": f"{type(err).__name__}: {err}"})
            except Closed:
                raise


if __name__ == "__main__":
    try:
        main()
    except Closed:
        log("Chrome hung up")
    except Exception as err:  # noqa: BLE001
        log(f"host crashed: {type(err).__name__}: {err}")
        raise
