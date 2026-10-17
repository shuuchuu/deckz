// MathJax's configuration, read when its script loads after this one: the
// math markdown-it left as `\(…\)`, `\[…\]` or `\begin{…}` (`studioz.
// notebooks`), only in what has `tex2jax_process` (Markdown cells), never
// in code or outputs. No menu, nothing loaded besides its own file: the
// page may run studioz's scripts only.
window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: false,
    processEnvironments: true,
  },
  options: { enableMenu: false },
  svg: { fontCache: "global" },
};
