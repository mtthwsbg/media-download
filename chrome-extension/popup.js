// popup.js - the panel.
//
// It holds no state of its own. Everything is asked for from the background
// worker on open, and again whenever the worker says something changed. The
// popup is destroyed every time it closes, so anything it remembered would be
// wrong the next time it opened.

const RUNNING = new Set(["queued", "running"]);

const grab = document.getElementById("grab");
const hint = document.getElementById("hint");
const runningBlock = document.getElementById("running-block");
const runningTitle = document.getElementById("running-title");
const runningList = document.getElementById("running");
const finishedBlock = document.getElementById("finished-block");
const finishedList = document.getElementById("finished");
const loginsBlock = document.getElementById("logins-block");
const loginsList = document.getElementById("logins");
const empty = document.getElementById("empty");

function ask(message) {
  return chrome.runtime.sendMessage(message).catch(() => null);
}

// --- drawing --------------------------------------------------------------

function nameOf(item) {
  const who = item.who || "";
  const row = document.createElement("span");
  row.className = "who";
  if (item.site) {
    const site = document.createElement("span");
    site.className = "site";
    site.textContent = item.site;
    row.append(site);
  }
  row.append(document.createTextNode(who || "this post"));
  return row;
}

function runningRow(item) {
  const li = document.createElement("li");
  li.className = "row";
  li.append(nameOf(item));

  const stop = document.createElement("button");
  stop.className = "x";
  stop.title = "Stop this one";
  stop.textContent = "✕";
  stop.addEventListener("click", () => ask({ type: "cancelItem", id: item.id }));
  li.append(stop);

  const bar = document.createElement("div");
  bar.className = "bar";

  const track = document.createElement("div");
  track.className = "track";
  const fill = document.createElement("div");
  const known = typeof item.percent === "number" && item.percent >= 0 && !item.stage;
  fill.className = known ? "fill" : "fill waiting";
  if (known) fill.style.width = item.percent + "%";
  track.append(fill);

  const pct = document.createElement("span");
  pct.className = "pct";
  pct.textContent = item.stage ? item.stage : (known ? item.percent + "%" : "starting");

  bar.append(track, pct);
  li.append(bar);
  return li;
}

function finishedRow(item) {
  const li = document.createElement("li");
  li.className = "row";

  const mark = document.createElement("span");
  mark.className = "mark " + (item.status === "done" ? "ok" : "bad");
  mark.textContent = item.status === "done" ? "✓" : "✗";

  const label = nameOf(item);
  label.prepend(mark, document.createTextNode(" "));
  li.append(label, document.createElement("span"));

  if (item.status !== "done" && item.message) {
    const note = document.createElement("p");
    note.className = "note bad";
    note.textContent = item.message;
    li.append(note);
  }

  // The only place a login is ever offered, and only for the one failure that
  // actually needs it.
  if (item.kind === "needs_login") {
    const use = document.createElement("button");
    use.className = "login";
    use.textContent = "Use my " + (item.site || "site") + " login";
    use.addEventListener("click", () => ask({ type: "useLogin", id: item.id }));
    li.append(use);
  }

  return li;
}

function loginRow(site) {
  const li = document.createElement("li");
  li.className = "row";
  li.append(document.createTextNode(site));

  const drop = document.createElement("button");
  drop.className = "x";
  drop.title = "Stop using my login for " + site;
  drop.textContent = "✕";
  drop.addEventListener("click", () => ask({ type: "forgetLogin", site: site }));
  li.append(drop);
  return li;
}

function draw(state) {
  const items = (state && state.items) || [];
  const logins = (state && state.logins) || [];

  const running = items.filter((item) => RUNNING.has(item.status));
  const finished = items.filter((item) => !RUNNING.has(item.status)).reverse();

  runningList.replaceChildren(...running.map(runningRow));
  runningTitle.textContent =
    running.length > 1 ? "Downloading (" + running.length + ")" : "Downloading";
  runningBlock.hidden = running.length === 0;

  finishedList.replaceChildren(...finished.map(finishedRow));
  finishedBlock.hidden = finished.length === 0;

  loginsList.replaceChildren(...logins.map(loginRow));
  loginsBlock.hidden = logins.length === 0;

  empty.hidden = running.length > 0 || finished.length > 0;
}

async function refresh() {
  draw(await ask({ type: "getState" }));
}

// --- what the buttons do --------------------------------------------------

grab.addEventListener("click", async () => {
  hint.hidden = true;
  grab.disabled = true;
  const result = await ask({ type: "downloadVisible" });
  grab.disabled = false;

  if (result && result.error) {
    hint.textContent = result.error;
    hint.hidden = false;
  }
  refresh();
});

document.getElementById("clear").addEventListener("click", async () => {
  await ask({ type: "clearFinished" });
  refresh();
});

// The worker pings whenever anything moves, which is what keeps the
// percentages live while the panel is open.
chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "changed") refresh();
});

refresh();

// --- Reel Digest ----------------------------------------------------------
//
// The old Reel Digest bookmarklet, unchanged, injected into the open saved
// collection. It scrolls to the bottom, gathers every post code and copies
// them. The popup closes right after so the page gets focus back, which the
// clipboard write needs.

const reels = document.getElementById("reels");

chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  if (!tab || !/instagram\.com/.test(tab.url || "")) return;
  reels.hidden = false;
  reels.addEventListener("click", async () => {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: reelDigest });
    window.close();
  });
});

async function reelDigest() {
  if (!/instagram\.com/.test(location.host)) { console.log('Reel Digest: open your saved collection on instagram.com first'); return; }
  document.getElementById('__rd')?.remove();
  const box = document.createElement('div');
  box.id = '__rd';
  box.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;background:#111;color:#fff;font:14px system-ui;padding:14px 16px;border-radius:10px;box-shadow:0 6px 24px #0008;max-width:280px';
  box.textContent = 'Reel Digest: scrolling the collection...';
  document.body.appendChild(box);
  const found = new Set();
  let last = 0, still = 0;
  while (still < 4) {
    document.querySelectorAll('a[href*="/reel/"], a[href*="/p/"]').forEach((a) => {
      const m = a.href.match(/\/(?:reel|p)\/([\w-]+)/);
      if (m) found.add(m[1]);
    });
    box.textContent = 'Reel Digest: ' + found.size + ' found, scrolling...';
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise((r) => setTimeout(r, 1200));
    still = found.size === last ? still + 1 : 0;
    last = found.size;
  }
  const text = [...found].join('\n');
  window.__codes = [...found];
  const done = (msg) => {
    box.textContent = msg;
    const x = document.createElement('div');
    x.textContent = 'close';
    x.style.cssText = 'margin-top:8px;opacity:.6;cursor:pointer;font-size:12px';
    x.onclick = () => box.remove();
    box.appendChild(x);
  };
  try {
    window.focus();
    await navigator.clipboard.writeText(text);
    done(found.size + ' codes copied. Tell Claude: digest reels');
  } catch (e) {
    box.textContent = found.size + ' codes found. ';
    const b = document.createElement('button');
    b.textContent = 'Copy';
    b.style.cssText = 'margin-left:6px;padding:4px 12px;border:0;border-radius:6px;background:#4c8bf5;color:#fff;cursor:pointer';
    b.onclick = async () => {
      try {
        await navigator.clipboard.writeText(text);
        done(found.size + ' codes copied. Tell Claude: digest reels');
      } catch (e2) {
        done('Clipboard blocked. Press F12 and run: copy(__codes.join("\n"))');
      }
    };
    box.appendChild(b);
  }
}
