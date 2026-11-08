// The Maintenance page: a click on a row of the dashboard (`_maintenance.html`)
// opens the file deckz names for it (`opens`) in the editor beside it.
import { SourceEditor } from "/static/editor.js";

const page = document.getElementById("maintenance-page");
const notice = document.getElementById("notice");
let noticeTimer = null;

const editor = new SourceEditor(document.getElementById("editor-pane"), page.dataset.files, (text) => {
  notice.textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => (notice.textContent = ""), 6000);
});

let current = null;

page.addEventListener("click", (event) => {
  const link = event.target.closest("a");
  // Another link (a deck's page) is followed.
  if (link && !link.matches("a.opens")) return;
  const row = event.target.closest("#maintenance tr[data-file]");
  const file = link?.dataset.file ?? row?.dataset.file;
  if (!file) return;
  event.preventDefault();
  current?.classList.remove("current");
  current = row;
  current?.classList.add("current");
  editor.open(file, 1);
});
