// A workspace's pages laid out like VS Code (`workspace_base.html`): the
// activity bar picks the sidebar's view (clicking the one shown hides the
// sidebar), the panel below the page shows one tab, the sashes resize the
// sidebar, the agent, the panel, and the PDF against the editor, Ctrl+B, Ctrl+Alt+B and Ctrl+J show or
// hide them, and the badges and the status bar repeat what the panels count.
// What the person chose is kept per browser; the page's inline script
// applies it before the first paint.
const body = document.body;
const sidebar = document.getElementById("sidebar");
const agent = document.getElementById("agent");
const panel = document.getElementById("panel");
const buttons = [...document.querySelectorAll(".activity-bar [data-view]")];
const views = [...document.querySelectorAll(".primary-sidebar > .view")];
const tabs = [...document.querySelectorAll("[data-panel-tab]")];
const tabViews = [...document.querySelectorAll("[data-panel-view]")];
// The largest each may be, as a share of the window (the CSS has the same).
const MAX_SHARE = { sidebar: 0.35, agent: 0.45, panel: 0.6 };
const MIN_SIZE = { sidebar: 180, agent: 180, panel: 100 };

function store(key, value) {
  try { localStorage.setItem(`studioz-${key}`, value); } catch {}
}
function stored(key) {
  try { return localStorage.getItem(`studioz-${key}`); } catch { return null; }
}

let current = stored("sidebar-view");
if (!views.some((view) => view.dataset.view === current)) current = "formations";
// A tab only some pages have (Construction) falls back to the first.
let currentTab = stored("panel-tab");
if (!tabs.some((tab) => tab.dataset.panelTab === currentTab)) currentTab = tabs[0]?.dataset.panelTab;

const sidebarShown = () => !body.classList.contains("sidebar-hidden");
const agentShown = () => !body.classList.contains("agent-folded");
const panelShown = () => !body.classList.contains("panel-hidden");
const SHOWN = { sidebar: sidebarShown, agent: agentShown, panel: panelShown };

function render() {
  for (const view of views) view.hidden = view.dataset.view !== current;
  for (const button of buttons) {
    button.setAttribute("aria-pressed", String(sidebarShown() && button.dataset.view === current));
  }
  for (const view of tabViews) view.hidden = view.dataset.panelView !== currentTab;
  for (const tab of tabs) tab.setAttribute("aria-selected", String(tab.dataset.panelTab === currentTab));
  for (const toggle of document.querySelectorAll("[data-toggle]")) {
    toggle.setAttribute("aria-pressed", String(SHOWN[toggle.dataset.toggle]()));
  }
}

export function showSidebar(shown) {
  body.classList.toggle("sidebar-hidden", !shown);
  store("sidebar-hidden", shown ? "" : "1");
  render();
}

export function showView(view) {
  if (views.some((section) => section.dataset.view === view)) {
    current = view;
    store("sidebar-view", view);
  }
  showSidebar(true);
}

export function showAgent(shown) {
  body.classList.toggle("agent-folded", !shown);
  store("agent-folded", shown ? "" : "1");
  render();
}

// Shows or hides the panel, on `tab` when given.
export function showPanel(shown, tab = null) {
  if (tabs.some((button) => button.dataset.panelTab === tab)) {
    currentTab = tab;
    store("panel-tab", tab);
  }
  body.classList.toggle("panel-hidden", !shown);
  store("panel-shown", shown ? "1" : "");
  render();
}

const TOGGLES = {
  sidebar: () => showSidebar(!sidebarShown()),
  agent: () => showAgent(!agentShown()),
  panel: () => showPanel(!panelShown()),
};

for (const button of buttons) {
  button.addEventListener("click", () => {
    if (sidebarShown() && button.dataset.view === current) showSidebar(false);
    else showView(button.dataset.view);
  });
}
for (const tab of tabs) {
  tab.addEventListener("click", () => showPanel(true, tab.dataset.panelTab));
}

