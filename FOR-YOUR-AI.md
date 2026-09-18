# Hand this to your AI assistant

If a terminal makes you nervous, you don't have to do this alone.

Open Claude — the desktop app, Claude Code, ChatGPT, whatever you use — and say:

> I'm installing a Chrome extension called Media Downloader. The folder is at
> `<paste the path to the unzipped folder>`. Read `FOR-YOUR-AI.md` in it and
> walk me through the install one step at a time.

Everything below is written for the assistant. You can stop reading here.

---

## Instructions for the assistant

You are helping someone install a Chrome extension plus a small Windows helper
program. They may not be technical. Work through the steps in order, one at a
time, and confirm each one worked before moving to the next.

### The one thing that matters most

**You can run terminal commands. You cannot click inside Chrome.**

Chrome's settings pages (`chrome://extensions`) are not reachable from a
terminal, from a script, or by any tool you have. Steps 3 and 5 must be done by
the person, with their mouse. Do not claim to have done them. Do not offer to do
them. Give clear instructions, then **wait** for the person to say they're done.

Steps 1 and 4 are terminal commands — run those yourself if you have a shell,
and read the output back to the person in plain language.

### Before you start

Confirm all three, and stop if any fails:

- **Windows.** This build is Windows-only. There is no Mac or Linux version.
- **Chrome, Edge or Brave.** Edge and Brave need a one-line edit in step 4.
- **The folder is unzipped and in its final home.** Chrome gets pointed at this
  exact path in step 4. If it moves afterwards, step 4 must be re-run. Somewhere
  like `C:\Tools\video-downloader` is good; **Downloads is not** — people clear
  it out.

Check what you're working with:

```powershell
Test-Path "<folder>\install.ps1", "<folder>\extension\manifest.json", "<folder>\host\host.exe"
```

Three `True`s means the folder is intact. Any `False` means the unzip didn't
finish or they're pointing you at the wrong directory — sort that out first.

---

### Step 1 — ffmpeg

Check first, because it may already be there:

```powershell
ffmpeg -version
```

If that prints a version, skip to step 2. Otherwise:

```powershell
winget install --id Gyan.FFmpeg -e
```

**Then open a new terminal.** A shell started before the install doesn't know
ffmpeg exists — its PATH was captured at launch. If you're running commands
through a tool, your next command must be in a fresh session, or `ffmpeg
-version` will keep failing and you'll debug a problem that isn't there.

Why it's needed: sites hand over video and audio as separate streams and ffmpeg
joins them. Without it most downloads fail.

### Step 2 — confirm the folder's final location

Ask the person to confirm the folder is where they want it to live permanently.
This takes ten seconds now and saves re-running step 4 later.

### Step 3 — the person loads the extension (you cannot do this)

Give them exactly this, and wait:

1. Open a new tab and go to `chrome://extensions`
2. Turn on **Developer mode** — the switch in the top-right corner
3. Click **Load unpacked** — a button that appears on the top-left once
   Developer mode is on
4. Select the **`extension`** folder inside the unzipped folder — go *into* the
   main folder and pick `extension`, don't pick the main folder itself
5. A card appears saying **Media Downloader**

Two things they will see and should not worry about:

- Chrome warns about developer-mode extensions. That means "this didn't come
  from the Web Store", not "this is dangerous".
- The card may show **errors** until step 4 is done. That's expected — the
  extension is looking for a helper that isn't connected yet.

Ask them to tell you the ID shown on the card. It should be
`kkfepfljdgflemilngnbpkdadanpaleb`. If it differs, the extension folder is
missing its `manifest.json` key, the zip is damaged, and step 4 will not work —
they need a fresh copy of the zip.

### Step 4 — connect the extension to the helper

```powershell
powershell -ExecutionPolicy Bypass -File "<folder>\install.ps1"
```

Reassure them about the scary-looking part, because they will ask:
`-ExecutionPolicy Bypass` applies to that single command only. It changes no
Windows setting, needs no admin rights, and leaves nothing behind.

What it actually does: writes one registry value under their own user account
saying "this extension is allowed to talk to this program". That's what native
messaging is. Nothing is installed system-wide and nothing runs in the
background — Chrome starts the helper when they click download and closes it
when the download finishes.

Success looks like `Installed.` plus a line reading `ffmpeg : found`. If ffmpeg
says missing, go back to step 1 — and remember the fresh-terminal point.

