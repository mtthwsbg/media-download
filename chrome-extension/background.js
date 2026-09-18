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

// Every item the panel knows about, newest last. One list rather than two,
// because the panel shows running and finished rows together and the only
// difference between them is `status`.
//
//   {id, url, site, who, status, percent, stage, kind, message, path}
//   status: "queued" | "running" | "done" | "error" | "cancelled"
let items = [];

let nextId = 1;
let watchdog = null;

// Finished rows are worth keeping so you can click through to the file, but
// not forever.
const KEEP_FINISHED = 25;

const RUNNING = new Set(["queued", "running"]);

function active() {
  return items.filter((item) => RUNNING.has(item.status));
}

function byId(id) {
  return items.find((item) => item.id === id) || null;
}

// The service worker is shut down whenever Chrome feels like it, and the popup
// is a separate page that starts fresh every time it opens. Without mirroring
// the list somewhere durable, opening the panel mid-download would show
// nothing at all.
async function save() {
  try {
    await chrome.storage.session.set({ items: items, nextId: nextId });
  } catch (err) {
    // storage.session can be unavailable very early in startup. The list is
    // still correct in memory; it just won't survive a worker restart.
  }
}

async function load() {
  try {
    const stored = await chrome.storage.session.get(["items", "nextId"]);
    if (Array.isArray(stored.items)) items = stored.items;
    if (typeof stored.nextId === "number") nextId = stored.nextId;
  } catch (err) {
    // Nothing stored yet.
  }
}

const ready = load();

// Tell an open panel that something changed. It throws when no panel is open,
// which is the normal case and not worth reporting.
function announce() {
  chrome.runtime.sendMessage({ type: "changed" }).catch(() => {});
}

async function touch() {
  render();
  await save();
  announce();
}

// ---------------------------------------------------------------
//  Using your login - only ever after you say so
// ---------------------------------------------------------------
//
// Nothing is sent on a first attempt, for any site. If a download fails
// because it needs an account, the panel asks - once - and remembers the
// answer for that site only. The word "cookies" never reaches the user: what
// this actually is, to the person clicking, is their login.
const LOGIN_KEY = "sitesAllowedToUseMyLogin";

async function allowedSites() {
  try {
    const stored = await chrome.storage.local.get(LOGIN_KEY);
    return Array.isArray(stored[LOGIN_KEY]) ? stored[LOGIN_KEY] : [];
  } catch (err) {
    return [];
  }
}

async function allowSite(site) {
  const allowed = await allowedSites();
  if (site && !allowed.includes(site)) {
    allowed.push(site);
    await chrome.storage.local.set({ [LOGIN_KEY]: allowed });
  }
}

async function forgetSite(site) {
  const allowed = await allowedSites();
  await chrome.storage.local.set({
    [LOGIN_KEY]: allowed.filter((name) => name !== site)
  });
}

// ---------------------------------------------------------------
//  Working out WHICH post you meant
// ---------------------------------------------------------------

// What a link to ONE post looks like on each site. This is the mirror of
// SINGLE_ITEM in download.py - change one, change the other.
const SINGLE_ITEM = {
  "instagram.com":  ["/p/", "/reel/", "/reels/", "/tv/", "/stories/"],
  "youtube.com":    ["/watch", "/shorts/", "/live/", "/embed/", "/clip/"],
  "tiktok.com":     ["/video/", "/photo/"],
  "reddit.com":     ["/comments/", "/s/"],
  "facebook.com":   ["/reel/", "/videos/", "/video.php", "/watch", "/photo",
                     "/posts/", "/permalink", "/story.php", "/share/"],
  "x.com":          ["/status/"],
  "twitter.com":    ["/status/"],
  "snapchat.com":   ["/spotlight/", "/p/"],
  "bsky.app":       ["/post/"],
  "twitch.tv":      ["/clip/", "/clips/", "/videos/"],
  "pinterest.com":  ["/pin/"],
  "tumblr.com":     ["/post/", "/image/"],
  "deviantart.com": ["/art/"],
  "artstation.com": ["/artwork/"],
  "pixiv.net":      ["/artworks/"],
  "newgrounds.com": ["/portal/view/", "/art/view/", "/audio/listen/"],
  "9gag.com":       ["/gag/"]
};

