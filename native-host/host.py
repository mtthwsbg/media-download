"""
host.py - the bridge between the Chrome extension and download.py.

Chrome starts this program, hands it one link over a pipe, waits for it to
finish, then kills it. You never run this yourself.

The pipe format Chrome uses: every message is 4 bytes saying how long it is
(little-endian), followed by that many bytes of JSON. Anything else that ends
up on stdout corrupts the stream and Chrome hangs up - which is why the very
first thing this file does is take stdout away from everybody else.
"""

import json
import os
import struct
import sys
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
from download import clean_link, download  # noqa: E402
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
    """Chrome closed the pipe - the user clicked the button again to stop."""


def send(payload):
    """Write one message back to Chrome in the format it expects."""
    data = json.dumps(payload).encode("utf-8")
    try:
        CHANNEL.write(struct.pack("<I", len(data)))
        CHANNEL.write(data)
        CHANNEL.flush()
    except OSError as err:
        # Nobody is listening any more. Chrome closes the pipe to cancel a
        # download, so this is the normal way a cancel reaches us, not a fault.
        raise Cancelled from err


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


def main():
    message = receive()
    if not message:
        return

    url = clean_link(str(message.get("url", "")))
    log(f"request: {url}")

    if not url:
        send({"status": "error", "message": "No link was sent."})
        return

    last_percent = [-1]

    def on_progress(state):
        """yt-dlp calls this as bytes arrive.

        Doing double duty: it drives the percentage on the toolbar icon, and
        each message resets Chrome's idle timer, which is what stops Chrome
        shutting the extension down in the middle of a long download.
        """
        if state.get("status") != "downloading":
            return
        total = state.get("total_bytes") or state.get("total_bytes_estimate")
        if not total:
            return
        percent = int((state.get("downloaded_bytes") or 0) * 100 / total)
        if percent != last_percent[0]:
            last_percent[0] = percent
            send({"status": "progress", "percent": percent})

    try:
        # quiet/no_progress keep yt-dlp's own console output down; the real
        # format and folder rules stay in download.py, unchanged.
        saved = download(
            url,
            {
                "progress_hooks": [on_progress],
                "quiet": True,
                "no_progress": True,
                "noprogress": True,
            },
        )
    except Cancelled:
        log("cancelled by Chrome")
        return
    except DownloadError as err:
        # A cancel mid-download surfaces as our Cancelled wrapped by yt-dlp.
        if isinstance(err.__cause__, Cancelled) or isinstance(
            getattr(err, "exc_info", (None,))[1], Cancelled
        ):
            log("cancelled by Chrome")
            return
        log(f"failed: {err}")
        try:
            send({"status": "error", "message": tidy_error(err)})
        except Cancelled:
            pass
        return
    except Exception as err:  # noqa: BLE001 - a crash must still reach the user
        log(f"crashed: {type(err).__name__}: {err}")
        try:
            send({"status": "error", "message": f"{type(err).__name__}: {err}"})
        except Cancelled:
            pass
        return

    saved = Path(saved)
    log(f"saved: {saved}")
    try:
        send(
            {
                "status": "done",
                "path": str(saved),
                "name": saved.name,
                "folder": str(saved.parent),
            }
        )
    except Cancelled:
        # Finished just as it was cancelled. The file is on disk either way.
        log("finished, but Chrome had already hung up")


if __name__ == "__main__":
    try:
        main()
    except Cancelled:
        log("cancelled by Chrome")
    except Exception as err:  # noqa: BLE001
        log(f"host crashed: {type(err).__name__}: {err}")
        raise
