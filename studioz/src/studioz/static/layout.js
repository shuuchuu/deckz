// A workspace's pages laid out like VS Code (`workspace_base.html`): the
// activity bar picks the sidebar's view (clicking the one shown hides the
// sidebar), the sashes resize the sidebar and the agent, Ctrl+B and
// Ctrl+Alt+B show or hide them, and the activity bar's badges and the status
// bar repeat what the panels count. What the person chose is kept per
// browser; the page's inline script applies it before the first paint.
const body = document.body;
const sidebar = document.getElementById("sidebar");
const agent = document.getElementById("agent");
const buttons = [...document.querySelectorAll(".activity-bar [data-view]")];
const views = [...document.querySelectorAll(".primary-sidebar > .view")];
// The widest each may be, as a share of the window (the CSS has the same).
const MAX_SHARE = { sidebar: 0.35, agent: 0.45 };
const MIN_WIDTH = 180;

function store(key, value) {
  try { localStorage.setItem(`studioz-${key}`, value); } catch {}
}
function stored(key) {
  try { return localStorage.getItem(`studioz-${key}`); } catch { return null; }
}

let current = stored("sidebar-view");
if (!views.some((view) => view.dataset.view === current)) current = "formations";

const sidebarShown = () => !body.classList.contains("sidebar-hidden");
const agentShown = () => !body.classList.contains("agent-folded");

function render() {
  for (const view of views) view.hidden = view.dataset.view !== current;
  for (const button of buttons) {
    button.setAttribute("aria-pressed", String(sidebarShown() && button.dataset.view === current));
  }
  for (const toggle of document.querySelectorAll("[data-toggle]")) {
    const shown = toggle.dataset.toggle === "agent" ? agentShown() : sidebarShown();
    toggle.setAttribute("aria-pressed", String(shown));
  }
}

export function showSidebar(shown) {
  body.classList.toggle("sidebar-hidden", !shown);
  store("sidebar-hidden", shown ? "" : "1");
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
    for (const deck of tree.querySelectorAll("li.deck")) {
      deck.hidden = Boolean(text) && !deck.dataset.path.toLowerCase().includes(text);
    }
    if (!text) restore();
    for (const folder of folders) {
      const shown = Boolean(folder.querySelector("li.deck:not([hidden])"));
      folder.parentElement.hidden = !shown;
      if (text) folder.open = shown;
    }
  });
  tree.querySelector("li.current")?.scrollIntoView({ block: "nearest" });
}

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

for (const button of buttons) {
  button.addEventListener("click", () => {
    if (sidebarShown() && button.dataset.view === current) showSidebar(false);
    else showView(button.dataset.view);
  });
}

document.addEventListener("click", (event) => {
  const view = event.target.closest("[data-show-view]");
  if (view) showView(view.dataset.showView);
  const toggle = event.target.closest("[data-toggle]");
  if (toggle?.dataset.toggle === "agent") showAgent(!agentShown());
  else if (toggle) showSidebar(!sidebarShown());
});

document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.key.toLowerCase() !== "b") return;
  event.preventDefault();
  if (event.altKey) showAgent(!agentShown());
  else showSidebar(!sidebarShown());
});

// The sashes: drag to resize, double-click for the default width.
function setWidth(side, width) {
  const widest = window.innerWidth * MAX_SHARE[side];
  const clamped = Math.round(Math.min(Math.max(width, MIN_WIDTH), widest));
  body.style.setProperty(`--${side}-width`, `${clamped}px`);
  return clamped;
}

for (const sash of document.querySelectorAll(".sash")) {
  const side = sash.dataset.side;
  const panel = side === "agent" ? agent : sidebar;
  sash.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    sash.setPointerCapture(event.pointerId);
    body.classList.add("resizing");
    const { left, right } = panel.getBoundingClientRect();
    let width = null;
    const move = (moved) => {
      width = setWidth(side, side === "agent" ? right - moved.clientX : moved.clientX - left);
    };
    sash.addEventListener("pointermove", move);
    sash.addEventListener("lostpointercapture", () => {
      sash.removeEventListener("pointermove", move);
      body.classList.remove("resizing");
      if (width !== null) store(`${side}-width`, String(width));
    }, { once: true });
  });
  sash.addEventListener("dblclick", () => {
    body.style.removeProperty(`--${side}-width`);
    store(`${side}-width`, "");
  });
}

// The counts the panels show, on the activity bar and the status bar.
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

render();
