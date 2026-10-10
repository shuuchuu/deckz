// The agent panel (`_agent.html`): the conversation, followed through
// server-sent events (`/agent/evenements`), and the message box.
const panel = document.getElementById("agent");

if (panel) {
  const log = document.getElementById("agent-log");
  const form = document.getElementById("agent-form");
  const message = document.getElementById("agent-message");
  const send = document.getElementById("agent-send");
  const stop = document.getElementById("agent-stop");
  const status = document.getElementById("agent-status");
  const login = document.getElementById("agent-login");
  const fresh = document.getElementById("agent-new");
  const fold = document.getElementById("agent-fold");
  const base = panel.dataset.base;
  let running = false;
  let loggedIn = false;

  const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 40;

  function update() {
    panel.dataset.running = String(running);
    status.textContent = !loggedIn ? "" : running ? "travaille…" : "prêt";
    stop.hidden = !running;
    send.disabled = running || !loggedIn;
    message.disabled = !loggedIn;
  }

  const events = new EventSource(panel.dataset.events);
  events.addEventListener("reset", () => { log.replaceChildren(); });
  events.addEventListener("entry", (event) => {
    const follow = atBottom();
    log.insertAdjacentHTML("beforeend", JSON.parse(event.data).html);
    if (follow) log.scrollTop = log.scrollHeight;
  });
  events.addEventListener("state", (event) => {
    const state = JSON.parse(event.data);
    const finished = running && !state.running;
    running = state.running;
    loggedIn = state.loggedIn;
    login.hidden = loggedIn;
    status.title = loggedIn && state.account ? `Compte Claude : ${state.account}` : "";
    login.textContent = loggedIn ? "" :
      `${state.account}. Dans un terminal, lancez « uv run studioz login » depuis le dépôt et connectez-vous avec votre compte Claude ; ce panneau le verra tout seul.`;
    update();
    if (finished) {
      // What the agent changed shows in the panels and the before/after view.
      document.body.dispatchEvent(new Event("workspace-changed"));
      document.body.dispatchEvent(new Event("comparison-refresh"));
    }
  });
  events.addEventListener("error", () => { status.textContent = "reconnexion…"; });
  events.addEventListener("open", () => { status.textContent = ""; update(); });

  async function post(path, body) {
    const response = await fetch(`${base}/${path}`, { method: "POST", body });
    if (!response.ok && response.headers.get("content-type")?.includes("json")) {
      status.textContent = (await response.json()).error;
    }
    return response.ok;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = message.value.trim();
    if (!text || running) return;
    running = true;
    update();
    const body = new FormData();
    body.set("message", text);
    if (await post("message", body)) {
      message.value = "";
      log.scrollTop = log.scrollHeight;
    } else {
      running = false;
      update();
    }
  });
  message.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  stop.addEventListener("click", () => post("arreter"));

  // A second click confirms: the conversation is forgotten.
  let confirming = null;
  fresh.addEventListener("click", async () => {
    if (!confirming) {
      fresh.textContent = "Oublier la conversation ?";
      confirming = setTimeout(() => { fresh.textContent = "Nouvelle conversation"; confirming = null; }, 4000);
      return;
    }
    clearTimeout(confirming);
    confirming = null;
    fresh.textContent = "Nouvelle conversation";
    await post("nouvelle");
  });

  const folded = () => document.body.classList.contains("agent-folded");
  function setFolded(value) {
    document.body.classList.toggle("agent-folded", value);
    fold.setAttribute("aria-expanded", String(!value));
    fold.textContent = value ? "⇤" : "⇥";
    try { localStorage.setItem("studioz-agent-folded", value ? "1" : ""); } catch {}
  }
  try { setFolded(localStorage.getItem("studioz-agent-folded") === "1"); } catch {}
  fold.addEventListener("click", () => setFolded(!folded()));
}
