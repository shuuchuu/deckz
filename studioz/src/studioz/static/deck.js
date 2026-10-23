// The deck page: its handout in pdf.js, reloaded at the same place each time
// the workspace's `deckz run --watch` finishes a build (server-sent events).
// A click on a page opens its frame's source in the editor beside it. The
// "Avant/après" view shows the frames changed since the last commit
// (`_comparison.html`), each page drawn by pdf.js once in view.
import { SourceEditor } from "/static/editor.js";
import { showPanel } from "/static/layout.js";
import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

globalThis.pdfjsLib = pdfjsLib;
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
const { EventBus, LinkTarget, PDFLinkService, PDFViewer } = await import(
  "/static/vendor/pdfjs/web/pdf_viewer.mjs"
);

const LABELS = {
  building: "Construction…",
  built: "À jour",
  failed: "Échec de la construction",
  stopped: "Construction arrêtée",
  disconnected: "Connexion perdue, nouvelle tentative…",
};

// The panel's Construction tab says it in a sentence.
const SUMMARIES = {
  building: "La formation se construit avec vos dernières modifications…",
  built: "La formation est construite et à jour.",
  failed: "La dernière construction a échoué ; le PDF affiché est celui d'avant.",
  stopped: "La construction s'est arrêtée.",
  disconnected: "La connexion à la construction est perdue ; nouvelle tentative…",
};

const deck = document.getElementById("deck");
const container = document.getElementById("viewer-container");
const build = document.getElementById("build");
const errors = document.getElementById("errors");
const errorMessage = document.getElementById("error-message");
const summary = document.getElementById("build-summary");
const failedDot = document.getElementById("build-dot");
const errorLines = document.getElementById("error-lines");
const waiting = document.getElementById("waiting");
const pageNumber = document.getElementById("page-number");
const notice = document.getElementById("notice");

const eventBus = new EventBus();
// A link out of the deck opens a new tab (pdf.js adds `rel="noopener"`): the
// default follows it in studioz's own, the page and its editor gone.
const linkService = new PDFLinkService({ eventBus, externalLinkTarget: LinkTarget.BLANK });
const viewer = new PDFViewer({ container, eventBus, linkService });
linkService.setViewer(viewer);

function showPageNumber() {
  pageNumber.textContent = `p. ${viewer.currentPageNumber} / ${viewer.pagesCount}`;
}

eventBus.on("pagesinit", () => {
  viewer.currentScaleValue = "page-width";
});
eventBus.on("pagechanging", () => {
  showPageNumber();
  showSlide();
});
// The window's size, the editor opening or closing, a sidebar shown, hidden
// or dragged (once it rests: redrawing every page at each step is slow). The
// page clicked to open the editor stays in view.
let clicked = null;
let resized = null;
new ResizeObserver(() => {
  clearTimeout(resized);
  resized = setTimeout(() => {
    if (!viewer.pagesCount) return;
    viewer.currentScaleValue = "page-width";
    if (clicked) viewer.scrollPageIntoView({ pageNumber: clicked });
    clicked = null;
  }, 80);
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

// The slide in view, which a message to the agent names (`agent.js`): none on a
// page without a frame (title, outline) nor in the before/after view.
function showSlide() {
  const frame = deck.dataset.view === "changes" || !viewer.pagesCount
    ? null : frames.get(viewer.currentPageNumber);
  const { page, title, file, line } = frame ?? {};
  const slide = frame ? JSON.stringify({ page, title, file, line }) : "";
  if (slide === document.body.dataset.slide) return;
  document.body.dataset.slide = slide;
  document.body.dispatchEvent(new Event("slide-in-view"));
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
      showSlide();
      editor.refresh();
      if (deck.dataset.view === "changes") refreshComparison();
    } catch (error) {
      console.error("studioz: could not show", url, error);
    }
  }
  loading = false;
}

