import sys
from pathlib import Path
from subprocess import run
from typing import Any

from pygit2 import init_repository
from pytest import CaptureFixture, MonkeyPatch, fixture, raises

from deckz.analyzing.content_checks import course_notes_code
from deckz.cli import main
from deckz.code_runner import examples, matches, programs
from deckz.configuring.settings import (
    CourseNotesCodeSettings,
    CourseNotesSettings,
    GlobalPaths,
    GlobalSettings,
)
from deckz.course_notes_code import dataset_links


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


def test_an_example_ignoring_the_alarm_is_killed_after_its_grace(
    repo: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("deckz.course_notes_code._GRACE", 1)
    chapter = """# C

```python
import signal, time
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
time.sleep(60)
```

```pycon
>>> 1
1
```
"""

    problems = _check(repo, chapter, timeout=1)

    assert len(problems) == 1
    assert problems[0].startswith("course-notes/topic/chapter.md:3: still running")
    assert "after 1 s, stopped: mark the block" in problems[0]


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


def test_a_module_written_into_an_imported_package_is_found(repo: Path) -> None:
    # The import system caches the package's directory listing: the module
    # written right after its first import must still be found.
    chapter = """# C

```python
# paquet/__init__.py
```

```python
# paquet/a.py
A = 1
```

```pycon
>>> from paquet import a
```

```python
# paquet/b.py
B = 2
```

```pycon
>>> from paquet import b
>>> a.A + b.B
3
```
"""
    assert _check(repo, chapter) == []


def test_a_data_file_block_is_written_without_its_name_line(repo: Path) -> None:
    chapter = """# C

```text
# notes.txt
12
15
```

```pycon
>>> open("notes.txt").read().splitlines()
['12', '15']
```
"""
    assert _check(repo, chapter) == []


def test_programs_speak_english(repo: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    chapter = """# C

```pycon
>>> import os
>>> os.environ["LC_ALL"]
'C.UTF-8'
```
"""
    assert _check(repo, chapter) == []


def test_console_commands_run_when_their_programs_are_allowed(repo: Path) -> None:
    chapter = """# C

```python
# hello.py
print("hello")
```

```console
$ uv run python hello.py
hello
$ python -c "import sys; sys.exit(3)"
$ echo $?
3
$ X=1 python -c 'print(1 + 1)' \\
>   | cat
2
```

```console
$ git push
Everything up-to-date
```
"""
    allowed = ("python", "echo", "cat")

    problems = _check(repo, chapter, commands=allowed)

    # `git push` isn't allowed: its block isn't run, the first one is.
    assert problems == []
    shell = [e for e in examples(chapter, frozenset(allowed)) if e.mode == "shell"]
    assert [example.line for example in shell] == [9, 11, 12, 14]


def test_a_console_output_that_differs_or_a_silent_failure_is_reported(
    repo: Path,
) -> None:
    chapter = """# C

```console
$ python -c "print(2)"
3
$ python -c "import sys; sys.exit(2)"
```
"""
    problems = _check(repo, chapter, commands=("python",))

    assert len(problems) == 2
    assert problems[0].startswith(
        "course-notes/topic/chapter.md:4: the output shown isn't what it prints"
    )
    assert problems[1].startswith(
        "course-notes/topic/chapter.md:6: fails (exit status 2) and the chapter "
        "shows nothing"
    )


def test_a_command_killed_by_a_signal_has_a_shell_status(repo: Path) -> None:
    chapter = """# C

```console
$ python -c "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
$ echo $?
143
```
"""
    assert _check(repo, chapter, commands=("python", "echo")) == []


def test_programs_names_each_chained_program() -> None:
    assert programs("A=1 uv run ruff check . && echo $? | cat") == [
        "ruff",
        "echo",
        "cat",
    ]
    assert programs("uv run --with x python") == ["uv"]
    assert programs("echo $(rm -rf x)") is None


def test_requirements_take_the_place_of_with(repo: Path) -> None:
    # An interpreter recording the packages it's given, then running the runner.
    log = repo / "with.log"
    wrapper = repo / "wrapper.py"
    wrapper.write_text(
        "import runpy, sys\n"
        "args = sys.argv[1:]\n"
        "packages = []\n"
        "while args[0] == '--with':\n"
        "    packages.append(args[1])\n"
        "    args = args[2:]\n"
        f"open({str(log)!r}, 'w').write(' '.join(packages))\n"
        "sys.argv = args\n"
        "runpy.run_path(args[0], run_name='__main__')\n",
        encoding="utf8",
    )
    python = (sys.executable, str(wrapper), "{with}")
    chapter = "# C\n\n```pycon\n>>> 1\n1\n```\n"

    problems = _check(
        repo,
        chapter,
        python=python,
        requirements={"topic/**": ("flask >= 3",), "topic/*": ("lxml",)},
    )

    assert problems == []
    assert log.read_text(encoding="utf8") == "flask >= 3 lxml"
    problems = _check(repo, chapter, requirements={"topic/**": ("flask",)})
    assert 'course_notes.code.python has no "{with}"' in problems[0]


def test_patterns_matching_no_chapter_are_reported(repo: Path) -> None:
    problems = _check(
        repo,
        "# C\n",
        setup={"gone/**": ("data.md",)},
        requirements={"topic/**": ("flask",), "moved/*": ("lxml",)},
    )

    assert problems == [
        "deckz.yml: course_notes.code.setup's pattern gone/** matches no chapter: "
        "fix it, or remove it",
        "deckz.yml: course_notes.code.requirements's pattern moved/* matches no "
        "chapter: fix it, or remove it",
    ]


_URL = "https://github.com/acme/datasets"


def _git(cwd: Path, *args: str) -> None:
    run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@fixture
def sibling(tmp_path: Path) -> Path:
    # A repository with a directory of its own around it, for `../datasets`.
    init_repository(str(tmp_path / "repo"))
    return tmp_path / "repo"


@fixture
def datasets(sibling: Path) -> Path:
    # A data sets clone, pushed to its upstream, next to the repository.
    upstream = sibling.parent / "upstream.git"
    _git(sibling.parent, "init", "--bare", "--initial-branch=main", str(upstream))
    clone = sibling.parent / "datasets"
    _git(sibling.parent, "clone", str(upstream), str(clone))
    _write(clone / "titanic" / "train.csv", "survived\n1\n")
    _write(clone / "ames" / "train.csv", "price\n2\n")
    _write(clone / "ames" / "test.csv", "price\n3\n")
    _write(clone / "words" / "fr.txt", "bonjour\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-m", "data")
    _git(clone, "push", "origin", "HEAD:main")
    _git(clone, "branch", "--set-upstream-to=origin/main")
    return clone


def _with_datasets(repo: Path, chapter: str, **code: Any) -> list[str]:
    from deckz.configuring.settings import DatasetsSettings

    datasets = DatasetsSettings(url=_URL, path="{git_dir}/../datasets")
    return _check(repo, chapter, datasets=datasets, **code)


def test_linked_data_sets_are_in_the_working_directory(
    sibling: Path, datasets: Path
) -> None:
    chapter = f"""# C

The [passengers]({_URL}/raw/refs/heads/main/titanic/train.csv), the houses
(<{_URL}/tree/main/ames>) and the words:

```console
$ wget -q {_URL}/raw/refs/heads/main/ghsparse.sh -O /tmp/ghsparse.sh \\
    && bash /tmp/ghsparse.sh words
```

```pycon
>>> open("train.csv").read()
'survived\\n1\\n'
>>> open("ames/test.csv").read()
'price\\n3\\n'
>>> open("words/fr.txt").read()
'bonjour\\n'
```
"""
    assert _with_datasets(sibling, chapter) == []


def test_data_sets_not_published_are_reported(sibling: Path, datasets: Path) -> None:
    _write(datasets / "words" / "en.txt", "hello\n")
    _write(datasets / "ames" / "test.csv", "price\n4\n")
    _git(datasets, "commit", "-am", "new prices")
    chapter = f"""# C

[en]({_URL}/raw/main/words/en.txt), [test]({_URL}/blob/main/ames/test.csv),
[gone]({_URL}/raw/main/gone.csv).

```pycon
>>> 1
1
```
"""
    rel = "course-notes/topic/chapter.md"

    assert _with_datasets(sibling, chapter) == [
        f"{rel}: links to words/en.txt, which isn't committed in ../datasets: "
        "commit it and push it, the chapter's link leads nowhere until then",
        f"{rel}: links to ames/test.csv, which isn't pushed from ../datasets: "
        "`git -C ../datasets push`, the chapter's link leads nowhere until then",
        f"{rel}: links to gone.csv, which isn't in ../datasets: pull it (`git -C "
        "../datasets pull`), or add it there and push it",
    ]


def test_two_data_files_of_the_same_name_are_reported(
    sibling: Path, datasets: Path
) -> None:
    chapter = f"""# C

<{_URL}/raw/main/titanic/train.csv>, <{_URL}/raw/main/ames/train.csv>

```pycon
>>> 1
1
```
"""
    problems = _with_datasets(sibling, chapter)

    assert problems == [
        "course-notes/topic/chapter.md: links to titanic/train.csv and "
        "ames/train.csv, both downloaded as train.csv: link their directories "
        "instead, and read them there"
    ]


def test_a_missing_datasets_clone_says_how_to_clone_it(sibling: Path) -> None:
    chapter = f"# C\n\n<{_URL}/raw/main/a.csv>\n\n```pycon\n>>> 1\n1\n```\n"

    problems = _with_datasets(sibling, chapter)

    assert problems == [
        f"course-notes/topic/chapter.md: links to {_URL}, whose clone ../datasets "
        f"doesn't exist: `git clone {_URL} ../datasets`, or set "
        "course_notes.code.datasets.path in deckz.yml"
    ]


def test_a_big_data_file_is_linked_and_writing_over_it_reported(
    sibling: Path, datasets: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr("deckz.course_notes_code._LINKED_SIZE", 0)
    chapter = f"""# C

<{_URL}/raw/main/words/fr.txt>

```python
open("fr.txt", "w").write("salut")
```
"""
    problems = _with_datasets(sibling, chapter)

    assert (datasets / "words" / "fr.txt").read_text(encoding="utf8") == "salut"
    assert problems == [
        "course-notes/topic/chapter.md: writes over words/fr.txt, linked from "
        "../datasets (rather than copied, being big): write to another file, and "
        "restore it (`git -C ../datasets restore words/fr.txt`)"
    ]


def test_dataset_links_reads_each_form_once() -> None:
    text = (
        f"[a]({_URL}/raw/refs/heads/main/a/b.csv) <{_URL}/tree/main/c>. "
        f"{_URL}/raw/main/a/b.csv, and `bash /tmp/ghsparse.sh d` without the "
        "script's address, not a sparse clone."
    )

    assert dataset_links(_URL, text) == ["a/b.csv", "c"]


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