function markersFor(url) {
  try {
    const host = new URL(url).hostname;
    for (const site of Object.keys(SINGLE_ITEM)) {
      if (host === site || host.endsWith("." + site)) return SINGLE_ITEM[site];
    }
  } catch (err) {
    // Not a URL we can read; the caller falls back to the tab's own address.
  }
  return null;
}

// The repeating unit of a feed - one post's card. Whichever of these is
// filling the screen is the post you meant. Verified against live TikTok and
// YouTube feeds: TikTok cards are
// article[data-e2e="recommend-list-item-container"], YouTube's are
// ytd-rich-item-renderer.
const POST_CARDS = [
  "article",
  '[data-e2e="recommend-list-item-container"]',
  "ytd-rich-item-renderer",
  "ytd-video-renderer",
  "ytd-reel-video-renderer",
  "shreddit-post",
  '[role="article"]',
  "section"
].join(", ");

// Runs INSIDE the page, so it can see what the address bar can't.
//
// TikTok, Instagram and YouTube are single-page apps: the address bar stays on
// the feed while you scroll through posts. Clicking the toolbar button on a
// TikTok feed used to send "tiktok.com/en/", which is a feed and not a video -
// which is exactly what the downloader refused, and exactly why TikTok never
// worked. So instead of trusting the URL, look at what is on the screen.
//
// This function is stringified and injected, so it can't call anything outside
// itself - everything it needs is defined inside.
function findPostOnScreen(markers, cardSelector) {
  const looksLikeAPost = (path) =>
    markers.some((marker) => path.toLowerCase().includes(marker));

  // Already on a post's own page - an opened Reel, a Short, a watch page.
  // Nothing to work out, and nothing to get wrong.
  if (looksLikeAPost(location.pathname)) return location.href;

  // How much of an element is on screen right now. The post you mean is the
  // one filling the window; the others are half-scrolled neighbours.
  const visibleArea = (element) => {
    const box = element.getBoundingClientRect();
    const width = Math.min(box.right, innerWidth) - Math.max(box.left, 0);
    const height = Math.min(box.bottom, innerHeight) - Math.max(box.top, 0);
    return width > 0 && height > 0 ? width * height : 0;
  };

  const cards = Array.from(document.querySelectorAll(cardSelector))
    .map((element) => ({ element: element, area: visibleArea(element) }))
    .filter((card) => card.area > 10000)
    .sort((a, b) => b.area - a.area);

  // Most sites put a link to the post inside the post's own card. Searching
  // the card and not the page is the point: the page is full of links to other
  // posts, and picking one of those downloads the wrong video.
  for (const card of cards) {
    for (const anchor of card.element.querySelectorAll("a[href]")) {
      try {
        const found = new URL(anchor.getAttribute("href"), location.origin);
        if (found.hostname === location.hostname && looksLikeAPost(found.pathname)) {
          return found.href;
        }
      } catch (err) {
        // A malformed href. Try the next one.
      }
    }
  }

  // TikTok's feed card carries no link to its own video - the only link in it
  // with a long number is "/music/original-sound-7517...", which is the SOUND
  // and would download the wrong thing. So the id has to come from somewhere
  // else, and the author from the "/@handle" link in the same card. Those two
  // are all a TikTok link is.
  if (location.hostname.endsWith("tiktok.com")) {
    // Where the video's id actually lives, in the order worth trying:
    //
    // 1. The player's element id ("xgwrapper-0-7674..."), which only exists
    //    once that video has started playing - so it is present exactly when
    //    you are watching the thing you want, and absent in a background tab.
    // 2. React's own props for the card. TikTok renders the feed from a list
    //    of items, and the item object is still there whether or not a player
    //    has mounted. This is what makes the button work on a card that hasn't
    //    started playing yet.
    const idFromPlayer = (card) =>
      Array.from(card.querySelectorAll('[id*="xgwrapper"]'))
        .map((element) => (element.id.match(/([0-9]{15,25})/) || [])[1])
        .find(Boolean) || null;

    const idFromReact = (card) => {
      const key = Object.keys(card).find((name) => name.startsWith("__reactFiber$"));
      if (!key) return null;

      // The item object: a long numeric id, alongside the fields that only a
      // post has. Checking for those companions is what stops this matching
      // some unrelated object that happens to carry a long number.
      const isPost = (value) =>
        value && typeof value === "object" && typeof value.id === "string" &&
        /^[0-9]{15,25}$/.test(value.id) &&
        (value.author || value.video || value.desc !== undefined);

      const search = (object, depth) => {
        if (!object || typeof object !== "object" || depth > 2) return null;
        if (isPost(object)) return object.id;
        for (const name of Object.keys(object)) {
          try {
            const hit = search(object[name], depth + 1);
            if (hit) return hit;
          } catch (err) {
            // A getter that throws. Skip it.
          }
        }
        return null;
      };

      // Breadth-first through the card's own fibers, capped so a deep tree
      // can never turn one button click into a long freeze.
      const seen = new Set();
      let queue = [card[key]];
      let visited = 0;
      while (queue.length && visited < 400) {
        const fiber = queue.shift();
        if (!fiber || seen.has(fiber)) continue;
        seen.add(fiber);
        visited++;
        for (const props of [fiber.memoizedProps, fiber.pendingProps]) {
          const hit = search(props, 0);
          if (hit) return hit;
        }
        if (fiber.child) queue.push(fiber.child);
        if (fiber.sibling) queue.push(fiber.sibling);
      }
      return null;
    };

    for (const card of cards) {
      // Length check because the nav bar has a bare "/@" link that would
      // otherwise pass for a username and build "tiktok.com/@/video/...".
      const handle = Array.from(card.element.querySelectorAll('a[href^="/@"]'))
        .map((anchor) => anchor.getAttribute("href").split("/")[1])
        .find((name) => name && name.length > 2);
      if (!handle) continue;

      const id = idFromPlayer(card.element) || idFromReact(card.element);
      if (id) return location.origin + "/" + handle + "/video/" + id;
    }
  }

  return null;
}

