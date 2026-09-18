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
from collections import namedtuple
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

import bundle
import transcribe
from bundle import find_ffmpeg

# ---------------------------------------------------------------
#  WHERE THINGS GET SAVED
#
#  Everything this tool writes lives under ONE folder, so it is obvious what
#  put it there and it can be moved or deleted in one go:
#
#      Videos\Chrome Downloader Ext\<Platform>\<Kind>
#
#      ...\Instagram\Reels      ...\YouTube\Videos
#      ...\Instagram\Posts      ...\YouTube\Shorts
#
#  If you rename a folder in Explorer, change the name here too.
# ---------------------------------------------------------------
HOME_VIDEOS = Path.home() / "Videos"
VIDEOS = HOME_VIDEOS / "Chrome Downloader Ext"
OTHER = VIDEOS / "Other"   # anything from a site not listed below

# folder  - the platform's own folder under Videos
# video   - where a video goes when the link doesn't say
# post    - where a picture post goes when the link doesn't say
# by_path - bits of the link that name the sub-folder outright; these win,
#           because "/reel/" is a surer signal than what the file turned out
#           to be. Checked in order.
Platform = namedtuple("Platform", "folder video post by_path")

PLATFORMS = {
    # --- the ones most people actually use -------------------------------
    "instagram.com": Platform("Instagram", "Reels", "Posts", (
        ("/reel/", "Reels"), ("/reels/", "Reels"),
        ("/p/", "Posts"), ("/tv/", "Posts"), ("/stories/", "Stories"),
    )),
    "youtube.com": Platform("YouTube", "Videos", "Videos", (
        ("/shorts/", "Shorts"),
    )),
    "youtu.be": Platform("YouTube", "Videos", "Videos", ()),
    "tiktok.com": Platform("TikTok", "Videos", "Photos", (
        ("/video/", "Videos"), ("/photo/", "Photos"),
    )),
    "reddit.com": Platform("Reddit", "Videos", "Posts", ()),
    "redd.it": Platform("Reddit", "Videos", "Posts", ()),
    "facebook.com": Platform("Facebook", "Videos", "Posts", (
        ("/reel/", "Reels"), ("/videos/", "Videos"), ("/video.php", "Videos"),
        ("/watch", "Videos"), ("/photo", "Posts"), ("/posts/", "Posts"),
    )),
    "fb.watch": Platform("Facebook", "Videos", "Posts", ()),
    "x.com": Platform("X", "Videos", "Posts", ()),
    "twitter.com": Platform("X", "Videos", "Posts", ()),
    "snapchat.com": Platform("Snapchat", "Spotlight", "Posts", (
        ("/spotlight/", "Spotlight"),
    )),
    "bsky.app": Platform("Bluesky", "Videos", "Posts", ()),

    # --- video sites -------------------------------------------------------
    "twitch.tv": Platform("Twitch", "Videos", "Videos", (
        ("/clip/", "Clips"), ("/clips/", "Clips"),
    )),
    "vimeo.com": Platform("Vimeo", "Videos", "Videos", ()),
    "dailymotion.com": Platform("Dailymotion", "Videos", "Videos", ()),
    "dai.ly": Platform("Dailymotion", "Videos", "Videos", ()),
    "streamable.com": Platform("Streamable", "Videos", "Videos", ()),
    "rumble.com": Platform("Rumble", "Videos", "Videos", ()),
    "kick.com": Platform("Kick", "Videos", "Videos", (
        ("/clips/", "Clips"),
    )),
    "bilibili.com": Platform("Bilibili", "Videos", "Videos", ()),
    "vk.com": Platform("VK", "Videos", "Posts", ()),
    "weibo.com": Platform("Weibo", "Videos", "Posts", ()),
    "linkedin.com": Platform("LinkedIn", "Videos", "Posts", ()),
    "9gag.com": Platform("9GAG", "Videos", "Posts", ()),
    "newgrounds.com": Platform("Newgrounds", "Videos", "Art", ()),

    # --- picture-first sites ----------------------------------------------
    "pinterest.com": Platform("Pinterest", "Videos", "Images", ()),
    "pin.it": Platform("Pinterest", "Videos", "Images", ()),
    "imgur.com": Platform("Imgur", "Videos", "Images", ()),
    "flickr.com": Platform("Flickr", "Videos", "Images", ()),
    "deviantart.com": Platform("DeviantArt", "Videos", "Art", ()),
    "artstation.com": Platform("ArtStation", "Videos", "Art", ()),
    "pixiv.net": Platform("Pixiv", "Videos", "Art", ()),
    "tumblr.com": Platform("Tumblr", "Videos", "Posts", ()),
    "tenor.com": Platform("Tenor", "Videos", "Images", ()),

    # --- audio -------------------------------------------------------------
    "soundcloud.com": Platform("SoundCloud", "Audio", "Audio", ()),
    "bandcamp.com": Platform("Bandcamp", "Audio", "Audio", ()),
}

