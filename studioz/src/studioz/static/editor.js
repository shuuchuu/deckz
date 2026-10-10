// The source editor beside a preview: one file at a time, saved into the
// workspace (where the running watch rebuilds), never over a version of the
// file the editor didn't read.
import {
  bracketMatching,
  classHighlighter,
  closeBrackets,
  closeBracketsKeymap,
  Decoration,
  defaultKeymap,
  drawSelection,
  EditorSelection,
  EditorState,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSelectionMatches,
  highlightSpecialChars,
  history,
  historyKeymap,
  indentOnInput,
  indentWithTab,
  keymap,
  lineNumbers,
  markdown,
  MatchDecorator,
  searchKeymap,
  syntaxHighlighting,
  ViewPlugin,
  yaml,
} from "/static/vendor/codemirror/codemirror.min.mjs";

// deckz renders content files with Jinja first: its tags stand out.
const jinja = new MatchDecorator({
  regexp: /\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}/g,
  decoration: Decoration.mark({ class: "cm-jinja" }),
});
const jinjaTags = ViewPlugin.define(
  (view) => ({
    decorations: jinja.createDeco(view),
    update(update) {
      this.decorations = jinja.updateDeco(update, this.decorations);
    },
  }),
  { decorations: (plugin) => plugin.decorations },
);

const STATUS = {
  saved: "Enregistré",
  modified: "Modifié",
  saving: "Enregistrement…",
  conflict: "Modifié ailleurs",
  failed: "Échec de l'enregistrement",
};

export class SourceEditor {
  // `pane` holds the elements with the ids used below; `base` is the URL
  // of the workspace's files, e.g. /espaces/x/fichiers; `notify` shows a
  // message outside the pane, which may be closed.
  constructor(pane, base, notify) {
    this.pane = pane;
    this.base = base;
    this.notify = notify;
    this.file = null;
    this.version = null;
    this.saved = null; // the text as last read or saved
    this.element = (id) => pane.querySelector(`#${id}`);
    this.view = new EditorView({ parent: this.element("editor") });
    this.element("editor-save").addEventListener("click", () => this.save());
    this.element("editor-close").addEventListener("click", () => this.close());
    this.element("editor-ask")?.addEventListener("click", () => this.ask());
    window.addEventListener("beforeunload", (event) => {
      if (this.dirty) event.preventDefault();
    });
  }

  get dirty() {
    return this.file !== null && this.view.state.doc.toString() !== this.saved;
  }

  url(file) {
    return `${this.base}/${file.split("/").map(encodeURIComponent).join("/")}`;
  }

  // Shows a problem above the editor (or hides it), with buttons
  // `{label: action}`.
  say(text, buttons = {}) {
    const message = this.element("editor-message");
    message.replaceChildren(text ?? "");
    for (const [label, action] of Object.entries(buttons)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = label;
      button.addEventListener("click", action);
      message.append(" ", button);
    }
    message.hidden = !text;
  }

  setStatus(status) {
    const element = this.element("editor-status");
    element.dataset.status = status ?? "";
    element.textContent = STATUS[status] ?? "";
    this.element("editor-save").disabled = status !== "modified";
  }

