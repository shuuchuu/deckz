// VS Code's notifications, for the workspace's jobs: a toast at the bottom
// right when one ends (a success hides itself, a failure stays until
// closed), the status bar's bell keeping the last ones, and a desktop
// notification when the page is hidden, once the person allowed them (from
// the bell's center: a browser asks only after a click).
//
// The status bar's jobs item reloads every few seconds with the last jobs
// ended (`data-ended`); each is notified once per browser, those ended
// before the workspace was first opened here never. Kept per workspace:
// what was notified, the notifications, what was read.
const body = document.body;
const workspace = decodeURIComponent(location.pathname.split("/")[2] || "");
const toasts = document.getElementById("toasts");
const center = document.getElementById("notification-center");
const bell = document.getElementById("status-bell");
const KEPT = 20;
const HIDE_AFTER = 8000;

const HEADLINES = {
  done: "Tâche terminée",
  failed: "Tâche échouée",
  stopped: "Tâche arrêtée",
  interrupted: "Tâche interrompue",
};
const ICONS = { done: "✓", failed: "✕", stopped: "■", interrupted: "!" };

function stored(key, fallback) {
  try {
    const value = localStorage.getItem(`studioz-${key}-${workspace}`);
    return value === null ? fallback : JSON.parse(value);
  } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(`studioz-${key}-${workspace}`, JSON.stringify(value)); } catch {}
}

function item(notification, { toast }) {
  const li = document.createElement("li");
  li.className = "notification";
  li.dataset.state = notification.state;
  const icon = document.createElement("span");
  icon.className = "notification-icon";
  icon.textContent = ICONS[notification.state] || "•";
  const text = document.createElement("div");
  text.className = "notification-text";
  const headline = document.createElement("strong");
  headline.textContent = HEADLINES[notification.state] || "Tâche finie";
  const title = document.createElement("span");
  title.textContent = notification.title;
  text.append(headline, title);
  if (notification.detail) {
    const detail = document.createElement("code");
    detail.textContent = notification.detail;
    text.append(detail);
  }
  const when = document.createElement("time");
  when.dateTime = new Date(notification.ended).toISOString();
  when.textContent = new Date(notification.ended).toLocaleTimeString("fr", { hour: "2-digit", minute: "2-digit" });
  text.append(when);
  const actions = document.createElement("div");
  actions.className = "notification-actions";
  const log = document.createElement("button");
  log.type = "button";
  log.className = "secondary";
  log.dataset.openPanel = "taches";
  log.textContent = "Voir le journal";
  actions.append(log);
  li.append(icon, text, actions);
  if (toast) {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "icon notification-close";
    close.title = "Fermer";
    close.setAttribute("aria-label", "Fermer");
    close.textContent = "✕";
    close.addEventListener("click", () => li.remove());
    log.addEventListener("click", () => li.remove());
    li.append(close);
  }
  return li;
}

function showToast(notification) {
  const li = item(notification, { toast: true });
  toasts.append(li);
  if (notification.state !== "done") return;
  const hide = () => {
    if (li.matches(":hover")) setTimeout(hide, 1000);
    else li.remove();
  };
  setTimeout(hide, HIDE_AFTER);
}

function showDesktop(notification) {
  if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  const shown = new Notification(`${HEADLINES[notification.state]} — studioz`, {
    body: [notification.title, notification.detail].filter(Boolean).join("\n"),
    tag: `studioz-${workspace}-${notification.id}-${notification.ended}`,
  });
  shown.addEventListener("click", () => {
    window.focus();
    document.querySelector('[data-open-panel="taches"]')?.click();
  });
}

function renderCenter() {
  const list = center.querySelector(".notification-list");
  const kept = stored("notifications", []);
  list.replaceChildren(...kept.slice().reverse().map((n) => item(n, { toast: false })));
  center.querySelector(".empty").hidden = kept.length > 0;
  const desktop = center.querySelector('[data-notifications="desktop"]');
  desktop.hidden = !("Notification" in window) || Notification.permission !== "default";
  const read = stored("notifications-read", 0);
  const unread = kept.filter((n) => n.ended > read).length;
  const dot = bell.querySelector(".unread");
  dot.hidden = !unread;
  dot.textContent = unread || "";
  bell.title = unread ? `Notifications : ${unread} non lue${unread > 1 ? "s" : ""}` : "Notifications";
}

function openCenter(open) {
  center.hidden = !open;
  bell.setAttribute("aria-expanded", String(open));
  if (open) {
    const kept = stored("notifications", []);
    store("notifications-read", Math.max(0, ...kept.map((n) => n.ended)));
    // Toasts shown are in the center too.
    toasts.replaceChildren();
  }
  renderCenter();
}

function followEnded() {
  const badge = document.querySelector(".jobs-badge[data-ended]");
  if (!badge) return;
  let ended;
  try { ended = JSON.parse(badge.dataset.ended); } catch { return; }
  const latest = Math.max(0, ...ended.map((job) => job.ended));
  const notified = stored("notified", null);
  if (notified === null) {
    // First time here: what ended before isn't news.
    store("notified", latest || Date.now());
    return;
  }
  const fresh = ended.filter((job) => job.ended > notified).sort((a, b) => a.ended - b.ended);
  if (!fresh.length) return;
  store("notified", latest);
  const kept = [...stored("notifications", []), ...fresh].slice(-KEPT);
  store("notifications", kept);
  for (const job of fresh) {
    if (center.hidden) showToast(job);
    showDesktop(job);
  }
  if (!center.hidden) store("notifications-read", latest);
  renderCenter();
}

bell.addEventListener("click", () => openCenter(center.hidden));
center.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-notifications]")?.dataset.notifications;
  if (action === "close") openCenter(false);
  if (action === "clear") {
    store("notifications", []);
    renderCenter();
  }
  if (action === "desktop") {
    await Notification.requestPermission();
    renderCenter();
  }
  if (event.target.closest("[data-open-panel]")) openCenter(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !center.hidden) openCenter(false);
});
document.addEventListener("pointerdown", (event) => {
  if (!center.hidden && !center.contains(event.target) && !bell.contains(event.target)) openCenter(false);
});
// Another tab of the workspace notified, or read them.
window.addEventListener("storage", (event) => {
  if (event.key?.endsWith(`-${workspace}`)) renderCenter();
});

// A job's log follows its end as it grows, unless the person scrolled up
// in it: each reload replaces it.
const scrolled = new Map();
body.addEventListener("htmx:beforeSwap", () => {
  for (const log of document.querySelectorAll(".job-log")) {
    const id = log.closest(".job")?.id;
    if (!id) continue;
    const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 8;
    scrolled.set(id, atEnd ? null : log.scrollTop);
  }
});
body.addEventListener("htmx:afterSettle", (event) => {
  for (const log of document.querySelectorAll(".job-log")) {
    const top = scrolled.get(log.closest(".job")?.id);
    log.scrollTop = top ?? log.scrollHeight;
  }
  if (event.target.closest?.("#jobs-badge") || event.target.id === "jobs-badge") followEnded();
});

renderCenter();