# What a link to ONE post looks like on each site. A link matching none of
# these is a profile, a feed or a playlist - and handing one of those to the
# downloader is what used to fetch somebody's entire account in one click.
#
# A platform with no entry here is not unguarded: it falls through to the
# entry-count check in fetch(), which refuses anything yt-dlp reports as a
# long list. That is what lets new sites work without each needing a rule.
SINGLE_ITEM = {
    "Instagram":   ("/p/", "/reel/", "/reels/", "/tv/", "/stories/"),
    "YouTube":     ("/watch", "/shorts/", "/live/", "/embed/", "/clip/"),
    "TikTok":      ("/video/", "/photo/"),
    "Reddit":      ("/comments/", "/s/"),
    "Facebook":    ("/reel/", "/videos/", "/video.php", "/watch", "/photo",
                    "/posts/", "/permalink", "/story.php", "/share/"),
    "X":           ("/status/",),
    "Snapchat":    ("/spotlight/", "/p/"),
    "Bluesky":     ("/post/",),
    "Twitch":      ("/clip/", "/clips/", "/videos/"),
    "Pinterest":   ("/pin/",),
    "Tumblr":      ("/post/", "/image/"),
    "DeviantArt":  ("/art/",),
    "ArtStation":  ("/artwork/",),
    "Pixiv":       ("/artworks/",),
    "Newgrounds":  ("/portal/view/", "/art/view/", "/audio/listen/"),
    "9GAG":        ("/gag/",),
}

# A share link is short on purpose: it carries no path worth reading, and it
# always points at exactly one thing. Never treat one as a listing.
SHORT_LINK_HOSTS = ("youtu.be", "vm.tiktok.com", "vt.tiktok.com",
                    "redd.it", "fb.watch", "t.co")

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


# Query parameters that are about tracking who shared what, never about which
# post you meant. A share sheet adds several; img_index in particular says
# "start at picture 9", which is not a thing we want to honour when the point
# is to get all of them.
JUNK_PARAMS = {
    "igsh", "igsi", "img_index", "utm_source", "utm_medium", "utm_campaign",
    "utm_content", "utm_term", "fbclid", "gclid", "share_id", "si", "feature",
    "_nc_cat", "ref_src", "ref_url", "s", "t", "is_from_rle",
}

# Parameters that quietly turn a link to one video into a link to a whole
# list. Copy a link while a playlist is open and "&list=" comes with it; left
# in, the downloader sees a playlist and fetches every video on it.
#
# These can only be dropped from a link that already names a single video. On
# /playlist the list IS the link, and that case is refused by
# container_reason() rather than silently turned into a broken URL.
PLAYLIST_PARAMS = {"list", "index", "start_radio", "pp", "ab_channel"}


