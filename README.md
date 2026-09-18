# media-download

A Chrome button that saves whatever you're looking at, sorted into folders under
your `Videos` directory. Instagram Reels and multi-picture posts, YouTube Shorts
and videos, TikToks, Facebook Reels.

Click the toolbar icon on a post's page, or right-click a link in a feed. That's
it — no terminal, no pasting URLs.

Two things it does that a plain downloader doesn't:

- **It queues.** Click download on one tab, switch to the next, click again.
  Links pile up and get worked through one at a time; nothing waits for anything.
  The badge counts what's left.
- **It writes a copy an AI can read.** Alongside the media, every download
  produces a folder with `post.md` (caption, author, date), the pictures shrunk
  to 1024px, stills from any video, and a transcript. See *Bundles*, below.

> **Windows only.** Built and tested on Windows 11 with Chrome.

---

## Install

**[→ Download the latest release](../../releases/latest)** (`video-downloader.zip`,
~32 MB), then follow **[INSTALL.md](INSTALL.md)**.

Five steps, about three minutes:

1. `winget install --id Gyan.FFmpeg -e` — then close that terminal
2. Unzip somewhere permanent
3. `chrome://extensions` → Developer mode → **Load unpacked** → the `extension` folder
4. `powershell -ExecutionPolicy Bypass -File install.ps1`
5. Reload the extension, pin it

You don't need Python — it's bundled inside `host.exe`.

**[INSTALL.md](INSTALL.md) has the full version**, including troubleshooting.

Not comfortable in a terminal? **[FOR-YOUR-AI.md](FOR-YOUR-AI.md)** ships in the
zip too. Point Claude at the folder and ask it to read that file: it is written
for the assistant rather than for you, and is explicit that loading the
extension and pinning it are yours to click — an assistant cannot reach inside
Chrome's settings, and one that claims otherwise sends you hunting for a button
nobody pressed.

## Using it

Click the toolbar icon and a panel opens:

```
┌─────────────────────────────┐
│  ⬇ Download what's on screen │
├─────────────────────────────┤
│ Downloading (2)             │
│                             │
│ ▸ TikTok · nimrashamid   ✕  │
│   ███████████░░░░░  68%     │
│                             │
│ ▸ YouTube · JayMech      ✕  │
│   starting…                 │
├─────────────────────────────┤
│ ✓ Instagram · Brody         │
│ ✗ Reddit · busy right now   │
│              Clear finished │
└─────────────────────────────┘
```

| | |
|---|---|
| **Download what you're looking at** | Open the panel → **Download what's on screen** |
| **In a feed** | Same button — it works out which post is on screen |
| **When it can't tell** | Right-click the post → **Download this** |
| **Queue several** | Keep going. They run one at a time, in order |
| **Stop one** | The **✕** on its row |
| **Stop everything** | Right-click the toolbar icon → **Stop everything** |

Cancelling takes effect immediately, whatever the download is doing — including
a link that is stuck waiting on a site that isn't answering.

The badge on the icon counts what's left, so you can see there's work in
progress without opening the panel.

## Bundles — the copy an AI can read

A **video** is saved as just the video file. There is nothing to explain about
an `.mp4` that the `.mp4` doesn't already contain, and writing a folder of
stills beside every one of them only made the Videos folder harder to look at.

A **picture post** has no single file to open, so it becomes a folder, named
`author - id` inside its platform's `Posts` folder:

```
Videos\Chrome Downloader Ext\2026-09-18\Instagram\Posts\someone - Cxyz123\
    post.md          caption, author, date, link — read this first
    01.jpg 02.jpg …  the pictures, in swipe order, 1024px on the long edge
    video-01.mp4     any clip the post also contained, kept whole
    frame-01.jpg …   five stills from that clip
    transcript.txt   what was said, if there was audio
```

**Why not a PDF.** What an AI pays to look at a picture depends only on its pixel
count — about `width × height / 750` tokens — and not on the file format. A PDF
page costs *more* than a plain image, because each page is both rendered to an
image and scraped for text. A ten-picture carousel is roughly 9,000 tokens as a
folder of shrunk JPEGs against roughly 20,000 as a PDF, and the folder is easier
to point at one picture inside.

Transcripts need a free Groq API key. Without one everything else still works and
the transcript is simply absent — see *Requirements*.

## Where files go

Everything lives under **one** folder in your own `Videos`, so it is obvious
what put it there and you can move or delete the lot in one go. Inside it,
there is **a folder for each day**, and inside a day, files are sorted by the
site they came from and then by what kind of thing they are:

