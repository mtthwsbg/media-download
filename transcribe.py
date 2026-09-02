"""
transcribe.py - turn a video's audio into text, for free.

Claude can't watch a video, but it can read one. A transcript costs about a
token per word, against roughly 900 tokens for a single still image, so this is
by far the cheapest way to make a Reel or a YouTube video legible.

It runs on Groq's free Whisper endpoint. If there is no API key set up, this
file quietly does nothing - a missing transcript must never turn a download that
worked into a download that failed.

To switch it on, once, in PowerShell:

    setx GROQ_API_KEY "gsk_your_key_here"

Then open a new terminal. Get a key free at https://console.groq.com/keys.
"""

import os
from pathlib import Path

import requests

ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"

# Groq's free tier caps the upload. bundle.extract_audio() writes 16 kHz mono at
# 48 kbps, so this is about 70 minutes of audio - far past anything on Instagram.
MAX_BYTES = 25 * 1024 * 1024

TIMEOUT_SECONDS = 120


def api_key():
    """
    The key, or None.

    Environment first, then a plain file, so there is a way to set this up that
    doesn't involve editing environment variables.
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key

    stored = Path.home() / ".claude" / "groq-key.txt"
    try:
        key = stored.read_text(encoding="utf-8").strip()
        return key or None
    except OSError:
        return None


def transcribe(audio):
    """
    Text of what's said in an audio file, or None.

    Every failure path returns None rather than raising. The caller is in the
    middle of a download that has already succeeded; nothing here is worth
    losing that over.
    """
    audio = Path(audio)
    key = api_key()
    if not key or not audio.exists():
        return None
    if audio.stat().st_size > MAX_BYTES:
        return None

    try:
        with audio.open("rb") as handle:
            response = requests.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (audio.name, handle, "audio/m4a")},
                data={"model": MODEL, "response_format": "text"},
                timeout=TIMEOUT_SECONDS,
            )
        if response.status_code != 200:
            return None
        text = response.text.strip()
        return text or None
    except Exception:
        return None


def transcribe_video(video, dest):
    """
    Extract audio from a video, transcribe it, write transcript.txt.

    Returns the text, or None if any step didn't happen. The audio file is
    deleted afterwards - it exists only to be uploaded, and leaving a stray
    .m4a beside every post is clutter.
    """
    from bundle import extract_audio  # imported here so bundle.py stays optional

    if not api_key():
        return None

    audio = extract_audio(video, dest)
    if not audio:
        return None

    try:
        text = transcribe(audio)
    finally:
        try:
            audio.unlink()
        except OSError:
            pass

    if text:
        (dest / "transcript.txt").write_text(text, encoding="utf-8")
    return text
