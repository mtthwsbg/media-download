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
~19 MB), then follow **[INSTALL.md](INSTALL.md)**.

Five steps, about three minutes:

1. `winget install --id Gyan.FFmpeg -e` — then close that terminal
2. Unzip somewhere permanent
3. `chrome://extensions` → Developer mode → **Load unpacked** → the `extension` folder
4. `powershell -ExecutionPolicy Bypass -File install.ps1`
5. Reload the extension, pin it

You don't need Python — it's bundled inside `host.exe`.

**[INSTALL.md](INSTALL.md) has the full version**, including troubleshooting, and
is written so you can hand it to an AI assistant and have it walk you through.

## Using it

| | |
|---|---|
| **On a post's own page** | Click the blue arrow in the toolbar |
| **In a feed** (page isn't the post) | Right-click the picture or link → **Download this** |
| **Queue several** | Just keep clicking. Every click adds one; they run in order |
| **Cancel the one running** | Right-click the toolbar icon → **Cancel current download** |
| **Drop everything queued** | Right-click the toolbar icon → **Clear the whole queue** |

The badge shows how many are left to go. Hover the icon for the percentage and
what it's currently doing. A notification names each file as it lands.

Left-click never cancels. With eight tabs to get through, a click that sometimes
means "stop" is a click you can't make quickly.

## Bundles — the copy an AI can read

Every download also writes a folder under `Videos\Posts`, named
`site - author - id`:

```
Videos\Posts\instagram - someone - Cxyz123\
    post.md          caption, author, date, link — read this first
    01.jpg 02.jpg …  the pictures, in swipe order, 1024px on the long edge
    frame-01.jpg …   five stills, if there was a video
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

Sorted by where the link came from, under your own `Videos` folder:

| Link | Lands in |
|---|---|
| `instagram.com/...` | `Videos\IG Reels` |
| `tiktok.com/...` (also `vm.` / `vt.`) | `Videos\TikToks` |
| `youtube.com/shorts/...` | `Videos\YT Shorts` |
| `youtube.com/watch?v=...` or `youtu.be/...` | `Videos\YT Videos` |
| anything else | `Videos\Other` |

Named `Creator - Title [id].mp4` — the id keeps two videos with the same title
from overwriting each other.

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

The extension asks for four permissions and no host permissions, so it cannot
read the pages you visit. It never touches your cookies or your accounts, which
also means it can only reach videos you could see while logged out.

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

```powershell
cd native-host

# 1. freeze host.py + download.py + yt-dlp into host.exe
..\.venv\Scripts\python.exe -m PyInstaller --name host --onedir --console `
    --noconfirm --paths .. --hidden-import download `
    --collect-submodules yt_dlp host.py

# 2. assemble the zip
..\.venv\Scripts\python.exe make-release.py
```

`--onedir`, not `--onefile`: a one-file exe unpacks itself on **every** run, which
adds seconds to every single click.

`make-release.py` refuses to build if the private key, a machine-specific host
manifest, or a log file would end up in the archive.

**Rebuild after editing `download.py` or `host.py`** — the exe is a frozen
snapshot. `install.ps1` prefers `host.exe` and falls back to `host.bat` (which
runs live source from the venv), so deleting `dist\` switches you back to
developing against source.

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