```
Videos\Chrome Downloader Ext\
  2026-09-16\
  2026-09-17\
  2026-09-18\      <- a folder for each day you saved something

...and inside any one of those days, the same split by site:

  Instagram\   Reels    Posts   Stories
  YouTube\     Videos   Shorts
  TikTok\      Videos   Photos
  Reddit\      Videos   Posts
  Facebook\    Reels    Videos  Posts
  X\           Videos   Posts
  Snapchat\    Spotlight        Bluesky\    Posts
  Twitch\      Clips    Videos  Vimeo\      Videos
  Pinterest\   Images           Imgur\      Images
  SoundCloud\  Audio            Bandcamp\   Audio
  ...and Dailymotion, Streamable, Rumble, Kick, Bilibili, VK, Weibo,
     LinkedIn, 9GAG, Newgrounds, Flickr, DeviantArt, ArtStation,
     Pixiv, Tumblr, Tenor
  Other\       anything else
```

**It will try any site**, not only the ones above. The list is about *naming* —
those get a tidy folder and a sensible split inside it. A site nobody has taught
it about still downloads; it just lands in `Other`.

**Threads is the one deliberate gap.** Neither of the two downloaders underneath
has a Threads extractor, so there is nothing to hook up. Better an honest gap
than a menu entry that always fails.

A day's folder is made by the first download that needs it, so there is never
an empty folder for a day you saved nothing. If you used an earlier version -
one that wrote straight into `Videos\`, or one with no dated folders - what it
left behind is sorted into place the next time the helper starts — merged, never overwritten. `Screen Recordings` is
left alone, because it was never ours.

Paths in the table below are all relative to a day's folder, so in full:
`Videos\Chrome Downloader Ext\2026-09-18\Instagram\Reels`.

| Link | Lands in |
|---|---|
| `instagram.com/reel/...` | `Instagram\Reels` |
| `instagram.com/p/...` | `Instagram\Posts` |
| `youtube.com/shorts/...` | `YouTube\Shorts` |
| `youtube.com/watch?v=...` or `youtu.be/...` | `YouTube\Videos` |
| `tiktok.com/@user/video/...` (also `vm.` / `vt.`) | `TikTok\Videos` |
| `tiktok.com/@user/photo/...` | `TikTok\Photos` |
| `reddit.com/r/.../comments/...` | `Reddit\Videos` or `\Posts` |
| `facebook.com/reel/...`, `/videos/...`, `/posts/...` | `Facebook\...` |
| `x.com/user/status/...` | `X\Videos` or `\Posts` |
| anything else | `Other` |

Where the link itself says what it is — `/reel/`, `/shorts/` — that wins.
Otherwise a video goes in the site's video folder and pictures go in its post
folder. Files are named `Creator - Title [id].mp4`; the id keeps two videos
with the same title from overwriting each other.

## One click, one download

A profile page, a playlist, a subreddit or your own feed is a link to *many*
posts. Handing one to the downloader means downloading all of them, which is
how a folder fills up with things you never asked for. So those links are
refused, with a note saying to open the post itself or right-click it:

> That link is a profile, feed or playlist — not one post.

A link copied while a playlist is open carries `&list=` along with it. That is
stripped, so `watch?v=abc&list=PL123` downloads the one video `abc` rather than
the whole list. And if a listing somehow gets through anyway, the downloader
stops as soon as a file arrives belonging to a second post.

Capped at 1080p by default, since 4K is roughly ten times the bytes for something
you'll watch on a laptop. Change `MAX_HEIGHT` in `download.py` if you want 4K.

## How it works

Chrome extensions are sandboxed and **cannot start programs on your computer** —
that's the whole point of the sandbox. So this is two pieces:

```
Chrome extension  ──native messaging──>  host.exe  ──>  yt-dlp  ──>  .mp4
   (the button)                        (the worker)
