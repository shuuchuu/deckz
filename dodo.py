DOIT_CONFIG = {
    "backend": "json",
    "default_tasks": ["check"],
    "dep_file": ".doit.json",
    "verbosity": 2,
}


def task_check():
    return {
        "actions": [
            "uv run ruff check src/deckz tests",
            "uv run ruff format --check src/deckz tests",
            "uv run ty check src/deckz tests",
        ],
    }


def task_test():
    return {
        "actions": [
            "uv run pytest",
        ],
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
