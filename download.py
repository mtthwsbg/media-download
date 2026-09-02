"""
download.py - paste a link, get the media, plus a folder Claude can read.

Handles three shapes of link:

  * a single video      - Reels, Shorts, YouTube, TikTok -> an .mp4
  * a multi-picture post - the Instagram ones with dots along the bottom
                           -> a folder of numbered .jpg files
  * anything in between  - a post that mixes pictures and clips

Every download also gets a bundle: a folder holding post.md (the caption and
who wrote it), the pictures shrunk down, a few stills from any video, and a
transcript if a Groq key is set up. That bundle is the part Claude reads - see
bundle.py for why it isn't a PDF.

Usage:
    python download.py            -> interactive; paste links one at a time
    python download.py <link>     -> download that one link and exit
"""

import io
import shutil
import sys
import tempfile
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

import bundle
import transcribe
from bundle import find_ffmpeg

# ---------------------------------------------------------------
#  WHERE THINGS GET SAVED
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

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


class Result:
    """What a finished download produced."""

    def __init__(self, kind, media=None, folder=None):
        self.kind = kind        # "video" or "post"
        self.media = media      # the .mp4, for a video
        self.folder = folder    # the bundle folder Claude reads

    @property
    def path(self):
        """The one path worth showing in a notification."""
        return self.media or self.folder


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


def _base_options(cookiefile=None):
    """The yt-dlp settings shared by looking and downloading."""
    options = {
        "socket_timeout": 15,
        "retries": 3,
        "no_warnings": True,
        "quiet": True,
        "noprogress": True,
    }
    if cookiefile:
        # Being logged in is what makes Instagram and Facebook work at all.
        # The extension hands us a cookie file; see background.js.
        options["cookiefile"] = str(cookiefile)

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        options["ffmpeg_location"] = str(ffmpeg)
    return options


def probe(url, cookiefile=None):
    """
    Ask what's behind a link without downloading it.

    Returns yt-dlp's info dict, or None if yt-dlp can't see anything - which is
    the normal answer for a post that is only pictures, and the signal to hand
    the link to gallery-dl instead.

    noplaylist is deliberately NOT set here. A multi-picture Instagram post is a
    playlist as far as yt-dlp is concerned, so switching playlists off is what
    used to make a ten-picture post arrive as one picture.
    """
    options = dict(_base_options(cookiefile), extract_flat=False, skip_download=True)
    try:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)
    except DownloadError:
        return None
    except Exception:
        return None


def has_video(info):
    """True if yt-dlp found an actual video stream to fetch."""
    if not info:
        return False
    if info.get("entries"):
        return False
    return bool(info.get("formats") or info.get("url"))


def download(url, extra_options=None, cookiefile=None):
    """
    Download a single video. Returns the saved file path.

    extra_options is for callers that need to tweak yt-dlp without copying the
    settings below - host.py uses it to attach a progress hook.
    """
    folder = pick_folder(url)
    folder.mkdir(parents=True, exist_ok=True)  # make the folder if it isn't there yet

    options = dict(_base_options(cookiefile))
    options.update({
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
        # Stitch the video and audio into a single .mp4 (this is what ffmpeg does).
        "merge_output_format": "mp4",
        # Filename pattern -> "Creator - Title [id].mp4"
        "outtmpl": str(folder / "%(uploader)s - %(title).80s [%(id)s].%(ext)s"),
        # A single video that happens to sit in a playlist: grab only that video.
        # Multi-picture posts never reach here - fetch() sends them elsewhere.
        "noplaylist": True,
    })

    # Applied last so a caller can override anything above.
    if extra_options:
        options.update(extra_options)

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    # yt-dlp records the final path here after any merging is done.
    finished = info.get("requested_downloads") or []
    if finished and finished[0].get("filepath"):
        return Path(finished[0]["filepath"]), info
    return folder, info


def gallery_fetch(url, into, cookiefile=None):
    """
    Download every picture and clip in a post, using gallery-dl.

    yt-dlp is a video tool and treats a picture as a video with no formats.
    gallery-dl is the one built for posts, so multi-picture Instagram posts and
    the image half of a mixed post go through here.

    Returns the files it wrote, in the order you'd swipe through them.
    """
    from gallery_dl import config as gconfig, job as gjob

    gconfig.clear()
    gconfig.set((), "base-directory", str(into))
    # An empty directory list means "put the files straight in base-directory"
    # rather than gallery-dl's usual site/user/ tree.
    gconfig.set((), "directory", [])
    gconfig.set((), "skip", True)
    if cookiefile:
        gconfig.set((), "cookies", str(cookiefile))

    # Order is the whole game here - it's the order you'd swipe through the
    # post - and the filenames gallery-dl picks don't reliably carry it. So
    # record the order the files actually arrive in. Renaming them to 01, 02...
    # happens later, in bundle.save_images().
    arrived = []

    class OrderedDownload(gjob.DownloadJob):
        def handle_url(self, url, keywords):
            super().handle_url(url, keywords)
            path = getattr(getattr(self, "pathfmt", None), "path", None)
            if path:
                arrived.append(Path(path))

    OrderedDownload(url).run()

    on_disk = {p for p in Path(into).iterdir() if p.is_file()}
    # Anything the hook caught, in arrival order, then anything it missed.
    ordered = [p for p in arrived if p in on_disk]
    return ordered + sorted(on_disk - set(ordered))


