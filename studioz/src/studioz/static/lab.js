// A lab notebook's page: the notebook rendered, or its changes since the
// last commit (`_lab_view.html`), switched without reloading the page.

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
  const url = new URL(document.getElementById("lab-view").getAttribute("hx-get"), location.href);
  if (view === "changes") url.searchParams.set("vue", "avant-apres");
  else url.searchParams.delete("vue");
  htmx.ajax("GET", url.pathname + url.search, { target: "#lab-view", swap: "outerHTML" });
}

for (const button of document.querySelectorAll(".views button")) {
  button.addEventListener("click", () => setView(button.dataset.view));
}
