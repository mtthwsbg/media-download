"""
download.py - paste a video link, get an MP4.

Works with Instagram Reels, YouTube Shorts, and regular YouTube videos.
Videos are sorted into folders automatically based on the kind of link.

Usage:
    python download.py            -> interactive; paste links one at a time
    python download.py <link>     -> download that one link and exit
"""

import shutil
import sys
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# ---------------------------------------------------------------
#  WHERE VIDEOS GET SAVED
#  If you rename a folder in Explorer, change it here too.
# ---------------------------------------------------------------
VIDEOS = Path.home() / "Videos"

IG_REELS  = VIDEOS / "IG Reels"
YT_SHORTS = VIDEOS / "YT Shorts"
YT_VIDEOS = VIDEOS / "YT Videos"
TIKTOKS   = VIDEOS / "TikToks"

OTHER = VIDEOS / "Other"   # anything that is not one of the four above

# ---------------------------------------------------------------
#  SPEED
# ---------------------------------------------------------------
# Biggest lever on how long a download takes is how many pixels it is. 4K is
# roughly ten times the bytes of 1080p for a video you'll watch on a laptop.
# Raise this to 2160 if you ever actually want 4K.
MAX_HEIGHT = 1080

# YouTube sends video in many small pieces. Fetching several at once is the
# difference between one slow stream and a full pipe. 8 is safe; much higher
# and sites start refusing connections.
PARALLEL_PIECES = 8


def clean_link(text):
    """
    Tidy up a pasted link.

    Copying a link can quietly bring along invisible characters or wrapping
    quotes. Without this they look like a real link and fail confusingly.
    """
    # Zero-width and byte-order-mark characters some apps sneak in.
    for junk in ("﻿", "​", "‌", "‍", "⁠"):
        text = text.replace(junk, "")
    return text.strip().strip('"').strip("'").strip()


def pick_folder(url):
    """Look at the link and decide which folder the video belongs in."""
    link = url.lower()
    if "instagram.com" in link:
        return IG_REELS
    if "tiktok.com" in link:
        return TIKTOKS
    # Must stay ABOVE the youtube.com/watch check, or Shorts fall through to YT Videos.
    if "youtube.com/shorts" in link:
        return YT_SHORTS
    if "youtube.com/watch" in link or "youtu.be/" in link:
        return YT_VIDEOS
    return OTHER


def find_ffmpeg():
    """
    Find ffmpeg, the tool that stitches video and audio together.

    Returns the folder holding ffmpeg.exe, or None to let yt-dlp look on its own.
    Normally ffmpeg is on your PATH and there is nothing to do, but a terminal
    that was already open when ffmpeg was installed won't know about it yet.
    In that case we check where winget puts it. The glob ("*") is there so a
    future ffmpeg update, which changes the version number in the path, still works.
    """
    if shutil.which("ffmpeg"):
        return None

    packages = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    for exe in packages.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"):
        return exe.parent
    return None


def download(url, extra_options=None):
    """
    Download a single link. Returns the saved file path.

    extra_options is for callers that need to tweak yt-dlp without copying the
    settings below - the Chrome extension uses it to attach a progress hook.
    """
    folder = pick_folder(url)
    folder.mkdir(parents=True, exist_ok=True)  # make the folder if it isn't there yet

    options = {
        # Prefer H.264 video + AAC audio: the combination that plays in every
        # player and video editor. Falls back to whatever exists if that's
        # not offered, so a download never fails just over codec choice.
        # The "<=?" means "no taller than this, but don't reject a format just
        # because its height is unknown".
        "format": (
            f"bestvideo[vcodec^=avc1][height<=?{MAX_HEIGHT}]+bestaudio[acodec^=mp4a]/"
            f"best[vcodec^=avc1][height<=?{MAX_HEIGHT}]/"
            f"bestvideo*[height<=?{MAX_HEIGHT}]+bestaudio/best"
        ),
        # Pull the pieces of the video in parallel instead of one after another.
        "concurrent_fragment_downloads": PARALLEL_PIECES,
        # Don't sit forever on a connection that has gone quiet; retry instead.
        "socket_timeout": 15,
        "retries": 3,
        # Stitch the video and audio into a single .mp4 (this is what ffmpeg does).
        "merge_output_format": "mp4",
        # Filename pattern -> "Creator - Title [id].mp4"
        "outtmpl": str(folder / "%(uploader)s - %(title).80s [%(id)s].%(ext)s"),
        # If a link happens to sit inside a playlist, grab only that one video.
        "noplaylist": True,
        "no_warnings": True,
        # Uncomment the line below to reach posts that require being logged in
        # (private accounts you follow, age-restricted videos). It reads the
        # login cookies out of your Chrome profile. Close Chrome first.
        # "cookiesfrombrowser": ("chrome",),
    }

    # Point yt-dlp at ffmpeg if it isn't already on PATH.
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        options["ffmpeg_location"] = str(ffmpeg)

    # Applied last so a caller can override anything above.
    if extra_options:
        options.update(extra_options)

    print(f"\nSaving into: {folder}")
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    # yt-dlp records the final path here after any merging is done.
    finished = info.get("requested_downloads") or []
    if finished and finished[0].get("filepath"):
        return Path(finished[0]["filepath"])
    return folder


def try_download(url):
    """Run download() but never crash - print the problem and carry on."""
    try:
        saved = download(url)
        print(f"Done: {saved}")
        return True
    except DownloadError as err:
        print(f"\nCouldn't download that link.\n  {err}")
    except Exception as err:
        print(f"\nSomething went wrong.\n  {type(err).__name__}: {err}")
    return False


def main():
    # A Korean or Japanese title in a filename can't be printed by the default
    # Windows console encoding, and the crash lands on the "Done:" line - so a
    # download that actually worked reports itself as a failure. Ask for UTF-8
    # and settle for "?" on any character the window still can't draw.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    links = [clean_link(arg) for arg in sys.argv[1:] if clean_link(arg)]

    # Links passed on the command line: do them and quit.
    if links:
        for url in links:
            try_download(url)
        return

    # No links given: ask for them one at a time.
    print("Paste a video link and press Enter.")
    print("Press Enter on an empty line to quit.")
    while True:
        try:
            url = clean_link(input("\nLink: "))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not url:
            break
        try_download(url)
    print("Bye.")


if __name__ == "__main__":
    main()
