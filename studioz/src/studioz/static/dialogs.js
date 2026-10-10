// A button opening a dialog with its content from studioz (`data-dialog`, the
// dialog; `data-url`, what to POST; `data-values`, JSON; `data-include`, a
// form whose fields to send too). The request belongs to the dialog, not to
// the button: the panels holding these buttons reload themselves, and htmx
// drops the answer to a request whose element left the page meanwhile.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-dialog]");
  if (!button) return;
  const dialog = document.querySelector(button.dataset.dialog);
  const form = button.dataset.include && document.querySelector(button.dataset.include);
  button.disabled = true;
  try {
    await htmx.ajax("POST", button.dataset.url, {
      source: form || dialog,
      target: dialog,
      swap: "innerHTML",
      values: JSON.parse(button.dataset.values || "{}"),
    });
  } finally {
    button.disabled = false;
  }
  if (dialog.childElementCount) dialog.showModal();
});