```

`install.ps1` writes one registry value under `HKEY_CURRENT_USER` saying "this
extension may talk to this program". Chrome starts the helper when you click and
kills it when the download ends — **nothing runs in the background**, and no
admin rights are needed.

The extension runs only on the sites it lists, and only when you click it. On a
feed it reads that page to work out which post is on screen — see below — and
nothing about the page is stored or sent anywhere.

## Your login

Most posts are public and download without you being signed in to anything. Some
aren't: a private Instagram account, a Reddit that has decided it doesn't like
being asked.

**Nothing of your login is used until you say so.** The first attempt is always
made signed-out. If that fails *because* it needed an account, the panel says so
and offers a button:

> ✗ Instagram · somebody
> Needs your Instagram login.
> **[ Use my Instagram login ]**

Press it and that download is retried using the session already in your browser.
The answer is remembered for **that site only**, and the sites you've said yes to
are listed at the bottom of the panel with an ✕ to take it back. Nothing is ever
sent anywhere: it goes to the helper on your own machine, in a temporary file
deleted straight afterwards.

## When a site says no

Sites rate-limit. Reddit in particular will refuse a run of requests and then
keep refusing for a minute or two. When that happens you get:

> ✗ Reddit · Reddit is busy right now - try again in a minute.

...in about twenty seconds, rather than a download that appears to hang. If a
site keeps doing it, that is usually the one worth giving your login to.

## Which post did you mean?

TikTok, Instagram and YouTube are single-page apps: the address bar stays on the
feed while you scroll through posts. So on a feed the button can't just use the
tab's URL — that URL is the feed, and a feed is a link to *everybody* on it.
Clicking the button on TikTok used to send `tiktok.com/en/` and get refused,
which is why TikTok never worked.

Instead it looks at what is actually on screen: the post card filling most of
the window, and the link to that post inside that card. TikTok's cards carry no
link to their own video — the only long number in one belongs to the *sound*, so
using it would download the wrong thing. There the video's id comes from the
player, or from the feed data the page was built from, paired with the author
link beside it.

If it can't tell, it says so rather than guessing:

> Couldn't tell which post is on screen. Right-click the post itself and choose
> "Download this".

Right-clicking a post works on any site, always, because that hands over the
exact link you pointed at.

## Requirements

- Windows, Google Chrome (Edge and Brave work — see the note in INSTALL.md)
- [ffmpeg](https://ffmpeg.org/) — joins the separate video and audio streams,
  and cuts the stills
- Python is **not** required to use it; only to develop it

**Optional — transcripts.** Get a free key at
[console.groq.com/keys](https://console.groq.com/keys), then run once:

```powershell
setx GROQ_API_KEY "gsk_your_key_here"
```

Open a new terminal afterwards. Without a key, every download still works and
`transcript.txt` is simply not written — a missing transcript never fails a
download.

**Logged-in content.** Instagram carousels and Facebook Reels usually need a
session. The extension reads your own Chrome cookies for the site and hands them
to the helper for the duration of one download; they are written to a temporary
file which is deleted immediately afterwards, and they never leave the machine.
Chrome can stay open — this is why it doesn't use yt-dlp's
`cookiesfrombrowser`, which requires closing it.

---

## Development

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then the command-line version works on its own:

```powershell
python download.py                                    # paste links one at a time
python download.py "https://www.youtube.com/watch?v=..."   # or one and done
```

### Layout

| Path | What it is |
|---|---|
| `download.py` | Works out what a link is, then fetches it — folder sorting, format selection |
| `bundle.py` | Builds the AI-readable folder — shrinking, stills, `post.md` |
| `transcribe.py` | Optional, free audio → text via Groq Whisper |
| `chrome-extension/` | The button. `background.js` is the whole extension |
| `native-host/host.py` | Bridges Chrome's native messaging to `download.py`, and holds the queue |
| `native-host/install.ps1` | Registers the host with Chrome |
| `native-host/make-release.py` | Builds the shareable zip |

### Building a release

One command, from `native-host`:

```powershell
..\.venv\Scripts\python.exe make-release.py
```

It freezes `host.exe` from `host.spec`, checks that the frozen build actually
starts, and writes `Desktop\video-downloader.zip`. Add `--no-build` to package
an existing build without freezing it again.

**`host.spec` is the file that matters.** PyInstaller finds imports by reading
code, and almost nothing here is reachable that way: `download`, `bundle` and
`transcribe` are imported from the project root, and both yt-dlp and gallery-dl
choose a site's extractor at runtime by name. Anything missing from the spec
fails only in the shared build, only on the site whose extractor didn't come
along — which is why the build runs the exe before packaging it.

`--onedir`, not `--onefile`: a one-file exe unpacks itself on **every** run, which
adds seconds to every single click.

`make-release.py` refuses to build if the private key, a machine-specific host
manifest, or a log file would end up in the archive.

### Developing against source, not the frozen build

The exe is a snapshot, so while Chrome points at it **every edit to the Python
is invisible**. That failure looks exactly like a broken change. Point Chrome at
the source instead:

```powershell
cd native-host
powershell -ExecutionPolicy Bypass -File install.ps1 -Source
```

That writes the host manifest against `host.bat`, which runs `host.py` from the
venv, so a reload of the extension picks up every edit. Re-run `install.ps1`
without `-Source` to go back to the frozen build.

### The extension ID is fixed

`manifest.json` carries a `key`, so Chrome derives the ID from that key instead of
from the folder path. It is `kkfepfljdgflemilngnbpkdadanpaleb` on every machine —
which is why `install.ps1` doesn't have to ask for it.

`native-host/make-key.py` generated it. **Don't run it again**: a new key means a
new ID, breaking every existing install. It refuses to overwrite an existing key
for exactly that reason. The private key is gitignored and never shipped; it's
only needed to publish a packed `.crx`, which this project doesn't do.

### Keeping it working

Instagram and YouTube change constantly and yt-dlp gets patched to keep up. The
version frozen into `host.exe` will go stale:

```powershell
pip install --upgrade yt-dlp
```

then rebuild and cut a new release.

## Why not the Chrome Web Store?

The store ships the extension only — it cannot install `host.exe` or write the
registry entry, so a store install would be a button that always errors. Google
also rejects YouTube downloaders, since it owns YouTube and YouTube's terms don't
permit downloading.

## A note on what you download

Saving videos for your own reference is one thing; re-uploading someone else's
video as your own is a different one. Please know the difference.

## License

MIT — see [LICENSE](LICENSE). Uses [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense) and requires [ffmpeg](https://ffmpeg.org/) (LGPL/GPL), neither of
which is included in this repository.
