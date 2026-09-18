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
from download import classify, clean_link, fetch, migrate_folders  # noqa: E402
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


# Two deadlines, because "slow" and "stuck" look identical from outside and
# need opposite answers.
#
# A big video legitimately takes minutes, so once bytes are actually moving we
# wait a long time. But a link that has produced NO sign of life - no
# progress, no stage - is a link going nowhere. Reddit is the case that proved
# it: it answers "403 Blocked" in a tenth of a second, and yt-dlp then works
# through fallback after fallback for a hundred seconds. No retry setting
# bounds that, because it isn't retrying - it's trying different things. Only
# the caller can put a limit on it.
QUIET_DEADLINE_SECONDS = 45      # nothing has happened at all
ITEM_DEADLINE_SECONDS = 1800     # something is happening, just slowly


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
            # A cancel can name one item. The panel has a cross per row, so
            # "cancel" no longer only means "whatever is running".
            wanted = message.get("id")
            with queue_lock:
                still_queued = [q for q in pending if q.get("id") == wanted]
                for queued in still_queued:
                    pending.remove(queued)
            if still_queued:
                # It never started, so nothing has to be interrupted - and the
                # answer can go back immediately.
                log(f"cancel: queued item {wanted} removed")
                try:
                    send({"status": "cancelled", "id": wanted})
                except Closed:
                    pass
            else:
                log(f"cancel: current item ({wanted})")
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
    # An empty message is how a real failure once reached the user as the word
    # "None" and told them nothing. Never send one.
    if not text or text == "None":
        return "The download failed and gave no reason. Check host.log."
    return text


def handle(message, reported=None, beat=None):
    """
    Do one item off the queue, and tell Chrome how it went.

    `reported` is a threading.Event shared with the main loop. Once it is set,
    this item has already been answered - because the user cancelled and the
    main loop said so without waiting for us. Everything that would speak to
    Chrome checks it first, so an abandoned download can never announce itself
    afterwards and put a finished row back on a queue the user emptied.
    """
    if reported is None:
        reported = threading.Event()
    if beat is None:
        beat = [time.monotonic()]

    def answer(payload):
        """Send exactly one final word about this item, and only if nobody has."""
        if reported.is_set():
            return
        reported.set()
        send(payload)

    item_id = message.get("id")
    url = clean_link(str(message.get("url", "")))
    log(f"request: {url}")

    if not url:
        answer({"status": "error", "id": item_id, "kind": "failed",
                "message": "No link was sent."})
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
            beat[0] = time.monotonic()
            if not reported.is_set():
                send({"status": "progress", "id": item_id, "percent": percent})

    def on_status(note):
        """Stages that aren't a percentage - shrinking pictures, transcribing."""
        check_cancel()
        beat[0] = time.monotonic()
        if not reported.is_set():
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
            # Checked during extraction and inside gallery-dl too, not just
            # while bytes are moving. A link stuck resolving used to be
            # uncancellable, which is what made cancel look broken.
            should_stop=check_cancel,
        )
    except Cancelled:
        log("cancelled")
        answer({"status": "cancelled", "id": item_id})
        return
    except DownloadError as err:
        # A cancel mid-download surfaces as our Cancelled wrapped by yt-dlp.
        # exc_info is None on a DownloadError we raised ourselves rather than
        # one yt-dlp raised, so it has to be defaulted before it is indexed -
        # getattr's default doesn't help when the attribute exists and is None.
        wrapped = (getattr(err, "exc_info", None) or (None, None, None))[1]
        if isinstance(err.__cause__, Cancelled) or isinstance(wrapped, Cancelled):
            log("cancelled")
            answer({"status": "cancelled", "id": item_id})
            return
        kind, sentence = classify(err, url)
        log(f"failed ({kind}): {err}")
        answer({"status": "error", "id": item_id, "kind": kind,
                "message": sentence or tidy_error(err),
                "site": message.get("site") or ""})
        return
    except Exception as err:  # noqa: BLE001 - a crash must still reach the user
        log(f"crashed: {type(err).__name__}: {err}")
        kind, sentence = classify(err, url)
        detail = sentence or tidy_error(err)
        if detail.startswith("The download failed and gave no reason"):
            detail = type(err).__name__
        answer({"status": "error", "id": item_id, "kind": kind,
                "message": detail})
        return
    finally:
        if cookies:
            try:
                cookies.unlink()
            except OSError:
                pass

    saved = Path(str(result.path))
    log(f"saved: {saved}")
    answer({
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
    # An older version wrote straight into Videos. Tidy that away once, before
    # anything can save into the new place and leave the tree half-migrated.
    try:
        moved = migrate_folders()
        if moved:
            log(f"moved into the master folder: {', '.join(moved)}")
    except Exception as err:  # noqa: BLE001 - never block downloading over this
        log(f"folder migration skipped: {type(err).__name__}: {err}")

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

        # The item runs on its own thread so the main loop stays free to
        # answer a cancel. Waiting for a blocked download to notice a flag is
        # exactly what made cancel feel broken: a link stuck retrying a 429
        # reaches no checkpoint for minutes. Answering here instead makes
        # cancel instant no matter where the worker is stuck.
        reported = threading.Event()
        beat = [time.monotonic()]   # last time the worker showed any sign of life
        worker = threading.Thread(
            target=_run_item, args=(item, reported, beat), daemon=True
        )
        worker.start()

        started = time.monotonic()
        while worker.is_alive():
            worker.join(0.2)
            if not worker.is_alive():
                break

            if cancel_current.is_set() and not reported.is_set():
                # Say so now and move on. The worker is a daemon, and
                # `reported` guarantees it can never write a finished row for
                # an item the user already stopped.
                reported.set()
                log(f"cancelled item {item.get('id')} (worker abandoned)")
                send({"status": "cancelled", "id": item.get("id")})
                break

            if pipe_closed.is_set():
                return

            now = time.monotonic()
            quiet = now - beat[0] > QUIET_DEADLINE_SECONDS
            overall = now - started > ITEM_DEADLINE_SECONDS
            if quiet or overall:
                if not reported.is_set():
                    reported.set()
                    log(f"gave up on item {item.get('id')} "
                        f"({'no sign of life' if quiet else 'overall deadline'})")
                    send({"status": "error", "id": item.get("id"),
                          "kind": "rate_limited" if quiet else "failed",
                          "message": ("This site isn't responding - it may be "
                                      "blocking downloads. Try again in a "
                                      "minute, or use your login for it.")
                                     if quiet else
                                     "This one took too long and was stopped."})
                # Stop the abandoned worker too, so it isn't still using the
                # network while the next item runs.
                cancel_current.set()
                break


def _run_item(item, reported, beat):
    """One queued item, on its own thread. Never lets an exception escape."""
    try:
        handle(item, reported, beat)
    except Closed:
        pipe_closed.set()
    except Exception as err:  # noqa: BLE001
        log(f"item crashed: {type(err).__name__}: {err}")
        if not reported.is_set():
            reported.set()
            try:
                send({"status": "error", "id": item.get("id"), "kind": "failed",
                      "message": f"{type(err).__name__}: {err}"})
            except Closed:
                pipe_closed.set()


if __name__ == "__main__":
    try:
        main()
    except Closed:
        log("Chrome hung up")
    except Exception as err:  # noqa: BLE001
        log(f"host crashed: {type(err).__name__}: {err}")
        raise
