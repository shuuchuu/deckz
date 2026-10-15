// The palette, as VS Code's: Ctrl+P (or the title bar's search) finds a deck
// to open; typing ">" first, Ctrl+Maj+P or F1 finds a command instead. The
// commands are the page's hidden buttons (`_commands.html`): running one
// clicks it, so the page's own handlers do the work.
import { showAgent } from "/static/layout.js";

const palette = document.getElementById("palette");
const input = document.getElementById("palette-input");
const list = document.getElementById("palette-list");
const COMMANDS = ">";
const SHOWN = 60;

// Lower case, without accents: "é" is found by typing "e".
const plain = (text) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

// How well `text` matches `query`: a substring best (the earlier the
// better), then the query's letters in order; null for no match.
function score(text, query) {
  if (!query) return 0;
  const at = text.indexOf(query);
  if (at >= 0) return at;
  let from = 0;
  let gaps = 0;
  for (const letter of query) {
    const found = text.indexOf(letter, from);
    if (found < 0) return null;
    gaps += found - from;
    from = found + 1;
  }
  return 1000 + gaps;
}

function decks() {
  const root = document.querySelector(".tree-root")?.textContent ?? "";
  return [...document.querySelectorAll(".tree li.deck-item a")].map((link) => {
    const path = link.closest("li").dataset.path;
    return {
      label: path.startsWith(root) ? path.slice(root.length) : path,
      detail: "formation",
      run: () => { location.href = link.href; },
    };
  });
}

function commands() {
  return [...document.querySelectorAll("#commands > button")].map((button) => ({
    label: button.textContent.trim(),
    detail: button.dataset.keys ?? "",
    run: () => {
      if (button.dataset.click) {
        document.querySelector(button.dataset.click)?.click();
      } else if (button.dataset.focus) {
        showAgent(true);
        document.querySelector(button.dataset.focus)?.focus();
      } else {
        button.click();
      }
    },
  }));
}

let items = [];
let selected = 0;

function update() {
  const text = input.value;
  const commanding = text.startsWith(COMMANDS);
  const query = plain((commanding ? text.slice(1) : text).trim());
  items = (commanding ? commands() : decks())
    .map((item) => ({ ...item, score: score(plain(item.label), query) }))
    .filter((item) => item.score !== null)
    .sort((a, b) => a.score - b.score)
    .slice(0, SHOWN);
  selected = 0;
  list.replaceChildren(
    ...items.map((item, index) => {
      const row = document.createElement("li");
      row.role = "option";
      row.dataset.index = String(index);
      const label = document.createElement("span");
      label.className = "palette-label";
      label.textContent = item.label;
      const detail = document.createElement("span");
      detail.className = "palette-detail";
      detail.textContent = item.detail;
      row.append(label, detail);
      return row;
    }),
  );
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = commanding ? "Aucune commande." : "Aucune formation. (« > » pour les commandes)";
    list.append(empty);
  }
  select(0);
}

function select(index) {
  if (!items.length) return;
  selected = (index + items.length) % items.length;
  for (const row of list.querySelectorAll("[role=option]")) {
    const current = Number(row.dataset.index) === selected;
    row.setAttribute("aria-selected", String(current));
    if (current) row.scrollIntoView({ block: "nearest" });
  }
}

function run(index) {
  const item = items[index];
  if (!item) return;
  palette.close();
  item.run();
}

export function openPalette(prefix = "") {
  input.value = prefix;
  if (!palette.open) palette.showModal();
  update();
  input.focus();
}

input.addEventListener("input", update);
input.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") select(selected + 1);
  else if (event.key === "ArrowUp") select(selected - 1);
  else if (event.key === "Enter") run(selected);
  else return;
  event.preventDefault();
});
list.addEventListener("click", (event) => {
  const row = event.target.closest("[role=option]");
  if (row) run(Number(row.dataset.index));
});
// A click outside the box (on the backdrop) closes it.
palette.addEventListener("click", (event) => {
  if (event.target === palette) palette.close();
});

document.addEventListener("keydown", (event) => {
  const ctrl = event.ctrlKey || event.metaKey;
  if (event.key === "F1" || (ctrl && event.shiftKey && event.key.toLowerCase() === "p")) {
    event.preventDefault();
    openPalette(COMMANDS);
  } else if (ctrl && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "p") {
    event.preventDefault();
    openPalette();
  }
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-palette]")) openPalette();
});