document.addEventListener("click", (event) => {
  const view = event.target.closest("[data-show-view]");
  if (view) showView(view.dataset.showView);
  // The status bar's items toggle their tab, as VS Code's do.
  const item = event.target.closest("[data-show-panel]");
  if (item) {
    const tab = item.dataset.showPanel;
    showPanel(!(panelShown() && currentTab === tab), tab);
  }
  // The palette's commands show a tab, whatever is shown already.
  const opened = event.target.closest("[data-open-panel]");
  if (opened) showPanel(true, opened.dataset.openPanel);
  const toggle = event.target.closest("[data-toggle]");
  if (toggle) TOGGLES[toggle.dataset.toggle]?.();
});

document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.shiftKey) return;
  const key = event.key.toLowerCase();
  if (key === "b") {
    event.preventDefault();
    TOGGLES[event.altKey ? "agent" : "sidebar"]();
  } else if (key === "j" && !event.altKey) {
    event.preventDefault();
    TOGGLES.panel();
  }
});

// A job started from a dialog: the dialog closes, the panel's Tâches tab
// follows it (the response's `HX-Trigger-After-Settle`). The form that sent
// it is gone by then: the dialog is the one showing the job started.
body.addEventListener("job-started", () => {
  for (const dialog of document.querySelectorAll("dialog")) {
    if (!dialog.querySelector("[data-job-started]")) continue;
    dialog.close();
    dialog.replaceChildren();
  }
  showPanel(true, "taches");
});

// The sashes: drag to resize, double-click for the default size.
function setSize(side, pixels) {
  const window_ = side === "panel" ? window.innerHeight : window.innerWidth;
  const largest = window_ * MAX_SHARE[side];
  const clamped = Math.round(Math.min(Math.max(pixels, MIN_SIZE[side]), largest));
  body.style.setProperty(`--${side}-${side === "panel" ? "height" : "width"}`, `${clamped}px`);
  return clamped;
}

// The PDF and the editor share their space by a ratio, the PDF's: it holds
// when the sidebars or the window change, side by side or one above the other.
const SPLIT = [0.15, 0.85];

function splitSash(sash) {
  const shared = sash.parentElement;
  sash.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    sash.setPointerCapture(event.pointerId);
    const column = getComputedStyle(shared).flexDirection === "column";
    body.classList.add("resizing", column ? "resizing-height" : "resizing-width");
    const box = shared.getBoundingClientRect();
    let ratio = null;
    const move = (moved) => {
      const share = column
        ? (moved.clientY - box.top) / box.height
        : (moved.clientX - box.left) / box.width;
      ratio = Math.round(Math.min(Math.max(share, SPLIT[0]), SPLIT[1]) * 1000) / 1000;
      body.style.setProperty("--split", String(ratio));
    };
    sash.addEventListener("pointermove", move);
    sash.addEventListener("lostpointercapture", () => {
      sash.removeEventListener("pointermove", move);
      body.classList.remove("resizing", "resizing-height", "resizing-width");
      if (ratio !== null) store("split", String(ratio));
    }, { once: true });
  });
  sash.addEventListener("dblclick", () => {
    body.style.removeProperty("--split");
    store("split", "");
  });
}

for (const sash of document.querySelectorAll(".sash")) {
  const side = sash.dataset.side;
  if (side === "split") {
    splitSash(sash);
    continue;
  }
  const resized = { sidebar, agent, panel }[side];
  const dimension = side === "panel" ? "height" : "width";
  sash.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    sash.setPointerCapture(event.pointerId);
    body.classList.add("resizing", `resizing-${dimension}`);
    const { left, right, bottom } = resized.getBoundingClientRect();
    let size = null;
    const move = (moved) => {
      const pixels = {
        sidebar: moved.clientX - left,
        agent: right - moved.clientX,
        panel: bottom - moved.clientY,
      }[side];
      size = setSize(side, pixels);
    };
    sash.addEventListener("pointermove", move);
    sash.addEventListener("lostpointercapture", () => {
      sash.removeEventListener("pointermove", move);
      body.classList.remove("resizing", `resizing-${dimension}`);
      if (size !== null) store(`${side}-${dimension}`, String(size));
    }, { once: true });
  });
  sash.addEventListener("dblclick", () => {
    body.style.removeProperty(`--${side}-${dimension}`);
    store(`${side}-${dimension}`, "");
  });
}

