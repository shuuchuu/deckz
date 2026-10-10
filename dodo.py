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

    def copy() -> None:
        from shutil import copyfile

        modules = Path("studioz/node_modules")
        vendor = Path("studioz/src/studioz/static/vendor")
        vendor.mkdir(parents=True, exist_ok=True)
        copyfile(modules / "htmx.org/dist/htmx.min.js", vendor / "htmx.min.js")

    return {
        "actions": ["npm ci --prefix studioz --no-audit --no-fund", copy],
        "file_dep": ["studioz/package.json", "studioz/package-lock.json"],
        "targets": ["studioz/src/studioz/static/vendor/htmx.min.js"],
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