def clean_link(text):
    """
    Tidy up a pasted link.

    Copying a link can quietly bring along invisible characters or wrapping
    quotes. Without this they look like a real link and fail confusingly.
    A link shared from an app also arrives carrying tracking parameters, which
    get dropped here - carefully, because YouTube's ?v= is a query parameter
    too and dropping the whole query string would break it.
    """
    # Zero-width and byte-order-mark characters some apps sneak in.
    for junk in ("﻿", "​", "‌", "‍", "⁠"):
        text = text.replace(junk, "")
    text = text.strip().strip('"').strip("'").strip()

    # A fragment is never part of what you want downloaded - Reddit's lightbox
    # links end in "#lightbox" - and the early return below used to skip this
    # entirely for any link without a "?", so the fragment rode along.
    if "?" not in text:
        return text.split("#", 1)[0]

    parsed = urlsplit(text)

    drop = set(JUNK_PARAMS)
    host = (parsed.hostname or "").lower()
    if "/watch" in parsed.path.lower() or _host_is(host, "youtu.be"):
        drop |= PLAYLIST_PARAMS

    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in drop]
    return urlunsplit(parsed._replace(query=urlencode(kept), fragment=""))


def _host_is(host, domain):
    """True if host is that domain or something under it - never a lookalike."""
    return host == domain or host.endswith("." + domain)


def site_of(url):
    """The Platform a link belongs to, or None for anywhere else."""
    host = (urlsplit(url).hostname or "").lower()
    for domain, platform in PLATFORMS.items():
        if _host_is(host, domain):
            return platform
    return None


def pick_folder(url, media_kind="video"):
    """
    Look at the link and decide which folder this belongs in.

    media_kind ("video" or "post") is the fallback for links whose path does
    not say - a Reddit link, say, which looks the same whether the post turns
    out to be a clip or a set of pictures.
    """
    platform = site_of(url)
    if not platform:
        return OTHER

    path = (urlsplit(url).path or "").lower()
    for marker, bucket in platform.by_path:
        if marker in path:
            return VIDEOS / platform.folder / bucket

    bucket = platform.post if media_kind == "post" else platform.video
    return VIDEOS / platform.folder / bucket


