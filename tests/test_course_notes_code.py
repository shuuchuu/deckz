from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import CaptureFixture, fixture, raises

from deckz.analyzing.content_checks import course_notes_code
from deckz.cli import main
from deckz.code_runner import examples, matches
from deckz.configuring.settings import (
    CourseNotesCodeSettings,
    CourseNotesSettings,
    GlobalPaths,
    GlobalSettings,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def _settings(git_dir: Path, **code: Any) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        course_notes=CourseNotesSettings(code=CourseNotesCodeSettings(**code)),
    )


@fixture
def repo(tmp_path: Path) -> Path:
    init_repository(str(tmp_path))
    return tmp_path


def _check(repo: Path, chapter: str, **code: Any) -> list[str]:
    _write(repo / "course-notes" / "topic" / "chapter.md", chapter)
    return course_notes_code(_settings(repo, **code))


def test_matching_sessions_and_blocks_pass(repo: Path) -> None:
    chapter = """# Chapter

```pycon
>>> x = 2
>>> x + 1
3
>>> for i in range(2):
...     print(i)
...
0
1
```

```python
print(x * 10)
```

```text
20
```
"""
    assert _check(repo, chapter) == []


def test_a_wrong_output_is_reported_with_its_line(repo: Path) -> None:
    problems = _check(repo, "# C\n\nText.\n\n```pycon\n>>> 1 + 1\n3\n```\n")

    assert len(problems) == 1
    assert problems[0].startswith("course-notes/topic/chapter.md:6: the output shown")
    assert "| 2" in problems[0]


def test_a_block_printing_what_isnt_shown_is_reported(repo: Path) -> None:
    problems = _check(repo, "# C\n\n```python\nprint('hello')\n```\n")

    assert len(problems) == 1
    assert "prints what the chapter doesn't show" in problems[0]


def test_trailing_spaces_and_ellipsis_dont_count(repo: Path) -> None:
    chapter = """# C

```pycon
>>> print("a   \\nb")
a
b
>>> object()
<object object at 0x...>
```
"""
    assert _check(repo, chapter) == []


def test_a_shown_error_matches_on_its_last_line(repo: Path) -> None:
    chapter = """# C

```pycon
>>> int("x")
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
ValueError: invalid literal for int() with base 10: 'x'
>>> 2x = 1
  File "<stdin>", line 1
    2x = 1
    ^
SyntaxError: invalid decimal literal
```
"""
    assert _check(repo, chapter) == []


def test_an_unexpected_error_is_reported_and_its_cascade_counted(repo: Path) -> None:
    chapter = """# C

```python
import nowhere_to_be_found
data = nowhere_to_be_found.load()
```

```pycon
>>> data
1
>>> len(data)
1
```
"""
    problems = _check(repo, chapter)

    assert len(problems) == 2
    assert "raises ModuleNotFoundError" in problems[0]
    assert "2 more example(s) raise NameError" in problems[1]


def test_fence_classes_opt_out(repo: Path) -> None:
    chapter = """# C

```{.python .no-run}
input("Name? ")
```

```{.pycon .output-varies}
>>> import time
>>> time.time()
12.5
```
"""
    assert _check(repo, chapter) == []


def test_output_varies_still_reports_an_error(repo: Path) -> None:
    problems = _check(repo, "# C\n\n```{.pycon .output-varies}\n>>> 1 / 0\n```\n")

    assert len(problems) == 1
    assert "raises ZeroDivisionError" in problems[0]


def test_a_file_block_is_written_then_imported(repo: Path) -> None:
    chapter = """# C

```python
# greeting.py
def hello():
    return "hello"
```

```python
# main.py
import greeting
print(greeting.hello(), __name__)
```

```text
hello __main__
```

```pycon
>>> import greeting
>>> greeting.hello()
'hello'
```
"""
    assert _check(repo, chapter) == []


def test_setup_chapters_and_files_run_first(repo: Path) -> None:
    _write(repo / "course-notes" / "data.md", "# D\n\n```python\nrows = [1, 2]\n```\n")
    _write(repo / "data" / "numbers.txt", "7\n")
    chapter = """# C

```pycon
>>> len(rows)
2
>>> open("numbers.txt").read()
'7\\n'
```
"""
    problems = _check(
        repo,
        chapter,
        setup={"topic/**": ("course-notes/data.md", "data/numbers.txt")},
    )

    assert problems == []


def test_a_missing_setup_path_names_the_fix(repo: Path) -> None:
    problems = _check(
        repo, "# C\n\n```pycon\n>>> 1\n1\n```\n", setup={"topic/*": ("gone.md",)}
    )

    assert problems == [
        "course-notes/topic/chapter.md: course_notes.code.setup names gone.md, "
        "which doesn't exist: fix the path in deckz.yml"
    ]


def test_an_example_running_too_long_is_stopped(repo: Path) -> None:
    chapter = (
        "# C\n\n```python\nwhile True:\n    pass\n```\n\n```pycon\n>>> 1\n1\n```\n"
    )

    problems = _check(repo, chapter, timeout=1)

    assert len(problems) == 1
    assert "still running after 1 s, stopped: mark the block" in problems[0]


def test_an_interpreter_that_cant_start_names_the_setting(repo: Path) -> None:
    problems = _check(
        repo, "# C\n\n```pycon\n>>> 1\n1\n```\n", python=("no-such-python-here",)
    )

    assert len(problems) == 1
    assert "course_notes.code.python" in problems[0]


def test_examples_skip_other_languages() -> None:
    text = "```sh\nls\n```\n\n```pycon\n>>> 1\n1\n```\n\n```c\nint x;\n```\n"

    found = list(examples(text))

    assert [example.source for example in found] == ["1\n"]


def test_matches_compares_an_error_by_its_last_line() -> None:
    assert matches("Traceback ...\nKeyError: 'a'\n", "", "KeyError: 'a'")
    assert not matches("", "", "KeyError: 'a'")


def test_check_names_files_and_is_opt_in(
    repo: Path, monkeypatch: Any, capsys: CaptureFixture[str]
) -> None:
    import appdirs

    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(repo))
    monkeypatch.chdir(repo)
    _write(repo / "course-notes" / "good.md", "# G\n\n```pycon\n>>> 1\n1\n```\n")
    _write(repo / "course-notes" / "bad.md", "# B\n\n```pycon\n>>> 1\n2\n```\n")

    main(("check",))  # Opt-in: not run, so nothing fails.
    assert "course-notes-code" not in capsys.readouterr().out

    main(("check", "course-notes-code", "--file", "course-notes/good.md"))
    assert capsys.readouterr().out == ""

    with raises(SystemExit):
        main(("check", "course-notes-code", "--file", "course-notes/bad.md"))
    assert "course-notes/bad.md:4: the output shown" in capsys.readouterr().out
