// background.js - the whole extension.
//
// Chrome is not allowed to start a program on your computer by itself, so this
// opens a "native messaging" pipe to native-host/host.bat, which runs
// download.py. Chrome starts that program when the pipe opens and kills it when
// the pipe closes, so nothing is left running between downloads.

const HOST = "com.mediadownload.host";

// If the helper goes this long without a word, assume it has hung and let go.
// Every chunk of a download sends a progress message, so a real download resets
// this constantly - only a genuinely wedged one runs it out.
const SILENCE_LIMIT_MS = 90000;

// The download running right now, or null. Holding the session object (not a
// boolean) is what lets a second click reach into it and cancel it.
let active = null;

// ---------------------------------------------------------------
//  The two ways to start a download
// ---------------------------------------------------------------

chrome.runtime.onInstalled.addListener(() => {
  // removeAll first, otherwise reloading the extension throws "duplicate id".
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "download-video",
      title: "Download this video",
      contexts: ["link", "video"]
    });
  });
});

// Toolbar button: whatever page the tab is on.
chrome.action.onClicked.addListener((tab) => {
  start(tab && tab.url);
});

// Right-click: the link itself. This is the one that works in a feed, where the
// tab's URL is the feed and not the Reel you actually want.
chrome.contextMenus.onClicked.addListener((info) => {
  start(info.linkUrl || info.srcUrl || info.pageUrl);
});

// ---------------------------------------------------------------
//  Feedback: a badge on the icon, and a notification at the end
// ---------------------------------------------------------------

function badge(text, color) {
  chrome.action.setBadgeText({ text: text });
  if (color) {
    chrome.action.setBadgeBackgroundColor({ color: color });
  }
}

function clearBadgeSoon() {
  setTimeout(() => {
    if (!active) badge("");
  }, 4000);
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon48.png",
    title: title,
    message: String(message).slice(0, 300)
  });
}

function fail(message) {
  badge("✗", "#c0392b");
  notify("Couldn't download that", message);
  clearBadgeSoon();
}

// ---------------------------------------------------------------
//  Starting, finishing, and cancelling
// ---------------------------------------------------------------

function start(url) {
  // A second click while something is running means "stop it", not "queue it".
  if (active) {
    cancel();
    return;
  }

  if (!url || !/^https?:/i.test(url)) {
    fail("That isn't a downloadable link.");
    return;
  }

  let port;
  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (err) {
    fail("Can't reach the downloader. Has install.ps1 been run?");
    return;
  }

  const session = { port: port, url: url, done: false, watchdog: null };
  active = session;
  badge("…", "#3b7ddd");

  // Finish exactly once, from wherever the end comes from: a result, a
  // cancellation, the helper dying, or the watchdog. Everything that can end a
  // download goes through here, so the "running" state can't be left set.
  function settle(handler) {
    if (session.done) return;
    session.done = true;
    clearTimeout(session.watchdog);
    if (active === session) active = null;
    try {
      port.disconnect();
    } catch (err) {
      // Already gone. Nothing to do.
    }
    handler();
  }

  session.settle = settle;

  function resetWatchdog() {
    clearTimeout(session.watchdog);
    session.watchdog = setTimeout(() => {
      settle(() => fail("The download stopped responding, so it was dropped."));
    }, SILENCE_LIMIT_MS);
  }

  resetWatchdog();

  port.onMessage.addListener((msg) => {
    if (session.done) return;
    resetWatchdog();

    if (msg.status === "progress") {
      badge(msg.percent + "%", "#3b7ddd");
      return;
    }
    if (msg.status === "done") {
      settle(() => {
        badge("✓", "#2e9e4f");
        notify("Saved", msg.name || msg.path || "Done");
        clearBadgeSoon();
      });
      return;
    }
    if (msg.status === "error") {
      settle(() => fail(msg.message || "The download failed."));
    }
  });

  // Only fires when the far end hangs up - not when we disconnect. That
  // asymmetry is why finishing must never be handled here alone.
  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError;
    settle(() =>
      fail(err ? err.message : "The downloader stopped unexpectedly.")
    );
  });

  port.postMessage({ url: url });
}

function cancel() {
  const session = active;
  if (!session) return;
  // Closing the pipe makes Chrome kill the helper process, which stops yt-dlp.
  session.settle(() => {
    badge("×", "#7f8c8d");
    notify("Cancelled", "Download stopped. Click again to start over.");
    clearBadgeSoon();
  });
}
