// The deck page: its handout in pdf.js, reloaded at the same place each time
// the workspace's `deckz run --watch` finishes a build (server-sent events).
// A click on a page opens its frame's source in the editor beside it.
import { SourceEditor } from "/static/editor.js";
import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

globalThis.pdfjsLib = pdfjsLib;
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
const { EventBus, PDFLinkService, PDFViewer } = await import(
  "/static/vendor/pdfjs/web/pdf_viewer.mjs"
);

const LABELS = {
  building: "Construction…",
  built: "À jour",
  failed: "Échec de la construction",
  stopped: "Construction arrêtée",
  disconnected: "Connexion perdue, nouvelle tentative…",
};

const deck = document.getElementById("deck");
const container = document.getElementById("viewer-container");
const build = document.getElementById("build");
const errors = document.getElementById("errors");
const errorMessage = document.getElementById("error-message");
const errorDetails = document.getElementById("error-details");
const errorLines = document.getElementById("error-lines");
const waiting = document.getElementById("waiting");
const pageNumber = document.getElementById("page-number");
const notice = document.getElementById("notice");

const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus });
const viewer = new PDFViewer({ container, eventBus, linkService });
linkService.setViewer(viewer);

function showPageNumber() {
  pageNumber.textContent = `p. ${viewer.currentPageNumber} / ${viewer.pagesCount}`;
}

eventBus.on("pagesinit", () => {
  viewer.currentScaleValue = "page-width";
});
eventBus.on("pagechanging", showPageNumber);
// The window's size, and the editor opening or closing. The page clicked
// to open the editor stays in view.
let clicked = null;
new ResizeObserver(() => {
  if (!viewer.pagesCount) return;
  viewer.currentScaleValue = "page-width";
  if (clicked) viewer.scrollPageIntoView({ pageNumber: clicked });
  clicked = null;
}).observe(container);

// Each page's frame in the PDF shown: {page, title, file, line}.
let frames = new Map();
let framesError = null;

async function loadFrames() {
  try {
    const response = await fetch(deck.dataset.frames);
    const { frames: found, error } = await response.json();
    frames = new Map(found.map((frame) => [frame.page, frame]));
    framesError = error ?? null;
  } catch (error) {
    console.error("studioz: could not load the frames", error);
  }
}

let noticeTimer = null;

function showNotice(text) {
  notice.textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => (notice.textContent = ""), 6000);
}

const editor = new SourceEditor(
  document.getElementById("editor-pane"),
  deck.dataset.files,
  showNotice,
);

// Opens a file at a line in the editor, keeping `page` in view.
function openSource(file, line, page) {
  notice.textContent = "";
  // The editor opening narrows the PDF.
  clicked = editor.pane.hidden ? page : null;
  editor.open(file, line);
}

container.addEventListener("click", (event) => {
  // Following a link, or selecting text, isn't asking for the source.
  if (event.target.closest("a") || !window.getSelection().isCollapsed) return;
  const page = event.target.closest(".page");
  if (!page) return;
  const frame = frames.get(Number(page.dataset.pageNumber));
  if (frame?.file) {
    openSource(frame.file, frame.line, frame.page);
  } else if (frame) {
    showNotice(`La source du cadre « ${frame.title} » est introuvable.`);
  } else {
    showNotice(
      framesError ??
        "Cette page n'a pas de source à elle : page de titre, sommaire ou intercalaire.",
    );
  }
});

let shown = null; // the loading task of the PDF shown, which destroys it
let next = null;
let loading = false;

// Loads the latest URL announced, one at a time: a build finishing during a
// load is shown right after it.
async function show(url) {
  next = url;
  if (loading) return;
  loading = true;
  while (next) {
    const url = next;
    next = null;
    const task = pdfjsLib.getDocument({ url });
    try {
      const pdf = await task.promise;
      // Read when swapping, not when the load started: the person may
      // have scrolled meanwhile.
      const top = container.scrollTop;
      const initialized = new Promise((resolve) =>
        eventBus.on("pagesinit", resolve, { once: true }),
      );
      viewer.setDocument(pdf);
      linkService.setDocument(pdf);
      await initialized;
      if (shown) {
        container.scrollTop = top;
        shown.destroy();
      }
      shown = task;
      waiting.hidden = true;
      showPageNumber();
      await loadFrames();
      editor.refresh();
    } catch (error) {
      console.error("studioz: could not show", url, error);
    }
  }
  loading = false;
}

// The Problems panel's links (`_problems.html`).
document.addEventListener("click", (event) => {
  const link = event.target.closest("a.problem");
  if (!link) return;
  event.preventDefault();
  const page = Number(link.dataset.page) || null;
  if (page) viewer.scrollPageIntoView({ pageNumber: page });
  if (link.dataset.file) {
    openSource(link.dataset.file, Number(link.dataset.line) || 1, page);
  }
});

function setState(state, lines = []) {
  if (state !== build.dataset.state && (state === "built" || state === "failed")) {
    document.body.dispatchEvent(new Event("problems-refresh"));
  }
  build.dataset.state = state;
  build.textContent = LABELS[state] ?? state;
  errors.hidden = state !== "failed";
  errorMessage.textContent = lines[0] ?? "";
  errorDetails.hidden = lines.length < 2;
  errorLines.textContent = lines.slice(1).join("\n");
}

const source = new EventSource(deck.dataset.events);
source.addEventListener("state", (event) => {
  const { state, errors: lines } = JSON.parse(event.data);
  setState(state, lines);
});
source.addEventListener("pdf", (event) => show(JSON.parse(event.data).url));
source.addEventListener("error", () => setState("disconnected"));
