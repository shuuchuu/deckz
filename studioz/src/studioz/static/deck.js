// The deck page: its handout in pdf.js, reloaded at the same place each time
// the workspace's `deckz run --watch` finishes a build (server-sent events).
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
window.addEventListener("resize", () => {
  if (viewer.pagesCount) viewer.currentScaleValue = "page-width";
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
    } catch (error) {
      console.error("studioz: could not show", url, error);
    }
  }
  loading = false;
}

function setState(state, lines = []) {
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
