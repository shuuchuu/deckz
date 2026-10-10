// What studioz's editor uses of CodeMirror, bundled by `uv run doit vendor`
// into src/studioz/static/vendor/codemirror/codemirror.min.mjs.
export { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
export {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
export { markdown } from "@codemirror/lang-markdown";
export { yaml } from "@codemirror/lang-yaml";
export {
  bracketMatching,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
export { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
export { Compartment, EditorSelection, EditorState } from "@codemirror/state";
export {
  Decoration,
  drawSelection,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  MatchDecorator,
  ViewPlugin,
} from "@codemirror/view";
export { classHighlighter } from "@lezer/highlight";
