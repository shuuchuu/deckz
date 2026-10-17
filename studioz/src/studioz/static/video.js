// A video's page: its render in a <video> (`_video_player.html`, reloaded
// after a render), or its render as of the last commit beside the current
// one, played together; and its scene's module in the editor beside them.
import { SourceEditor } from "/static/editor.js";

const page = document.getElementById("video-page");
const editor = new SourceEditor(
  document.getElementById("editor-pane"),
  page.dataset.files,
  (text) => (document.getElementById("notice").textContent = text),
);

let opened = false;

// The player's URL, for the view chosen.
function playerUrl(view) {
  const url = new URL(document.getElementById("video-player").getAttribute("hx-get"), location.href);
  if (view === "changes") url.searchParams.set("vue", "avant-apres");
  else url.searchParams.delete("vue");
  return url;
}

function setView(view) {
  for (const button of document.querySelectorAll(".views button")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  for (const link of [location, ...document.querySelectorAll(".langs a")]) {
    const url = new URL(link.href);
    if (view === "changes") url.searchParams.set("vue", "avant-apres");
    else url.searchParams.delete("vue");
    if (link === location) history.replaceState(null, "", url);
    else link.href = url;
  }
  const url = playerUrl(view);
  htmx.ajax("GET", url.pathname + url.search, { target: "#video-player", swap: "outerHTML" });
}

for (const button of document.querySelectorAll(".views button")) {
  button.addEventListener("click", () => setView(button.dataset.view));
}

// Before and after play, pause and seek together (media events don't
// bubble: caught on their way down).
let following = false;
const ACTIONS = {
  play: (other) => other.play(),
  pause: (other) => other.pause(),
  seeked: (other, video) => {
    if (Math.abs(other.currentTime - video.currentTime) > 0.1) other.currentTime = video.currentTime;
  },
};
for (const [type, action] of Object.entries(ACTIONS)) {
  document.addEventListener(type, (event) => {
    const video = event.target;
    const sides = video.closest?.(".video-sides");
    if (!sides || following) return;
    following = true;
    for (const other of sides.querySelectorAll("video")) if (other !== video) action(other, video);
    following = false;
  }, true);
}

document.body.addEventListener("htmx:afterSettle", (event) => {
  const player = document.getElementById("video-player");
  if (!player || !(player === event.target || player.contains(event.target))) return;
  if (!player.dataset.module) return;
  // The scene's module, once: then it's the person's editor.
  if (!opened) {
    opened = true;
    editor.open(player.dataset.module, Number(player.dataset.line));
  } else {
    editor.refresh();
  }
});
