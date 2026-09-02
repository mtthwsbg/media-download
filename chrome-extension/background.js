// background.js - the whole extension.
//
// Chrome is not allowed to start a program on your computer by itself, so this
// opens a "native messaging" pipe to native-host/host.bat, which runs the
// downloader. Chrome starts that program when the pipe opens and kills it when
// the pipe closes, so nothing is left running between batches.
//
// The pipe stays open for a whole batch, not for one download. Click the button
// on one tab, switch to the next, click again - links pile up and the helper
// works through them one at a time. The badge counts what's left.

const HOST = "com.mediadownload.host";

// If the helper goes this long without a word, assume it has hung and let go.
// It sends a tick every 20 seconds even when it has nothing to report, so a
// real download resets this constantly - only a genuinely wedged one runs out.
const SILENCE_LIMIT_MS = 90000;

// The open pipe, or null when nothing is in flight.
let port = null;

// Everything sent to the helper that hasn't come back yet: id -> {url, percent, stage}.
const outstanding = new Map();

let nextId = 1;
let watchdog = null;

// Sites where being logged in is the difference between working and not.
const COOKIE_SITES = [
  "instagram.com", "facebook.com", "youtube.com",
  "tiktok.com", "x.com", "twitter.com", "reddit.com"
];

// ---------------------------------------------------------------
//  The ways to start a download
// ---------------------------------------------------------------

chrome.runtime.onInstalled.addListener(buildMenus);
chrome.runtime.onStartup.addListener(buildMenus);

function buildMenus() {
  // removeAll first, otherwise reloading the extension throws "duplicate id".
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "download-video",
      title: "Download this",
      contexts: ["link", "video", "image"]
    });
    // Right-clicking the toolbar icon is where cancelling lives now. Left-click
    // always means "add to the queue" - with eight tabs to get through, a click
    // that sometimes cancels is a click you can't make quickly.
    chrome.contextMenus.create({
      id: "cancel-current",
      title: "Cancel current download",
      contexts: ["action"]
    });
    chrome.contextMenus.create({
      id: "clear-queue",
      title: "Clear the whole queue",
      contexts: ["action"]
    });
  });
}

chrome.action.onClicked.addListener((tab) => {
  enqueue(tab && tab.url);
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "cancel-current") {
    speak({ cmd: "cancel" });
    return;
  }
  if (info.menuItemId === "clear-queue") {
    const dropped = outstanding.size;
    speak({ cmd: "clear" });
    outstanding.clear();
    render();
    notify("Queue cleared", dropped + " download" + (dropped === 1 ? "" : "s") + " dropped.");
    return;
  }
  // The link itself. This is the one that works in a feed, where the tab's URL
  // is the feed and not the post you actually want.
  enqueue(info.linkUrl || info.srcUrl || info.pageUrl);
});

// ---------------------------------------------------------------
//  Feedback: a badge that counts, a tooltip that explains
// ---------------------------------------------------------------

function render() {
  const left = outstanding.size;

  if (!left) {
    chrome.action.setBadgeText({ text: "" });
    chrome.action.setTitle({ title: "Download this" });
    return;
  }

  chrome.action.setBadgeText({ text: String(left) });
  chrome.action.setBadgeBackgroundColor({ color: "#3b7ddd" });

  // The badge only has room for a number, so the detail goes in the tooltip.
  const current = outstanding.values().next().value;
  const where = current.stage
    ? current.stage
    : (current.percent >= 0 ? current.percent + "%" : "starting");
  chrome.action.setTitle({
    title: where + " - " + left + " in the queue\nRight-click to cancel."
  });
}

function flash(text, color) {
  chrome.action.setBadgeText({ text: text });
  chrome.action.setBadgeBackgroundColor({ color: color });
  setTimeout(render, 4000);
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon48.png",
    title: title,
    message: String(message).slice(0, 300)
  });
}

// ---------------------------------------------------------------
//  Cookies - what makes Instagram and Facebook work at all
// ---------------------------------------------------------------

function siteOf(url) {
  try {
    const host = new URL(url).hostname;
    return COOKIE_SITES.find((site) => host === site || host.endsWith("." + site)) || null;
  } catch (err) {
    return null;
  }
}