// The counts the panels show, on the badges and the status bar.
function count(selector) {
  const element = document.querySelector(`${selector} .count`);
  return element ? Number(element.textContent.trim()) || 0 : null;
}

function mirror() {
  for (const badge of document.querySelectorAll("[data-badge-of]")) {
    badge.textContent = count(badge.dataset.badgeOf) || "";
  }
  const problems = count("#problems");
  const status = document.querySelector("#status-problems .count");
  if (status) {
    status.textContent = problems ?? "…";
    status.parentElement.classList.toggle("warn", Boolean(problems));
  }
  const sync = document.getElementById("sync");
  const counts = document.getElementById("status-sync");
  if (sync && counts) {
    const ahead = Number(sync.dataset.ahead) || 0;
    const behind = Number(sync.dataset.behind) || 0;
    counts.textContent = [behind && `↓${behind}`, ahead && `↑${ahead}`].filter(Boolean).join(" ");
  }
}
body.addEventListener("htmx:afterSettle", mirror);
mirror();

// The agent's state, on the status bar, where it shows even with the agent
// hidden.
const agentStatus = document.getElementById("agent-status");
const agentItem = document.getElementById("status-agent");
if (agent && agentStatus && agentItem) {
  const follow = () => {
    const text = agentStatus.textContent.trim();
    agentItem.textContent = text ? `Agent : ${text}` : "Agent";
    agentItem.dataset.running = agent.dataset.running;
  };
  const observer = new MutationObserver(follow);
  observer.observe(agentStatus, { childList: true, characterData: true, subtree: true });
  observer.observe(agent, { attributes: true, attributeFilter: ["data-running"] });
  follow();
}

// The deck tree: the folders opened stay open from page to page; the filter
// shows the decks whose path has the text, their folders opened.
const tree = document.querySelector(".decks.tree");
const filter = document.getElementById("deck-filter");
if (tree && filter) {
  const folders = [...tree.querySelectorAll("details.folder")];
  const around = new Set(folders.filter((folder) => folder.open).map((folder) => folder.dataset.folder));
  const opened = new Set(JSON.parse(stored("open-folders") || "[]"));
  const restore = () => {
    for (const folder of folders) {
      folder.open = around.has(folder.dataset.folder) || opened.has(folder.dataset.folder);
    }
  };
  restore();
  // `toggle` doesn't bubble.
  tree.addEventListener("toggle", (event) => {
    if (filter.value.trim()) return;
    const path = event.target.dataset.folder;
    if (event.target.open) opened.add(path);
    else opened.delete(path);
    store("open-folders", JSON.stringify([...opened]));
  }, true);
  filter.addEventListener("input", () => {
    const text = filter.value.trim().toLowerCase();
    for (const deck of tree.querySelectorAll("li.deck-item")) {
      deck.hidden = Boolean(text) && !deck.dataset.path.toLowerCase().includes(text);
    }
    if (!text) restore();
    for (const folder of folders) {
      const shown = Boolean(folder.querySelector("li.deck-item:not([hidden])"));
      folder.parentElement.hidden = !shown;
      if (text) folder.open = shown;
    }
  });
  tree.querySelector("li.current")?.scrollIntoView({ block: "nearest" });
}

// The TP view's filter: the labs whose path has the text, and their
// folders. The list reloads whenever the workspace changes, the filter kept.
function filterLabs() {
  const filter = document.getElementById("lab-filter");
  const list = document.querySelector(".labs-list");
  if (!filter || !list) return;
  const text = filter.value.trim().toLowerCase();
  for (const lab of list.querySelectorAll("li.lab-item")) {
    lab.hidden = Boolean(text) && !lab.dataset.lab.toLowerCase().includes(text);
  }
  for (const folder of list.querySelectorAll("details.folder")) {
    folder.parentElement.hidden = !folder.querySelector("li.lab-item:not([hidden])");
  }
}
document.addEventListener("input", (event) => {
  if (event.target.id === "lab-filter") filterLabs();
});
document.body.addEventListener("htmx:afterSettle", filterLabs);

render();