**On Edge or Brave**, one line in `install.ps1` must change before running it:

```powershell
$key = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
```

`Google\Chrome` becomes `Microsoft\Edge` or `BraveSoftware\Brave-Browser`.

Verify it landed:

```powershell
Get-ItemProperty "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.mediadownload.host"
```

That should print a path ending in `com.mediadownload.host.json`. An error here
means the script didn't complete — read its output again rather than moving on.

### Step 5 — the person reloads and pins (you cannot do this either)

1. Back on `chrome://extensions`, click **Reload** on the Media Downloader card
   — the circular arrow. The errors from step 3 should clear.
2. Click the puzzle-piece icon in Chrome's toolbar, find **Media Downloader**,
   click the pin so it stays visible.

Chrome may ask about **reading cookies** for the sites it supports. Explain it
honestly, because it sounds worse than it is: that permission is what lets it
download posts that require being logged in. The cookies go to the helper on
their own machine for the length of one download and are deleted afterwards;
nothing is sent anywhere. If they only download public videos, they can decline
and everything else still works.

### Step 6 — prove it works

Have them open a normal YouTube video and click the pinned blue arrow, then
**Download what's on screen**.

Then check the result yourself rather than taking "I think it worked" for an
answer:

```powershell
Get-ChildItem "$env:USERPROFILE\Videos\Chrome Downloader Ext" -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 3 FullName, Length
```

A file with a non-zero length, under today's date, means it works.

---

## How it saves things

One folder in their `Videos`, a folder per day inside it, and the site and kind
inside that:

```
Videos\Chrome Downloader Ext\2026-09-18\YouTube\Shorts\Creator - Title [id].mp4
```

The per-day split is the point: you can open today's folder and see everything
you pulled down today.

A video saves as a single `.mp4`. A **picture post** becomes a folder instead,
holding `post.md` with the caption and author, the pictures, and — if the post
had a clip — some stills and a transcript. That folder is built to be handed to
an AI to read.

## When something fails

**Read the log before guessing.** Every attempt is recorded with the exact
reason it failed:

```powershell
Get-Content "<folder>\host\host.log" -Tail 20
```

Do this first, every time. The panel shows a short sentence; the log shows the
cause.

| What they see | What it means |
|---|---|
| `Specified native messaging host not found` | Step 4 never ran, or the folder moved since. Re-run step 4. |
| An ffmpeg error | Step 1, then a **new** terminal. |
| `Needs your <site> login` | Not a bug. The post is private or the site wants an account. There's a **Use my <site> login** button on that row — press it and it retries using the browser session they already have. They must actually be signed in to that site in Chrome. |
| `<site> is busy right now` | Rate-limited. Wait a minute. Reddit does this readily. |
| `Couldn't tell which post is on screen` | It won't guess and download the wrong thing. Right-click the post and choose **Download this**. |
| `That link is a profile, feed or playlist` | Working as intended — one click gets one post, not someone's whole account. Open the post itself. |
| Nothing happens at all | `chrome://extensions` → click the extension's **service worker** link → Console tab. That's a step they have to do; ask them to paste what's there. |
| It broke on a site that used to work | Sites change and the downloader inside this build is frozen at the version it shipped with. They need a newer zip from whoever gave them this one. |

## Things not to do

- **Don't tell them you've loaded the extension or clicked anything in Chrome.**
  You can't. Saying otherwise sends them looking for a button that was never
  pressed.
- **Don't suggest changing the PowerShell execution policy** with
  `Set-ExecutionPolicy`. The `-ExecutionPolicy Bypass` flag on the one command
  is deliberate and sufficient; changing the machine-wide policy is a real
  security change and is not needed here.
- **Don't offer to rebuild the helper from source** unless they're a developer
  and ask. The zip contains a working `host.exe`; they don't need Python.
- **Don't move the folder** to "somewhere tidier" after step 4 without re-running
  step 4.

## What it will not do

Worth saying plainly if they ask, rather than letting them think it's broken:

- **Threads** isn't supported. Neither downloader underneath has an extractor
  for it — an honest gap rather than a menu entry that always fails.
- **Whole profiles, playlists and feeds** are refused by design.
- **Downloads are capped at 1080p.** 4K is roughly ten times the size for
  something watched on a laptop.