// Ask the page which post is on screen. Falls back to the tab's own address,
// which is the right answer on any site that isn't a single-page feed.
async function realUrlFor(tab) {
  const markers = markersFor(tab && tab.url);
  if (!markers || !tab || tab.id == null) return tab ? tab.url : null;

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: findPostOnScreen,
      args: [markers, POST_CARDS]
    });
    const found = results && results[0] && results[0].result;
    return found || null;
  } catch (err) {
    // No permission to run on this page, or it's a page Chrome won't inject
    // into. The tab's URL is still worth a try.
    return tab.url;
  }
}

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
    // Cancelling one download lives in the panel now, a cross per row, which
    // is the only place it can name WHICH one. This stays for the blunt case.
    chrome.contextMenus.create({
      id: "clear-queue",
      title: "Stop everything",
      contexts: ["action"]
    });
  });
}

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "clear-queue") {
    clearQueue();
    return;
  }
  // The link itself. This is the sure way on any site: it hands over exactly
  // the post you pointed at, with nothing to work out.
  enqueue(info.linkUrl || info.srcUrl || info.pageUrl);
});

// ---------------------------------------------------------------
//  What the site is called, and who posted it
// ---------------------------------------------------------------

// The mirror of PLATFORMS in download.py, for display only - which folder a
// file lands in is decided there, not here.
const SITE_NAMES = {
  "instagram.com": "Instagram", "youtube.com": "YouTube", "youtu.be": "YouTube",
  "tiktok.com": "TikTok", "reddit.com": "Reddit", "redd.it": "Reddit",
  "facebook.com": "Facebook", "fb.watch": "Facebook",
  "x.com": "X", "twitter.com": "X", "snapchat.com": "Snapchat",
  "bsky.app": "Bluesky", "twitch.tv": "Twitch", "vimeo.com": "Vimeo",
  "dailymotion.com": "Dailymotion", "streamable.com": "Streamable",
  "rumble.com": "Rumble", "kick.com": "Kick", "bilibili.com": "Bilibili",
  "vk.com": "VK", "weibo.com": "Weibo", "linkedin.com": "LinkedIn",
  "9gag.com": "9GAG", "newgrounds.com": "Newgrounds",
  "pinterest.com": "Pinterest", "pin.it": "Pinterest", "imgur.com": "Imgur",
  "flickr.com": "Flickr", "deviantart.com": "DeviantArt",
  "artstation.com": "ArtStation", "pixiv.net": "Pixiv", "tumblr.com": "Tumblr",
  "tenor.com": "Tenor", "soundcloud.com": "SoundCloud",
  "bandcamp.com": "Bandcamp"
};

