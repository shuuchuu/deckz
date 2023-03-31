"""Generate the code reference pages."""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

src_dir = Path("deckz")
reference_dir = Path("reference")
summary_filename = "api.md"
index_filename = "index.md"

for path in sorted(src_dir.rglob("*.py")):

    module_path = path.relative_to(src_dir.parent).with_suffix("")
    doc_path = path.relative_to(src_dir).with_suffix(".md")
    full_doc_path = Path(reference_dir, doc_path)

    parts = list(module_path.parts)
    print(parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]
        doc_path = doc_path.with_name(index_filename)
        full_doc_path = full_doc_path.with_name(index_filename)
    elif parts[-1] == "__main__":
        continue
    print(doc_path)
    nav[tuple(parts)] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        identifier = ".".join(parts)
        print("::: " + identifier, file=fd)

    mkdocs_gen_files.set_edit_path(full_doc_path, path)

with mkdocs_gen_files.open(reference_dir / summary_filename, "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