  state(file, text) {
    return EditorState.create({
      doc: text,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        indentOnInput(),
        syntaxHighlighting(classHighlighter),
        bracketMatching(),
        closeBrackets(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        EditorView.lineWrapping,
        file.endsWith(".yml") ? yaml() : [markdown(), jinjaTags],
        keymap.of([
          { key: "Mod-s", run: () => (this.save(), true) },
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...searchKeymap,
          ...historyKeymap,
          indentWithTab,
        ]),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) this.setStatus(this.dirty ? "modified" : "saved");
        }),
      ],
    });
  }

  // Opens `file` at `line` (from 1), the file shown already or not.
  async open(file, line) {
    if (file !== this.file) {
      if (
        this.dirty &&
        !window.confirm(`Abandonner les modifications non enregistrées de ${this.file} ?`)
      ) {
        return;
      }
      const response = await fetch(this.url(file));
      if (!response.ok) {
        this.notify(`Impossible d'ouvrir ${file} : ${(await response.json()).detail}`);
        return;
      }
      const { text, version } = await response.json();
      this.file = file;
      this.version = version;
      this.saved = text;
      this.view.setState(this.state(file, text));
      this.element("editor-file").textContent = file;
      this.setStatus("saved");
      this.pane.hidden = false;
    }
    this.say(null);
    this.goTo(line);
  }

  goTo(line) {
    const doc = this.view.state.doc;
    const position = doc.line(Math.min(Math.max(line ?? 1, 1), doc.lines)).from;
    this.view.dispatch({
      selection: EditorSelection.cursor(position),
      effects: EditorView.scrollIntoView(position, { y: "start", yMargin: 48 }),
    });
    this.view.focus();
  }

  async save(force = false) {
    if (!this.file || (!this.dirty && !force)) return;
    const text = this.view.state.doc.toString();
    const body = new FormData();
    body.set("text", text);
    body.set("version", this.version);
    this.setStatus("saving");
    let response;
    try {
      response = await fetch(this.url(this.file), { method: "POST", body });
    } catch {
      response = null;
    }
    if (response?.status === 409) {
      const { version } = await response.json();
      this.setStatus("conflict");
      this.say(`${this.file} a changé sur le disque depuis son ouverture.`, {
        "Recharger (abandonner mes modifications)": () => this.reload(),
        "Garder ma version": () => {
          this.version = version;
          this.save(true);
        },
      });
      return;
    }
    if (!response?.ok) {
      this.setStatus("failed");
      return;
    }
    this.version = (await response.json()).version;
    this.saved = text;
    // The Problems panel checks the workspace again.
    document.body.dispatchEvent(new Event("workspace-changed"));
    this.say(null);
    this.setStatus(this.dirty ? "modified" : "saved");
  }

  // Starts a message to the agent about the passage under the cursor (the
  // agent panel, `agent.js`, takes it).
  ask() {
    if (!this.file) return;
    const { state } = this.view;
    const range = state.selection.main;
    const line = state.doc.lineAt(range.head).number;
    let excerpt = state.sliceDoc(range.from, range.to).trim().replace(/\s+/g, " ");
    if (excerpt.length > 120) excerpt = `${excerpt.slice(0, 117)}…`;
    const text = `À propos de \`${this.file}\`, ligne ${line}${excerpt ? ` (« ${excerpt} »)` : ""} : `;
    document.dispatchEvent(new CustomEvent("agent-prefill", { detail: { text } }));
  }

  // Shows the file as it is on disk now, at the same place.
  async reload() {
    const response = await fetch(this.url(this.file));
    if (!response.ok) return;
    const { text, version } = await response.json();
    const line = this.view.state.doc.lineAt(this.view.state.selection.main.head).number;
    const top = this.view.scrollDOM.scrollTop;
    this.version = version;
    this.saved = text;
    this.view.setState(this.state(this.file, text));
    const doc = this.view.state.doc;
    this.view.dispatch({
      selection: EditorSelection.cursor(doc.line(Math.min(line, doc.lines)).from),
    });
    this.view.scrollDOM.scrollTop = top;
    this.say(null);
    this.setStatus("saved");
  }

  // Follows changes made outside studioz (another editor, the agent) to
  // the file, unless it has unsaved changes here.
  async refresh() {
    if (!this.file || this.dirty) return;
    const response = await fetch(this.url(this.file));
    if (response.ok && (await response.json()).version !== this.version) {
      await this.reload();
    }
  }

  close() {
    if (
      this.dirty &&
      !window.confirm(`Abandonner les modifications non enregistrées de ${this.file} ?`)
    ) {
      return;
    }
    this.file = null;
    this.saved = null;
    this.pane.hidden = true;
  }
}
