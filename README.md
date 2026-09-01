# media-download

A Chrome button that saves the video you're looking at as an `.mp4`, sorted into
folders under your `Videos` directory. Instagram Reels, YouTube Shorts, regular
YouTube videos, TikToks.

Click the toolbar icon on a video's page, or right-click a link in a feed. That's
it — no terminal, no pasting URLs.

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
| **On a video's own page** | Click the blue arrow in the toolbar |
| **In a feed** (page isn't the video) | Right-click the video or link → **Download this video** |
| **While it's downloading** | Click again to cancel — progress is kept, so restarting resumes |

The icon shows `…`, then a percentage, then a green `✓`. A notification gives you
the filename.

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
- [ffmpeg](https://ffmpeg.org/) — joins the separate video and audio streams
- Python is **not** required to use it; only to develop it

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
| `download.py` | All the download logic — folder sorting, format selection, ffmpeg discovery |
| `chrome-extension/` | The button. `background.js` is the whole extension |
| `native-host/host.py` | Bridges Chrome's native-messaging protocol to `download.py` |
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