// yt-dlp and gallery-dl both read the old Netscape cookies.txt format:
// domain, include-subdomains, path, secure, expiry, name, value - tab separated.
function asCookieFile(cookies) {
  const lines = ["# Netscape HTTP Cookie File", ""];
  for (const c of cookies) {
    lines.push([
      c.domain,
      c.domain.startsWith(".") ? "TRUE" : "FALSE",
      c.path || "/",
      c.secure ? "TRUE" : "FALSE",
      Math.round(c.expirationDate || 0),
      c.name,
      c.value
    ].join("\t"));
  }
  return lines.join("\n") + "\n";
}

async function cookiesFor(url) {
  const site = siteOf(url);
  if (!site) return null;
  try {
    const jar = await chrome.cookies.getAll({ domain: site });
    return jar.length ? asCookieFile(jar) : null;
  } catch (err) {
    // No permission for that site, or the user declined it. Public posts will
    // still work; private ones won't. Not worth failing the download over.
    return null;
  }
}

// ---------------------------------------------------------------
//  The queue
// ---------------------------------------------------------------

async function enqueue(url) {
  if (!url || !/^https?:/i.test(url)) {
    flash("!", "#c0392b");
    notify("Not a link", "There is nothing downloadable on this tab.");
    return;
  }

  const cookies = await cookiesFor(url);

  if (!open_()) return;

  const id = nextId++;
  outstanding.set(id, { url: url, percent: -1, stage: "" });
  render();

  try {
    port.postMessage({ id: id, url: url, cookies: cookies });
  } catch (err) {
    outstanding.delete(id);
    render();
    notify("Couldn't download that", "Lost the connection to the downloader.");
    return;
  }

  if (outstanding.size > 1) {
    flash(String(outstanding.size), "#3b7ddd");
  }
}

function open_() {
  if (port) return true;

  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (err) {
    port = null;
    notify("Couldn't download that", "Can't reach the downloader. Has install.ps1 been run?");
    return false;
  }

  port.onMessage.addListener(onMessage);
  port.onDisconnect.addListener(onDisconnect);
  resetWatchdog();
  return true;
}

function speak(message) {
  if (!port) return;
  try {
    port.postMessage(message);
  } catch (err) {
    // Pipe already gone; onDisconnect will tidy up.
  }
}

function close_() {
  if (!port) return;
  const going = port;
  port = null;
  try {
    going.disconnect();
  } catch (err) {
    // Already gone. Nothing to do.
  }
  clearTimeout(watchdog);
}

function resetWatchdog() {
  clearTimeout(watchdog);
  watchdog = setTimeout(() => {
    const stuck = outstanding.size;
    outstanding.clear();
    close_();
    render();
    if (stuck) {
      notify("Download stopped responding", stuck + " item(s) were dropped.");
    }
  }, SILENCE_LIMIT_MS);
}

function finish(id) {
  outstanding.delete(id);
  render();
  // Nothing left to do means nothing should be running: closing the pipe is
  // what makes Chrome kill the helper process.
  if (outstanding.size === 0) close_();
}

function onMessage(msg) {
  resetWatchdog();

  // A heartbeat. Its only job is to have arrived.
  if (msg.status === "tick") return;

  const item = outstanding.get(msg.id);

  if (msg.status === "progress") {
    if (item) {
      item.percent = msg.percent;
      item.stage = "";
      render();
    }
    return;
  }

  if (msg.status === "stage") {
    if (item) {
      item.stage = msg.stage;
      render();
    }
    return;
  }

  if (msg.status === "done") {
    finish(msg.id);
    const where = msg.kind === "post" ? "Saved as a folder" : "Saved";
    notify(where, msg.name || msg.path || "Done");
    if (outstanding.size === 0) flash("✓", "#2e9e4f");
    return;
  }

  if (msg.status === "cancelled") {
    finish(msg.id);
    flash("×", "#7f8c8d");
    return;
  }

  if (msg.status === "error") {
    finish(msg.id);
    notify("Couldn't download that", msg.message || "The download failed.");
    if (outstanding.size === 0) flash("✗", "#c0392b");
  }
}

// Only fires when the far end hangs up - not when we disconnect.
function onDisconnect() {
  const err = chrome.runtime.lastError;
  const lost = outstanding.size;
  outstanding.clear();
  port = null;
  clearTimeout(watchdog);
  render();
  if (lost) {
    notify(
      "The downloader stopped",
      (err ? err.message : "It closed unexpectedly.") +
        " " + lost + " item(s) were lost."
    );
  }
}
