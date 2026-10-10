from pathlib import Path

DOIT_CONFIG = {
    "backend": "json",
    "default_tasks": ["check"],
    "dep_file": ".doit.json",
    "verbosity": 2,
}


def task_check():
    return {
        "actions": [
            "uv run ruff check src/deckz tests studioz/src studioz/tests",
            "uv run ruff format --check src/deckz tests studioz/src studioz/tests",
            "uv run ty check src/deckz tests studioz/src studioz/tests",
        ],
    }


def task_test():
    return {
        "actions": [
            "uv run pytest -n auto",
        ],
    }


def task_vendor():
    """Copy the JavaScript studioz serves, pinned in studioz/package.json."""

    modules = Path("studioz/node_modules")
    vendor = Path("studioz/src/studioz/static/vendor")
    pdfjs = modules / "pdfjs-dist"
    files = {
        modules / "htmx.org/dist/htmx.min.js": vendor / "htmx.min.js",
        pdfjs / "LICENSE": vendor / "pdfjs/LICENSE",
        pdfjs / "build/pdf.min.mjs": vendor / "pdfjs/pdf.min.mjs",
        pdfjs / "build/pdf.worker.min.mjs": vendor / "pdfjs/pdf.worker.min.mjs",
        pdfjs / "web/pdf_viewer.mjs": vendor / "pdfjs/web/pdf_viewer.mjs",
        pdfjs / "web/pdf_viewer.css": vendor / "pdfjs/web/pdf_viewer.css",
    }

    # CodeMirror is dozens of small modules: one bundle of what
    # studioz/codemirror.mjs exports. They're all MIT, by the same author.
    files[modules / "@codemirror/view/LICENSE"] = vendor / "codemirror/LICENSE"
    codemirror = vendor / "codemirror/codemirror.min.mjs"

    def copy() -> None:
        from shutil import copyfile, copytree, rmtree

        rmtree(vendor, ignore_errors=True)
        for source, target in files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            copyfile(source, target)
        # What pdf_viewer.css references.
        copytree(pdfjs / "web/images", vendor / "pdfjs/web/images")

    return {
        "actions": [
            "npm ci --prefix studioz --no-audit --no-fund",
            copy,
            "studioz/node_modules/.bin/esbuild studioz/codemirror.mjs --bundle"
            f" --format=esm --minify --log-level=warning --outfile={codemirror}",
        ],
        "file_dep": [
            "studioz/package.json",
            "studioz/package-lock.json",
            "studioz/codemirror.mjs",
        ],
        "targets": [str(target) for target in [*files.values(), codemirror]],
    }


def task_install_hooks():
    import os

    actions = ["git config core.hooksPath .githooks"]
    if os.name == "posix":
        actions.append("chmod +x .githooks/*")
    return {
        "actions": actions,
    }


def task_build_and_push_docker_image():
    return {
        "actions": [
            "docker build -t shuuchuu/deckz-ci .",
            "docker push shuuchuu/deckz-ci:latest",
        ],
    }
