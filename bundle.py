"""
bundle.py - turn a download into a folder Claude can read cheaply.

The point of this file is cost. What Claude pays to look at a picture depends
only on how many pixels it is - about width x height / 750 tokens - and not at
all on whether it's a PNG, a JPEG, or a page of a PDF. A PDF is in fact the
worst of the options, because each page is rendered to an image AND scraped for
text, so you pay twice for the same page.

So a post becomes a folder:

    post.md          everything sayable in words - caption, author, date
    01.jpg ...       the pictures, shrunk to 1024px on their long edge
    frame-01.jpg     for a video: a few stills, so the visuals aren't invisible
    transcript.txt   for a video: what was actually said

Words cost roughly a token each. A 1024px picture costs about 900. A ten-picture
carousel lands around 9,000 tokens this way, against roughly 20,000 as a PDF.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

# Long edge of every image we hand to Claude. 1024 is the sweet spot: text in a
# screenshot is still legible, and it costs a bit over half what a full-size
# image costs. Above ~1568px Claude downscales anyway, so the extra bytes buy
# nothing at all.
MAX_EDGE = 1024
JPEG_QUALITY = 85

# How many stills to pull out of a video. Enough to see what it looks like,
# few enough that the transcript stays the main event.
KEYFRAME_COUNT = 5

POSTS = Path.home() / "Videos" / "Posts"


def find_ffmpeg():
    """
    Find ffmpeg, the tool that stitches video and audio together and cuts stills.

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


def ffmpeg_exe():
    """The actual ffmpeg command to run, or None if there isn't one."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    folder = find_ffmpeg()
    if folder and (folder / "ffmpeg.exe").exists():
        return str(folder / "ffmpeg.exe")
    return None


def ffprobe_exe():
    """ffprobe ships beside ffmpeg and reads a video's length."""
    found = shutil.which("ffprobe")
    if found:
        return found
    exe = ffmpeg_exe()
    if exe:
        beside = Path(exe).with_name("ffprobe.exe")
        if beside.exists():
            return str(beside)
    return None


def safe(text, limit=60):
    """Make a piece of text usable as part of a Windows folder name."""
    text = str(text or "").strip()
    # These are the characters Windows refuses outright.
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    # Trailing dots and spaces are legal to type but not to create.
    text = text.strip(" .")
    return text[:limit] or "unknown"


def post_dir(info):
    """
    Where a post's readable bundle lives: one folder per post.

    Named site - author - id, so two posts by the same person never collide and
    the folder is recognisable in Explorer without opening it.
    """
    site = safe(info.get("extractor_key") or info.get("extractor") or "web", 20).lower()
    author = safe(info.get("uploader") or info.get("uploader_id") or "unknown", 40)
    ident = safe(info.get("id") or "post", 30)
    folder = POSTS / f"{site} - {author} - {ident}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def shrink(source, target):
    """Write one downscaled JPEG. Returns the path, or None if it wasn't an image."""
    try:
        with Image.open(source) as img:
            # Transparency and palettes don't survive JPEG; flatten onto white.
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                flat = Image.new("RGB", img.size, (255, 255, 255))
                flat.paste(img, mask=img.split()[-1])
                img = flat
            elif img.mode != "RGB":
                img = img.convert("RGB")

            longest = max(img.size)
            if longest > MAX_EDGE:
                scale = MAX_EDGE / longest
                img = img.resize(
                    (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                    Image.LANCZOS,
                )

            img.save(target, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return target
    except Exception:
        # A stray .json or .txt from gallery-dl lands here. Not an error.
        return None


def save_images(sources, dest):
    """
    Shrink every image into dest as 01.jpg, 02.jpg, ...

    Carousel order matters - it's the order you'd swipe through them - so the
    caller passes them already sorted and the numbering preserves it.
    """
    saved = []
    for source in sources:
        target = dest / f"{len(saved) + 1:02d}.jpg"
        if shrink(source, target):
            saved.append(target)
    return saved


def probe_duration(video):
    """Seconds of video. None if it can't be worked out."""
    probe = ffprobe_exe()
    if not probe:
        return None
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video)],
            capture_output=True, text=True,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return None


def keyframes(video, dest, count=KEYFRAME_COUNT):
    """
    Pull evenly spaced stills out of a video.

    Claude cannot watch a video. Stills plus the transcript are the closest
    thing to having seen it, at a fraction of what video would cost even if
    sending video were possible.
    """
    exe = ffmpeg_exe()
    duration = probe_duration(video)
    if not exe or not duration or duration <= 0:
        return []

    frames = []
    for index in range(count):
        # Spread across the middle, skipping the very start and end: the first
        # frame of a Reel is usually black and the last is usually a logo.
        position = duration * (index + 0.5) / count
        target = dest / f"frame-{index + 1:02d}.jpg"
        result = subprocess.run(
            [
                exe, "-nostdin", "-y", "-loglevel", "error",
                "-ss", f"{position:.2f}", "-i", str(video),
                "-frames:v", "1",
                # Shrink inside ffmpeg so a full-size still never hits the disk.
                "-vf", "scale=min(" + str(MAX_EDGE) + r"\,iw):-2",
                "-q:v", "4",
                str(target),
            ],
            capture_output=True,
        )
        if result.returncode == 0 and target.exists():
            frames.append(target)
    return frames


def extract_audio(video, dest):
    """
    Pull the audio out as a small mono file for transcription.

    16 kHz mono is what Whisper listens at anyway, and it makes the upload a
    fraction of the size, which matters on a free API tier.
    """
    exe = ffmpeg_exe()
    if not exe:
        return None
    target = dest / "audio.m4a"
    result = subprocess.run(
        [exe, "-nostdin", "-y", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(target)],
        capture_output=True,
    )
    if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
        return target
    return None


def _date(info):
    """yt-dlp gives 20260901; people read 2026-09-01."""
    raw = str(info.get("upload_date") or "")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw or "unknown"


def _clock(seconds):
    if not seconds:
        return None
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def write_post_md(info, dest, images=(), frames=(), transcript=None, media=None):
    """
    Write the file Claude reads first.

    Everything that can be words is words, because words are ~1 token each and
    pixels are ~900 per picture. The images are listed but not described - that
    is what Claude is for.
    """
    title = info.get("title") or info.get("description") or "Untitled post"
    lines = [f"# {str(title).strip()[:120]}", ""]

    kind = "post"
    if images:
        kind = f"carousel, {len(images)} image{'s' if len(images) != 1 else ''}"
    elif media:
        length = _clock(info.get("duration"))
        kind = "video" + (f", {length}" if length else "")

    facts = [
        ("Source", info.get("webpage_url") or info.get("original_url") or ""),
        ("Author", info.get("uploader") or info.get("uploader_id") or "unknown"),
        ("Posted", _date(info)),
        ("Type", kind),
    ]
    if info.get("like_count"):
        facts.append(("Likes", f"{info['like_count']:,}"))
    if media:
        facts.append(("Media file", str(media)))

    for label, value in facts:
        if value:
            lines.append(f"- **{label}:** {value}")

    caption = (info.get("description") or "").strip()
    if caption:
        lines += ["", "## Caption", "", caption]

    if transcript:
        lines += ["", "## Transcript", "", transcript.strip()]

    if images:
        lines += ["", "## Images", "", "In the order you'd swipe through them.", ""]
        lines += [f"![{i + 1}]({p.name})" for i, p in enumerate(images)]

    if frames:
        lines += ["", "## Stills", "", "Evenly spaced through the video.", ""]
        lines += [f"![still {i + 1}]({p.name})" for i, p in enumerate(frames)]

    target = dest / "post.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