def container_reason(url):
    """
    Say why a link is a listing rather than one post - or None if it names one.

    This is the guard behind "one click, one download". A profile page, a
    playlist or a subreddit front page is a perfectly good link, but handing
    one to the downloader means downloading everything behind it. Better to
    say so than to fill the folder with someone's whole account.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = ((parts.path or "").rstrip("/") or "/").lower()

    if any(_host_is(host, d) for d in SHORT_LINK_HOSTS):
        return None  # a share link is short precisely because it names one thing

    if path == "/":
        return (
            "That is the front page of " + (host or "the site") + ", not a "
            'post. Open the post itself, or right-click it and choose '
            '"Download this".'
        )

    platform = site_of(url)
    if not platform:
        return None  # some other site; no way to tell, so let it try

    wanted = SINGLE_ITEM.get(platform.folder)
    if wanted and not any(marker in path for marker in wanted):
        return (
            "That link is a profile, feed or playlist - not one post. Open "
            'the post itself, or right-click it and choose "Download this".'
        )
    return None


# How hard to try before giving up. These are deliberately small.
#
# A rate-limited site (Reddit answers 429 freely) used to take 141 SECONDS to
# fail, because every layer retried with backoff: yt-dlp's own extractor
# retries, then "retries" on top. Nothing could be cancelled during that, so
# the whole thing looked frozen. Failing in twenty seconds with "try again in
# a minute" is far more useful than succeeding on the fourth attempt three
# minutes later.
SOCKET_TIMEOUT = 10
RETRIES = 1
EXTRACTOR_RETRIES = 1


def _base_options(cookiefile=None, should_stop=None):
    """The yt-dlp settings shared by looking and downloading."""
    options = {
        "socket_timeout": SOCKET_TIMEOUT,
        "retries": RETRIES,
        "extractor_retries": EXTRACTOR_RETRIES,
        "no_warnings": True,
        "quiet": True,
        "noprogress": True,
    }

    if should_stop:
        # match_filter is called during EXTRACTION, before any bytes move. That
        # is the whole point: the progress hook only fires once a transfer is
        # underway, so it can't interrupt a link that is stuck resolving.
        def _abort_if_cancelled(info, incomplete=False):
            should_stop()
            return None

        options["match_filter"] = _abort_if_cancelled
    if cookiefile:
        # Being logged in is what makes Instagram and Facebook work at all.
        # The extension hands us a cookie file; see background.js.
        options["cookiefile"] = str(cookiefile)

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        options["ffmpeg_location"] = str(ffmpeg)
    return options


def probe(url, cookiefile=None, should_stop=None):
    """
    Ask what's behind a link without downloading it.

    Returns (info, error). Exactly one of the two is set:

      (info, None)   yt-dlp could read the link
      (None, error)  it could not, and THIS is why

    Returning the error is the whole point. It used to return a bare None for
    both "this post is only pictures" and "yt-dlp failed", which are opposite
    situations: the first should go to gallery-dl, the second should be
    reported. Collapsing them sent YouTube links to gallery-dl, which has no
    YouTube extractor, and the real message - the one saying what actually went
    wrong - was gone by then. See fetch().

    noplaylist is deliberately NOT set here. A multi-picture Instagram post is a
    playlist as far as yt-dlp is concerned, so switching playlists off is what
    used to make a ten-picture post arrive as one picture.
    """
    options = dict(_base_options(cookiefile, should_stop),
                   extract_flat=False, skip_download=True)
    try:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False), None
    except Exception as err:  # noqa: BLE001 - the caller decides what it means
        return None, err


def has_video(info):
    """
    True if yt-dlp found an actual VIDEO stream to fetch - not just any stream.

    "Has formats" is not the same question. A TikTok slideshow comes back with
    exactly one format, the sound, and answering yes to that saved the audio
    track as an .mp3 and called it a video. A post with no video in it is a
    picture post, which is gallery-dl's job - so getting this wrong doesn't
    just mislabel the answer, it sends the link to the wrong tool.

    A format with no vcodec at all is counted as video: plenty of extractors
    leave it unset, and only an explicit "none" actually means "no picture".
    """
    if not info:
        return False
    if info.get("entries"):
        return False

    formats = info.get("formats")
    if formats:
        return any(fmt.get("vcodec") != "none" for fmt in formats)

    return bool(info.get("url")) and info.get("vcodec") != "none"


def download(url, extra_options=None, cookiefile=None, should_stop=None):
    """
    Download a single video. Returns the saved file path.

    extra_options is for callers that need to tweak yt-dlp without copying the
    settings below - host.py uses it to attach a progress hook.
    """
    # Not created here on purpose: yt-dlp makes the folder itself when it has
    # something to write. Creating it up front left an empty "YT Videos"
    # sitting there every time a download failed.
    folder = pick_folder(url, "video")

    options = dict(_base_options(cookiefile, should_stop))
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


class _DifferentPost(Exception):
    """A file turned up belonging to some other post. Stop right there."""


# No single post has more files than this. It is the backstop for a listing
# that somehow gets past container_reason() - the download stops rather than
# paging through an account.
MAX_FILES_PER_POST = 50

# Keys that identify the POST a gallery-dl file belongs to. Deliberately only
# post-level keys: a carousel's images each carry their own "id", so keying on
# that would read a ten-picture post as ten different posts and stop after one.
POST_ID_KEYS = ("post_shortcode", "post_id", "tweet_id", "submission_id")


def _post_identity(keywords):
    """Which post a gallery-dl file belongs to, or None if it won't say."""
    for key in POST_ID_KEYS:
        value = keywords.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _limit_gallery_retries(gconfig):
    """
    Give gallery-dl the same short patience yt-dlp has.

    Both tools get asked about the same link, and both retry a 429 with
    backoff. Capping only yt-dlp just moved the three-minute wait one function
    further down - the second tool sat on the same rate limit for just as long.
    A budget has to cover every layer that can spend it.
    """
    gconfig.set((), "retries", 1)
    gconfig.set((), "timeout", SOCKET_TIMEOUT)
    gconfig.set((), "sleep-request", 0)


def gallery_supports(url):
    """
    True if gallery-dl has an extractor for this link.

    This is the question that decides whether "yt-dlp found no video" means
    "it's a picture post, hand it over" or "yt-dlp failed and nobody else can
    help". gallery-dl has no YouTube extractor, so a failed YouTube probe used
    to arrive here and die as NoExtractorError - throwing away the yt-dlp
    message that said what was actually wrong.
    """
    try:
        from gallery_dl import extractor
        return extractor.find(url) is not None
    except Exception:  # noqa: BLE001 - never let this check be the failure
        return False


