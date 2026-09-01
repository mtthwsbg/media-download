# Video Downloader — install guide

A Chrome button that saves the video you're looking at as an `.mp4`, sorted into
folders under your `Videos` directory.

**If you're reading this to help someone install it: everything you need is
below. It's five steps and takes about three minutes. Nothing here needs admin
rights, and nothing runs in the background.**

---

## What this is

Two pieces that talk to each other:

- **A Chrome extension** — the button. Chrome extensions are sandboxed and
  cannot run programs on your computer, so the button alone can't download.
- **A helper program** (`host/host.exe`) — does the actual downloading, using
  [yt-dlp](https://github.com/yt-dlp/yt-dlp). It's a normal Windows program.

They're connected by **native messaging**: `install.ps1` writes one registry
value under your own user account saying "this extension may talk to this
program". Chrome starts the helper when you click, and kills it when the
download finishes. Nothing is running in between.

## Before you start

| Need | Notes |
|---|---|
| **Windows** | This build is Windows-only. |
| **Google Chrome** | Or Edge/Brave, with a change noted at the bottom. |
| **ffmpeg** | See step 1. Videos arrive as separate video and audio streams and ffmpeg joins them. Without it most downloads fail. |

You do **not** need Python — it's built into `host.exe`.

---

## Step 1 — install ffmpeg

Open PowerShell and run:

```powershell
winget install --id Gyan.FFmpeg -e
```

Then **close that window**. A terminal opened before ffmpeg was installed
doesn't know it exists yet.

Already have ffmpeg? `ffmpeg -version` will tell you. Skip this step if it works.

## Step 2 — put the folder somewhere permanent

Unzip it wherever you like — `C:\Tools\video-downloader` or your Documents
folder are both fine.

**It has to stay there.** Chrome will be pointed at this exact path. If you move
it later, just re-run step 4.

## Step 3 — load the extension

1. Open `chrome://extensions`
2. Turn on **Developer mode** — the switch in the top right
3. Click **Load unpacked**
4. Select the **`extension`** folder from inside the unzipped folder

Chrome will warn you about developer-mode extensions. That's expected: it means
"this didn't come from the Web Store", not "this is dangerous".

## Step 4 — connect it to the helper

In PowerShell, in the unzipped folder:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

`-ExecutionPolicy Bypass` applies to that one command only. It changes no
Windows setting and needs no admin rights.

You should see `Installed.` and a line reading `ffmpeg : found`. If ffmpeg isn't
found, go back to step 1.

## Step 5 — reload and pin

Back on `chrome://extensions`, click **Reload** on the extension's card. Then
click the puzzle-piece icon in Chrome's toolbar and pin the blue arrow.

Done.

---

## Using it

- **On a video's own page** (a YouTube watch page, a Short, a Reel you've
  opened) — click the blue arrow in the toolbar.
- **In a feed**, where the page isn't the video — right-click the video or its
  link and choose **Download this video**.
- **Click again while it's downloading to cancel.** What's downloaded so far is
  kept, so starting the same video again resumes instead of restarting.

The icon shows `…`, then a percentage, then a green `✓`. A notification gives
you the filename.

## Where the files go

Under your own `Videos` folder, sorted by where the link came from:

| Link | Lands in |
|---|---|
| `instagram.com/...` | `Videos\IG Reels` |
| `tiktok.com/...` | `Videos\TikToks` |
| `youtube.com/shorts/...` | `Videos\YT Shorts` |
| `youtube.com/watch?v=...` or `youtu.be/...` | `Videos\YT Videos` |
| anything else | `Videos\Other` |

Named `Creator - Title [id].mp4`. Downloads are capped at 1080p — 4K is about
ten times the size for something you'll watch on a laptop.

---

## If something goes wrong

**Every attempt is logged.** Open `host\host.log` in the folder — it records
each link and the exact reason anything failed. Check it first.

**"Specified native messaging host not found"**
Step 4 didn't run, or the folder moved since it did. Re-run `install.ps1`.

**Downloads fail with an ffmpeg error**
ffmpeg isn't installed or isn't on PATH. Step 1, then open a new terminal.

**"This video is unavailable" / "login required"**
The video isn't publicly viewable. This tool only reaches things you could see
while logged out — it deliberately doesn't touch your cookies or your accounts.

**It stopped working on a site that used to work**
Instagram and YouTube change constantly and yt-dlp gets patched to keep up. This
build's yt-dlp is frozen at the version it shipped with, so ask whoever gave you
the zip for a fresh build.

**Nothing happens at all**
Go to `chrome://extensions`, click the extension's **service worker** link, and
look at the Console tab for an error.

## Using Edge or Brave instead of Chrome

Both work. Change one thing in `install.ps1`: the line

```powershell
$key = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
```

becomes `Microsoft\Edge` or `BraveSoftware\Brave-Browser` in place of
`Google\Chrome`.

## Removing it

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

Then click **Remove** on the extension's card, and delete the folder.

---

## A note on what you download

Saving videos for your own reference is one thing; re-uploading someone else's
video as your own is a different one. Also worth knowing that YouTube's terms of
service don't permit downloading — which is exactly why this isn't on the Chrome
Web Store and is being passed around as a folder instead.
