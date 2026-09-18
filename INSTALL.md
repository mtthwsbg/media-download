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

Chrome will ask about **reading cookies** for the sites it supports. That
permission is what lets it download posts that need you to be logged in. The
cookies go to the helper on your own machine for the length of one download and
are deleted afterwards; nothing is sent anywhere. Decline it if you only ever
download public videos — everything else still works.

**Nothing of your login is used until you say so.** Every download is first
tried signed-out. If one fails because it genuinely needed an account, the panel
offers a **Use my <site> login** button; press it and only then is your existing
browser session used, for that site, remembered until you remove it from the
list at the bottom of the panel.

Done.

---

## Using it

Click the toolbar icon to open the panel.

- **Download what's on screen** — the button at the top. It works on a post's
  own page and in a feed: it reads the page to see which post you're actually
  looking at.
- **If it can't tell**, it says so rather than guessing. Right-click the post
  and choose **Download this** — that always works, on any site.
- **Queue as many as you like.** Each one is added and the panel returns
  straight away; they run one at a time, in order.
- **The panel lists everything** that is downloading, with a progress bar and a
  percentage, and everything recently finished.
- **To stop one**, press the **✕** on its row. To stop everything, right-click
  the toolbar icon and choose **Stop everything**. Either takes effect
  immediately.

The badge on the icon counts what is left, so you can tell work is happening
without opening the panel.

### The folder Claude can read

A video is saved as just the video file. A **picture post** has no single file
to open, so it becomes a folder holding `post.md` (the caption, who posted it,
when), the pictures shrunk down, and — if the post also had a clip — a few
stills and a transcript, when a Groq key is set up. That folder is meant to be
handed to an AI: it costs roughly half what the same post would as a PDF. The
README explains why.

## Where the files go

Everything goes under **one** folder in your own `Videos`, so it is obvious what
put it there and you can move or delete the lot in one go. Inside it, files are
sorted by the site they came from and then by what kind of thing they are.
`install.ps1` creates the whole tree, so you can see where things will land
before you download anything. Paths in the table are relative to it.

```
Videos\Chrome Downloader Ext\
  Instagram\   Reels    Posts   Stories
  YouTube\     Videos   Shorts
  TikTok\      Videos   Photos
  Reddit\      Videos   Posts
  Facebook\    Reels    Videos  Posts
  X\           Videos   Posts
  ...and Snapchat, Bluesky, Twitch, Vimeo, Dailymotion, Streamable,
     Rumble, Kick, Bilibili, VK, Weibo, LinkedIn, 9GAG, Newgrounds,
     Pinterest, Imgur, Flickr, DeviantArt, ArtStation, Pixiv, Tumblr,
     Tenor, SoundCloud, Bandcamp
  Other\      any site not in the list - it still downloads
```

| Link | Lands in |
|---|---|
| `instagram.com/reel/...` | `Instagram\Reels` |
| `instagram.com/p/...` | `Instagram\Posts` |
| `youtube.com/shorts/...` | `YouTube\Shorts` |
| `youtube.com/watch?v=...` or `youtu.be/...` | `YouTube\Videos` |
| `tiktok.com/@user/video/...` | `TikTok\Videos` |
| `reddit.com/r/.../comments/...` | `Reddit\...` |
| `facebook.com/reel/...` | `Facebook\Reels` |
| `x.com/user/status/...` | `X\...` |
| anything else | `Other` |

Named `Creator - Title [id].mp4`. Downloads are capped at 1080p — 4K is about
ten times the size for something you'll watch on a laptop.

### One click gets one thing

A profile, a playlist, a subreddit or your feed is a link to *many* posts, and
downloading all of them is not what the button is for. Those links are refused
with a note telling you to open the post itself, or right-click it and choose
**Download this**. A `&list=` picked up from an open playlist is stripped, so
you get the one video you were watching.

---

## If something goes wrong

**Every attempt is logged.** Open `host\host.log` in the folder — it records
each link and the exact reason anything failed. Check it first.

**"Specified native messaging host not found"**
Step 4 didn't run, or the folder moved since it did. Re-run `install.ps1`.

**Downloads fail with an ffmpeg error**
ffmpeg isn't installed or isn't on PATH. Step 1, then open a new terminal.

**"Needs your <site> login"**
The post isn't public. Press the **Use my <site> login** button on that row in
the panel and it will retry using the session already in your browser. Make
sure you are actually signed in to that site in Chrome first.

**"<site> is busy right now"**
The site is rate-limiting - refusing requests for a while. Reddit does this
readily. Wait a minute and try again; if it keeps happening, giving that site
your login usually settles it.

**"Couldn't tell which post is on screen"**
On a feed the button reads the page to work out which post you're looking at.
If the post hasn't finished loading, or the site changed its layout, it says
this instead of guessing and downloading the wrong video. Right-click the post
and choose **Download this** — that always works.

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