def gallery_metadata(url, cookiefile=None):
    """Caption, author and id for a post, without downloading anything."""
    from gallery_dl import config as gconfig, job as gjob

    gconfig.clear()
    if cookiefile:
        gconfig.set((), "cookies", str(cookiefile))

    # DataJob's whole purpose is printing JSON to stdout. We want the data, not
    # the printing - and in the Chrome helper anything on stdout corrupts the
    # pipe, so this is a correctness fix and not just tidiness.
    collector = gjob.DataJob(url, file=io.StringIO())
    collector.run()

    for record in collector.data:
        # DataJob yields (type, url, keywords) triples; the keywords carry the post.
        if isinstance(record, (list, tuple)) and len(record) >= 3 and isinstance(record[-1], dict):
            keywords = record[-1]
            return {
                "id": str(keywords.get("post_shortcode") or keywords.get("id") or ""),
                "uploader": keywords.get("username") or keywords.get("owner") or "",
                "description": keywords.get("description") or keywords.get("content") or "",
                "extractor_key": keywords.get("category") or "",
                "webpage_url": url,
                "upload_date": str(keywords.get("date") or "")[:10].replace("-", ""),
            }
    return {}


def _post_bundle(url, info, cookiefile, on_status=None):
    """Download a multi-picture post and turn it into a readable folder."""
    if not info or not info.get("id"):
        info = {**(info or {}), **gallery_metadata(url, cookiefile)}
    info.setdefault("webpage_url", url)

    dest = bundle.post_dir(info)

    with tempfile.TemporaryDirectory(prefix="mediadl-") as staging:
        if on_status:
            on_status("fetching post")
        grabbed = gallery_fetch(url, staging, cookiefile)

        images = [p for p in grabbed if p.suffix.lower() in IMAGE_SUFFIXES]
        clips = [p for p in grabbed if p.suffix.lower() in VIDEO_SUFFIXES]

        if on_status:
            on_status("shrinking")
        saved_images = bundle.save_images(images, dest)

        # A post can mix pictures and clips. Keep the clips whole next to the
        # pictures, and pull stills out of them so they aren't invisible.
        frames = []
        kept = None
        for index, clip in enumerate(clips, start=1):
            kept = dest / f"video-{index:02d}{clip.suffix.lower()}"
            shutil.copy2(clip, kept)
            frames += bundle.keyframes(kept, dest)

    transcript = None
    if kept:
        if on_status:
            on_status("transcribing")
        transcript = transcribe.transcribe_video(kept, dest)

    bundle.write_post_md(info, dest, images=saved_images, frames=frames,
                         transcript=transcript, media=kept)

    if not saved_images and not clips:
        raise DownloadError(f"Nothing downloadable was found at {url}")

    return Result("post", media=None, folder=dest)


def _video_bundle(url, info, cookiefile, extra_options, on_status=None):
    """Download a video, then write the readable folder beside it."""
    saved, full = download(url, extra_options, cookiefile)
    info = full or info or {}

    dest = bundle.post_dir(info)

    if on_status:
        on_status("stills")
    frames = bundle.keyframes(saved, dest) if saved.is_file() else []

    if on_status:
        on_status("transcribing")
    transcript = transcribe.transcribe_video(saved, dest) if saved.is_file() else None

    bundle.write_post_md(info, dest, frames=frames, transcript=transcript, media=saved)

    return Result("video", media=saved, folder=dest)


def fetch(url, cookiefile=None, extra_options=None, on_status=None):
    """
    The one entry point. Works out what the link is and does the right thing.

    Returns a Result. Raises DownloadError like yt-dlp does, so callers that
    already handle that keep working.
    """
    info = probe(url, cookiefile)

    if has_video(info):
        return _video_bundle(url, info, cookiefile, extra_options, on_status)

    # Either several pieces of media, or nothing yt-dlp recognises as video -
    # both of which mean pictures are involved.
    return _post_bundle(url, info, cookiefile, on_status)


def try_download(url):
    """Run fetch() but never crash - print the problem and carry on."""
    try:
        result = fetch(url, on_status=lambda note: print(f"  {note}..."))
        print(f"Done: {result.path}")
        if result.folder and result.folder != result.path:
            print(f"  Readable copy: {result.folder}")
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
    print("Paste a link and press Enter.")
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
