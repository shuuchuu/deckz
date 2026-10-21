// The agent panel (`_agent.html`): the conversation, followed through
// server-sent events (`/agent/evenements`), and the message box.
import { showAgent } from "/static/layout.js";

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
  const slot = document.getElementById("agent-question");
  const undo = document.getElementById("agent-undo");
  const usage = document.getElementById("agent-usage");
  const model = document.getElementById("agent-model");
  // The file the message is about (the editor's): another file than the
  // conversation's starts a new one (`Conversation.send`).
  const about = document.getElementById("agent-about");
  const base = panel.dataset.base;
  let running = false;
  let asking = false;
  let undoable = 0;
  let pausedUntil = "";
  let loggedIn = false;
  let aside = false;

  const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 40;

  function update() {
    panel.dataset.running = String(running);
    status.textContent = !loggedIn ? "" : asking ? "attend votre réponse" : running ? "travaille…"
      : pausedUntil ? `en pause jusqu'à ${pausedUntil.replace(/^le /, "")}` : "prêt";
    // A question asked at the end of a turn waits without it: "Écarter" drops it.
    stop.hidden = !running && !pausedUntil && !asking;
    stop.textContent = running ? "Arrêter" : asking ? "Écarter la question" : "Annuler la reprise";
    undo.hidden = running || !undoable;
    send.disabled = running || !loggedIn;
    message.disabled = !loggedIn;
    // Only the last one: it takes back the conversation set aside last.
    const buttons = log.querySelectorAll("[data-agent-aside]");
    buttons.forEach((button, i) => {
      button.disabled = running || !aside || i < buttons.length - 1;
    });
  }

  const events = new EventSource(panel.dataset.events);
  events.addEventListener("reset", () => { log.replaceChildren(); });
  events.addEventListener("entry", (event) => {
    const follow = atBottom();
    log.insertAdjacentHTML("beforeend", JSON.parse(event.data).html);
    if (follow) log.scrollTop = log.scrollHeight;
    update();
  });
  events.addEventListener("state", (event) => {
    const state = JSON.parse(event.data);
    const finished = running && !state.running;
    running = state.running;
    asking = state.asking;
    undoable = state.undoable;
    pausedUntil = state.pausedUntil;
    aside = state.aside;
    model.textContent = state.model;
    usage.textContent = state.usage.text;
    usage.title = state.usage.title;
    usage.classList.toggle("warn", state.usage.warn);
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
  // The question the agent waits on: a form above the message box.
  events.addEventListener("question", (event) => {
    slot.innerHTML = JSON.parse(event.data).html;
    const form = slot.querySelector("form");
    if (!form) return;
    form.querySelector("input:not([type=hidden])")?.focus();
    form.addEventListener("submit", async (submitted) => {
      submitted.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      if (!(await post("reponse", new FormData(form)))) button.disabled = false;
    });
    // Typing a free answer picks it.
    for (const text of form.querySelectorAll(".other input[type=text]")) {
      text.addEventListener("input", () => {
        const radio = text.parentElement.querySelector("input[type=radio]");
        if (radio && text.value.trim()) radio.checked = true;
      });
    }
  });
  events.addEventListener("error", () => { status.textContent = "reconnexion…"; });
  events.addEventListener("open", () => { status.textContent = ""; update(); });

  // Its own line: the state's next update rewrites the status.
  const failure = document.getElementById("agent-error");
  async function post(path, body) {
    const response = await fetch(`${base}/${path}`, { method: "POST", body });
    failure.hidden = response.ok;
    if (!response.ok) {
      let error = "La demande n'a pas abouti";
      try { error = (await response.json()).error; } catch {}
      failure.textContent = error;
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
    body.set("about", about.value);
    if (await post("message", body)) {
      message.value = "";
      about.value = "";
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
  // Emptied, the message is about nothing in particular any more.
  message.addEventListener("input", () => {
    if (!message.value.trim()) about.value = "";
  });
  stop.addEventListener("click", () => post("arreter"));
  log.addEventListener("click", (event) => {
    const button = event.target.closest("[data-agent-aside]");
    if (!button) return;
    button.disabled = true;
    post("precedente");
  });

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

  // A second click confirms: the files go back as they were before the turn.
  let undoConfirming = null;
  const undoLabel = "Annuler ce tour";
  undo.addEventListener("click", async () => {
    if (!undoConfirming) {
      undo.textContent = `Remettre ${undoable} fichier${undoable > 1 ? "s" : ""} ?`;
      undoConfirming = setTimeout(() => { undo.textContent = undoLabel; undoConfirming = null; }, 4000);
      return;
    }
    clearTimeout(undoConfirming);
    undoConfirming = null;
    undo.textContent = undoLabel;
    if (await post("annuler")) {
      document.body.dispatchEvent(new Event("workspace-changed"));
      document.body.dispatchEvent(new Event("comparison-refresh"));
    }
  });

  // A dialog's "Demander à l'agent" (`asks.prompt` writes the message).
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-agent-task]");
    if (!button) return;
    const body = new FormData();
    body.set("task", button.dataset.agentTask);
    for (const [key, value] of Object.entries(JSON.parse(button.dataset.agentValues || "{}"))) {
      for (const item of [].concat(value)) body.append(key, item);
    }
    button.disabled = true;
    const response = await fetch(`${base}/demander`, { method: "POST", body });
    if (response.ok) {
      button.closest("dialog")?.close();
      showAgent(true);
      return;
    }
    button.disabled = false;
    let error = "La demande n'est pas partie";
    try { error = (await response.json()).error; } catch {}
    let shown = button.nextElementSibling;
    if (!shown?.classList.contains("agent-ask-error")) {
      shown = document.createElement("span");
      shown.className = "error agent-ask-error";
      button.after(shown);
    }
    shown.textContent = ` ${error}`;
  });

  // A workflow started from its dialog (`_workflow.html`).
  document.body.addEventListener("agent-started", (event) => {
    event.target.closest?.("dialog")?.close();
    showAgent(true);
    log.scrollTop = log.scrollHeight;
  });

  // The editor's "Demander à l'agent": a message started about a passage.
  document.addEventListener("agent-prefill", (event) => {
    showAgent(true);
    message.value = event.detail.text + message.value;
    about.value = event.detail.file || "";
    message.focus();
    message.setSelectionRange(event.detail.text.length, event.detail.text.length);
  });

  // A workflow started from the home page opens its workspace with `?agent`.
  if (new URLSearchParams(location.search).has("agent")) showAgent(true);
}
