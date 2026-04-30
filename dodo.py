DOIT_CONFIG = {"default_tasks": ["check"]}


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


def task_build_and_push_docker_image():
    return {
        "actions": [
            "docker build -t shuuchuu/deckz-ci .",
            "docker push shuuchuu/deckz-ci:latest",
        ],
    }