def _describe(err):
    """One readable line for an exception, however empty it is."""
    text = str(err).strip()
    # yt-dlp prefixes its own messages; saying ERROR twice helps nobody.
    if text.startswith("ERROR: "):
        text = text[len("ERROR: "):].strip()
    if text and text != "None":
        return text
    return type(err).__name__


# What went wrong, in a form the extension can act on. The tag drives what the
# panel offers - only "needs_login" gets a "use my login" button - and the
# sentence is what a person reads. Both matter: a friend who is handed this
# tool has no idea what a 429 is, and no reason to learn.
#
# Order matters: the first match wins, so the specific patterns come before
# the vague ones.
ERROR_KINDS = (
    ("needs_login", (
        "login required", "log in", "sign in", "requires authentication",
        "private", "not authorized", "account is private", "age-restricted",
        "age restricted", "confirm your age", "cookies", "authentication",
        "you must be logged", "members-only", "subscriber",
    )),
    ("rate_limited", (
        "429", "too many requests", "rate limit", "rate-limit",
        "try again later", "temporarily blocked", "ip address is blocked",
    )),
    ("unavailable", (
        "unavailable", "not available", "has been removed", "deleted",
        "does not exist", "not found", "404", "geo", "blocked in your country",
        "no longer", "terminated", "suspended",
    )),
    ("no_media", (
        "no video formats", "nothing downloadable", "no media",
        "unsupported url", "no suitable", "no extractor",
    )),
)

# The sentence shown for each tag. "failed" has none: it shows the real
# message, because at that point the tool's own words are the best available.
FRIENDLY = {
    "needs_login": "Needs your {site} login.",
    "rate_limited": "{site} is busy right now - try again in a minute.",
    "unavailable": "This post isn't available any more.",
    "no_media": "There's nothing downloadable on this one.",
    "not_a_post": None,
    "failed": None,
}


def site_name(url):
    """The platform's display name, or the bare domain for anywhere else."""
    platform = site_of(url)
    if platform:
        return platform.folder
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "That site"


def classify(error, url=""):
    """
    Turn a failure into (tag, sentence a person can act on).

    Everything the panel shows comes through here, so a raw yt-dlp string never
    reaches someone who didn't ask for one.
    """
    text = _describe(error).lower()

    if "profile, feed or playlist" in text or "front page of" in text:
        return "not_a_post", _describe(error)

    for tag, needles in ERROR_KINDS:
        if any(needle in text for needle in needles):
            template = FRIENDLY.get(tag)
            return tag, (template.format(site=site_name(url)) if template
                         else _describe(error))

    return "failed", _describe(error)


def _probe_failure(url, error):
    """The message for a link nothing could read."""
    return (
        f"Couldn't read that link. {_describe(error)}"
        if error is not None
        else f"Nothing downloadable was found at {url}"
    )


def gallery_fetch(url, into, cookiefile=None, should_stop=None):
    """
    Download every picture and clip in ONE post, using gallery-dl.

    yt-dlp is a video tool and treats a picture as a video with no formats.
    gallery-dl is the one built for posts, so multi-picture Instagram posts and
    the image half of a mixed post go through here.

    gallery-dl is happy to keep going into the next post, and the one after
    that, which is how a single click used to turn into fifty downloads. So the
    first post's id is remembered and anything belonging to a different one
    ends the job before it is written.

    Returns the files it wrote, in the order you'd swipe through them.
    """
    from gallery_dl import config as gconfig, job as gjob

    gconfig.clear()
    _limit_gallery_retries(gconfig)
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
    belongs_to = []   # the first post id seen, once there is one
    stop = []         # set when we've decided we're done, whatever run() does

    class OneItemOnly(gjob.DownloadJob):
        def handle_url(self, url, keywords):
            # Raising is how we stop early, but gallery-dl catches a lot on its
            # way out. This flag is what guarantees nothing more is written
            # even if the exception never reaches run()'s caller.
            if stop:
                return

            # The only cancel checkpoint on this side. gallery-dl has no
            # progress hook of its own, so without this a picture post could
            # not be interrupted at all once it started.
            if should_stop:
                should_stop()

            ident = _post_identity(keywords)
            if ident is not None:
                if not belongs_to:
                    belongs_to.append(ident)
                elif ident != belongs_to[0]:
                    stop.append(True)
                    raise _DifferentPost

            if len(arrived) >= MAX_FILES_PER_POST:
                stop.append(True)
                raise _DifferentPost

            super().handle_url(url, keywords)
            path = getattr(getattr(self, "pathfmt", None), "path", None)
            if path:
                arrived.append(Path(path))

    try:
        OneItemOnly(url).run()
    except _DifferentPost:
        pass  # everything on disk belongs to the post that was asked for

    on_disk = {p for p in Path(into).iterdir() if p.is_file()}
    # Anything the hook caught, in arrival order, then anything it missed.
    ordered = [p for p in arrived if p in on_disk]
    return ordered + sorted(on_disk - set(ordered))