// The Problems and Changes panels' links (`_problems.html`, `_changes.html`).
document.addEventListener("click", (event) => {
  const link = event.target.closest("a.problem, a.change");
  // A lab notebook's problem links to its page.
  if (!link || !(link.dataset.file || link.dataset.page)) return;
  event.preventDefault();
  const page = Number(link.dataset.page) || null;
  if (page) viewer.scrollPageIntoView({ pageNumber: page });
  if (link.dataset.file) {
    openSource(link.dataset.file, Number(link.dataset.line) || 1, page);
  }
});

function setState(state, lines = []) {
  const previous = build.dataset.state;
  if (state !== previous && (state === "built" || state === "failed")) {
    document.body.dispatchEvent(new Event("workspace-changed"));
  }
  build.dataset.state = state;
  build.textContent = LABELS[state] ?? state;
  summary.textContent = SUMMARIES[state] ?? state;
  errors.hidden = failedDot.hidden = state !== "failed";
  // deckz names the file and line first: a link to them, as in Problems.
  const located = /^([^\s:]+):(\d+):/.exec(lines[0] ?? "");
  if (located) {
    const link = Object.assign(document.createElement("a"), {
      href: "#",
      className: "problem",
      textContent: lines[0],
    });
    Object.assign(link.dataset, { file: located[1], line: located[2] });
    errorMessage.replaceChildren(link);
  } else {
    errorMessage.textContent = lines[0] ?? "";
  }
  errorLines.hidden = lines.length < 2;
  errorLines.textContent = lines.slice(1).join("\n");
  // A build failing shows why, as VS Code shows a task's output.
  if (state === "failed" && previous !== "failed") showPanel(true, "construction");
}

const source = new EventSource(deck.dataset.events);
source.addEventListener("state", (event) => {
  const { state, errors: lines } = JSON.parse(event.data);
  setState(state, lines);
});
source.addEventListener("pdf", (event) => show(JSON.parse(event.data).url));
source.addEventListener("error", () => setState("disconnected"));

// The before/after view.
function refreshComparison() {
  document.body.dispatchEvent(new Event("comparison-refresh"));
}

function setView(view) {
  deck.dataset.view = view;
  for (const button of document.querySelectorAll(".views button")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  for (const link of [location, ...document.querySelectorAll(".langs a")]) {
    const url = new URL(link.href);
    if (view === "changes") url.searchParams.set("vue", "modifications");
    else url.searchParams.delete("vue");
    if (link === location) history.replaceState(null, "", url);
    else link.href = url;
  }
  if (view === "changes") refreshComparison();
  showSlide();
}

for (const button of document.querySelectorAll(".views button")) {
  button.addEventListener("click", () => setView(button.dataset.view));
}

// The PDFs the view draws pages of, the last used last.
const documents = new Map();

function pdfDocument(url) {
  let loaded = documents.get(url);
  documents.delete(url);
  loaded ??= pdfjsLib.getDocument({ url }).promise;
  documents.set(url, loaded);
  if (documents.size > 4) {
    const [oldest, old] = documents.entries().next().value;
    documents.delete(oldest);
    old.then((pdf) => pdf.destroy(), () => {});
  }
  return loaded;
}

async function drawPage(canvas) {
  try {
    const pdf = await pdfDocument(canvas.dataset.src);
    const page = await pdf.getPage(Number(canvas.dataset.page));
    const scale =
      (canvas.clientWidth * devicePixelRatio) / page.getViewport({ scale: 1 }).width;
    const viewport = page.getViewport({ scale });
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    await page.render({ canvas, viewport }).promise;
  } catch (error) {
    console.error("studioz: could not draw", canvas.dataset.src, error);
  }
}

const inView = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      inView.unobserve(entry.target);
      drawPage(entry.target);
    }
  },
  { rootMargin: "300px" },
);

document.body.addEventListener("htmx:afterSettle", () => {
  for (const canvas of document.querySelectorAll("#comparison canvas:not([data-drawn])")) {
    canvas.dataset.drawn = "";
    inView.observe(canvas);
  }
});

// A frame as it is now opens its source.
document.addEventListener("click", (event) => {
  const canvas = event.target.closest("#comparison canvas[data-file]");
  if (canvas) openSource(canvas.dataset.file, Number(canvas.dataset.line), null);
});