function siteOf(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    for (const domain of Object.keys(SITE_NAMES)) {
      if (host === domain || host.endsWith("." + domain)) return domain;
    }
  } catch (err) {
    // Not a URL.
  }
  return null;
}

function siteLabel(url) {
  const domain = siteOf(url);
  if (domain) return SITE_NAMES[domain];
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (err) {
    return "Link";
  }
}

// A first guess at who posted it, taken from the link, so a row says something
// recognisable before the download finishes and the real name arrives.
function whoFrom(url) {
  try {
    const path = new URL(url).pathname;
    const handle = path.match(/\/@([^/]+)/) || path.match(/^\/(?:r|user|u)\/([^/]+)/);
    if (handle) return handle[1];
    const first = path.split("/").filter(Boolean)[0];
    return first && first.length < 24 ? first : "";
  } catch (err) {
    return "";
  }
}

// ---------------------------------------------------------------
//  The badge. The panel is the real display now.
// ---------------------------------------------------------------

function render() {
  const running = active();
  if (!running.length) {
    chrome.action.setBadgeText({ text: "" });
    chrome.action.setTitle({ title: "Download this" });
    return;
  }
  chrome.action.setBadgeText({ text: String(running.length) });
  chrome.action.setBadgeBackgroundColor({ color: "#3b7ddd" });
  const current = running[0];
  const where = current.stage
    ? current.stage
    : (current.percent >= 0 ? current.percent + "%" : "starting");
  chrome.action.setTitle({ title: where + " - " + running.length + " to go" });
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
//  Your login, in the format the downloader reads
// ---------------------------------------------------------------

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

// Never called for a site the user hasn't agreed to. That is the whole
// mechanism: no login leaves Chrome until a failed download proved one was
// needed and the panel asked.
async function loginFor(url) {
  const site = siteOf(url);
  if (!site) return null;
  const allowed = await allowedSites();
  if (!allowed.includes(site)) return null;
  try {
    const jar = await chrome.cookies.getAll({ domain: site });
    return jar.length ? asCookieFile(jar) : null;
  } catch (err) {
    return null;
  }
}

// ---------------------------------------------------------------
//  The queue
// ---------------------------------------------------------------

async function enqueue(url) {
  await ready;

  if (!url || !/^https?:/i.test(url)) {
    notify("Not a link", "There is nothing downloadable on this tab.");
    return null;
  }

  const cookies = await loginFor(url);
  if (!openPipe()) return null;

  const id = nextId++;
  items.push({
    id: id,
    url: url,
    site: siteLabel(url),
    who: whoFrom(url),
    status: "running",
    percent: -1,
    stage: "",
    kind: "",
    message: "",
    path: ""
  });
  trim();

  try {
    port.postMessage({ id: id, url: url, cookies: cookies });
  } catch (err) {
    const item = byId(id);
    if (item) {
      item.status = "error";
      item.kind = "failed";
      item.message = "Lost the connection to the downloader.";
    }
    await touch();
    return null;
  }

  await touch();
  return id;
}

// Finished rows are worth keeping so you can click through to the file, but
// not without limit.
function trim() {
  const done = items.filter((item) => !RUNNING.has(item.status));
  if (done.length > KEEP_FINISHED) {
    const drop = new Set(done.slice(0, done.length - KEEP_FINISHED));
    items = items.filter((item) => !drop.has(item));
  }
}

async function clearQueue() {
  const dropped = active().length;
  speak({ cmd: "clear" });
  for (const item of active()) item.status = "cancelled";
  await touch();
  if (dropped) {
    notify("Queue cleared",
           dropped + " download" + (dropped === 1 ? "" : "s") + " dropped.");
  }
}

async function cancelItem(id) {
  speak({ cmd: "cancel", id: id });
  // The host answers with "cancelled" of its own accord; this only makes the
  // row react the instant it is clicked.
  const item = byId(id);
  if (item && RUNNING.has(item.status)) item.stage = "stopping";
  await touch();
}

function openPipe() {
  if (port) return true;
  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (err) {
    port = null;
    notify("Couldn't download that",
           "Can't reach the downloader. Has install.ps1 been run?");
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

function closePipe() {
  if (!port) return;
  const going = port;
  port = null;
  try {
    going.disconnect();
  } catch (err) {
    // Already gone.
  }
  clearTimeout(watchdog);
}

function resetWatchdog() {
  clearTimeout(watchdog);
  watchdog = setTimeout(async () => {
    for (const item of active()) {
      item.status = "error";
      item.kind = "failed";
      item.message = "The downloader stopped responding.";
    }
    closePipe();
    await touch();
  }, SILENCE_LIMIT_MS);
}

function settle() {
  // Nothing left to do means nothing should be running: closing the pipe is
  // what makes Chrome kill the helper process.
  if (active().length === 0) closePipe();
}

async function onMessage(msg) {
  resetWatchdog();
  if (msg.status === "tick") return;

  const item = byId(msg.id);
  if (!item) return;

  if (msg.status === "progress") {
    item.percent = msg.percent;
    item.stage = "";
  } else if (msg.status === "stage") {
    item.stage = msg.stage;
  } else if (msg.status === "done") {
    item.status = "done";
    item.percent = 100;
    item.stage = "";
    item.path = msg.path || "";
    if (msg.name) item.who = msg.name;
    settle();
  } else if (msg.status === "cancelled") {
    item.status = "cancelled";
    settle();
  } else if (msg.status === "error") {
    item.status = "error";
    item.kind = msg.kind || "failed";
    item.message = msg.message || "The download failed.";
    settle();
  }

  await touch();
}

async function onDisconnect() {
  const err = chrome.runtime.lastError;
  port = null;
  clearTimeout(watchdog);
  for (const item of active()) {
    item.status = "error";
    item.kind = "failed";
    item.message = err ? err.message : "The downloader closed unexpectedly.";
  }
  await touch();
}

// ---------------------------------------------------------------
//  What the panel asks for
// ---------------------------------------------------------------

chrome.runtime.onMessage.addListener((request, sender, respond) => {
  handleRequest(request).then(respond);
  return true;   // keeps the channel open for the async reply
});

async function handleRequest(request) {
  await ready;

  switch (request && request.type) {
    case "getState":
      return { items: items, logins: await allowedSites() };

    case "downloadVisible": {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const url = await realUrlFor(tab);
      if (!url) {
        return {
          error: "Couldn't tell which post is on screen. Right-click the post " +
                 "itself and choose \"Download this\"."
        };
      }
      return { id: await enqueue(url) };
    }

    case "cancelItem":
      await cancelItem(request.id);
      return { ok: true };

    case "clearFinished":
      items = active();
      await touch();
      return { ok: true };

    case "useLogin": {
      // Say yes once for this site, then immediately retry what failed.
      const item = byId(request.id);
      if (!item) return { ok: false };
      const site = siteOf(item.url);
      if (site) await allowSite(site);
      const url = item.url;
      items = items.filter((row) => row.id !== item.id);
      return { ok: true, id: await enqueue(url) };
    }

    case "forgetLogin":
      await forgetSite(request.site);
      announce();
      return { ok: true };

    default:
      return { ok: false };
  }
}