def gallery_metadata(url, cookiefile=None):
    """Caption, author and id for a post, without downloading anything."""
    from gallery_dl import config as gconfig, job as gjob

    gconfig.clear()
    _limit_gallery_retries(gconfig)
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


def _post_bundle(url, info, cookiefile, on_status=None, probe_error=None,
                 should_stop=None):
    """
    Download a multi-picture post and turn it into a readable folder.

    probe_error is whatever yt-dlp said before we got here, if anything. If
    gallery-dl also can't do anything with the link, that earlier message is
    the useful one - it is the tool that was actually meant to handle it.
    """
    try:
        if not info or not info.get("id"):
            info = {**(info or {}), **gallery_metadata(url, cookiefile)}
    except Exception as err:  # noqa: BLE001
        raise DownloadError(_probe_failure(url, probe_error or err)) from err
    info.setdefault("webpage_url", url)

    with tempfile.TemporaryDirectory(prefix="mediadl-") as staging:
        if on_status:
            on_status("fetching post")
        try:
            grabbed = gallery_fetch(url, staging, cookiefile, should_stop)
        except _DifferentPost:
            raise
        except Exception as err:  # noqa: BLE001
            raise DownloadError(_probe_failure(url, probe_error or err)) from err

        images = [p for p in grabbed if p.suffix.lower() in IMAGE_SUFFIXES]
        clips = [p for p in grabbed if p.suffix.lower() in VIDEO_SUFFIXES]

        # Say nothing came back BEFORE making a folder to put it in. A folder
        # containing only a post.md about a download that failed is exactly
        # the litter this whole change is meant to stop.
        if not images and not clips:
            # If yt-dlp had already said something specific, that is the
            # useful sentence - "nothing was found" describes the symptom,
            # "Requested post not available" describes the cause.
            raise DownloadError(_probe_failure(url, probe_error))

        # Created here, not earlier: only once there is something to write.
        dest = bundle.post_dir(pick_folder(url, "post"), info, url)

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

    return Result("post", media=None, folder=dest)


def _video_bundle(url, cookiefile, extra_options, should_stop=None):
    """
    Download a video. That is the whole job - a video is just a file.

    It used to also write a folder of stills, a transcript and a post.md
    beside every video, in a separate tree. That turned every download into
    two things in two places, and for a video the file itself is what you
    wanted. The readable folder is now built only for picture posts, where
    there is no single file to open. A video download is quicker for it: no
    ffmpeg pass for stills, no audio upload for a transcript.
    """
    saved, _ = download(url, extra_options, cookiefile, should_stop)
    return Result("video", media=saved, folder=None)


# A single post is never this many separate items. Anything longer that yt-dlp
# hands back is a playlist, a profile or a channel - and this is the guard for
# every site that has no SINGLE_ITEM rule of its own, which is what makes it
# safe to point this tool at a site nobody has taught it about.
MAX_ENTRIES_PER_POST = 15


def _is_listing(info):
    """True if yt-dlp says this link is a long list rather than one post."""
    entries = (info or {}).get("entries")
    if not entries:
        return False
    try:
        return len(entries) > MAX_ENTRIES_PER_POST
    except TypeError:
        # A lazy generator: yt-dlp didn't count them, so we can't either
        # without draining it. Let the per-post caps downstream handle it.
        return False


def _attempt(url, cookiefile, extra_options, on_status, should_stop=None):
    """One go at a link, with one particular login situation."""
    info, error = probe(url, cookiefile, should_stop)

    if _is_listing(info):
        raise DownloadError(
            "That link is a profile, feed or playlist - not one post. Open "
            'the post itself, or right-click it and choose "Download this".'
        )

    if has_video(info):
        return _video_bundle(url, cookiefile, extra_options, should_stop)

    # yt-dlp failed AND nothing else can read this link: say what yt-dlp said.
    # This is the case that used to become "NoExtractorError: None".
    if error is not None and not gallery_supports(url):
        raise DownloadError(_probe_failure(url, error))

    # Either several pieces of media, or nothing yt-dlp recognises as video -
    # both of which mean pictures are involved.
    return _post_bundle(url, info, cookiefile, on_status, probe_error=error,
                        should_stop=should_stop)


def fetch(url, cookiefile=None, extra_options=None, on_status=None,
          should_stop=None):
    """
    The one entry point. Works out what the link is and does the right thing.

    Returns a Result. Raises DownloadError like yt-dlp does, so callers that
    already handle that keep working.

    cookiefile is the caller's decision, not ours: nothing is sent unless the
    extension already asked the user about that site. If a download fails even
    though a login WAS sent, it is tried once more logged out - the same jar
    that rescues one site can be what a different one objects to.

    should_stop() is called at every point where stopping is possible, and
    raises whatever the caller wants to stop with.
    """
    # Before anything touches the network: is this one post, or a list of them?
    reason = container_reason(url)
    if reason:
        raise DownloadError(reason)

    try:
        return _attempt(url, cookiefile, extra_options, on_status, should_stop)
    except DownloadError as first:
        # A cancellation arrives here wrapped in a DownloadError, because
        # yt-dlp wraps whatever a hook raises. Retrying one would restart the
        # download the user just stopped - and on a slow failure, double the
        # wait they cancelled to escape.
        if _was_cancelled(first) or not cookiefile:
            raise
        if on_status:
            on_status("retrying logged out")
        try:
            return _attempt(url, None, extra_options, on_status, should_stop)
        except DownloadError:
            raise first from None


def _was_cancelled(error):
    """True if this failure is really a stop request wearing a disguise."""
    cause = getattr(error, "__cause__", None)
    wrapped = (getattr(error, "exc_info", None) or (None, None, None))[1]
    for candidate in (error, cause, wrapped):
        if candidate is None:
            continue
        if type(candidate).__name__ in ("Cancelled", "Stopped"):
            return True
    return False


# Folders this tool used to write straight into Videos\, before everything
# moved under one master folder. Screen Recordings is deliberately absent - it
# was never ours to move.
LEGACY_FOLDERS = ("Instagram", "YouTube", "TikTok", "Facebook", "X", "Reddit",
                  "Other", "YT Shorts", "YT Videos", "IG Reels", "Posts")


def migrate_folders():
    """
    Move anything an older version left loose in Videos into the master folder.

    Runs at start-up and does nothing at all on a fresh install or once it has
    already run. Merges rather than overwrites: a file that already exists at
    the destination is left alone, so running this twice is safe.
    """
    moved = []
    for name in LEGACY_FOLDERS:
        source = HOME_VIDEOS / name
        if not source.is_dir() or source == VIDEOS:
            continue
        destination = VIDEOS / name
        try:
            destination.mkdir(parents=True, exist_ok=True)
            for item in list(source.iterdir()):
                target = destination / item.name
                if target.exists():
                    continue
                shutil.move(str(item), str(target))
            # Only remove it if it actually emptied; anything left is a
            # collision worth keeping rather than a folder worth deleting.
            if not any(source.iterdir()):
                source.rmdir()
            moved.append(name)
        except OSError:
            continue  # a locked file must never stop the downloader starting
    return moved


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

    migrate_folders()

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
