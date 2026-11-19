from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from pytest import raises

from deckz.run_cache import in_run, in_shared_run, run_resource, shared, shared_run
from deckz.utils import load_yaml

calls: list[str] = []


@shared
def _square(value: int) -> int:
    calls.append(f"square {value}")
    return value * value


@shared
def _failing() -> None:
    calls.append("failing")
    msg = "broken"
    raise ValueError(msg)


@shared
def _sum_of_squares(limit: int) -> int:
    # A shared step built from others: each computed once in a run.
    return sum(_square(value) for value in range(limit))


def test_a_shared_function_computes_on_every_call_outside_a_run() -> None:
    calls.clear()

    assert _square(3) == 9
    assert _square(3) == 9
    assert calls == ["square 3", "square 3"]
    assert not in_shared_run()


def test_a_shared_function_computes_once_per_arguments_in_a_run() -> None:
    calls.clear()

    with shared_run():
        assert in_shared_run()
        assert _sum_of_squares(3) == 5
        assert _square(2) == 4
        assert _square(4) == 16
        with shared_run():  # A nested run is the same run.
            assert _square(1) == 1

    assert calls == ["square 0", "square 1", "square 2", "square 4"]
    _square(1)
    assert calls[-1] == "square 1"


def test_a_shared_failure_raises_again_without_computing_again() -> None:
    calls.clear()

    with shared_run():
        for _ in range(2):
            with raises(ValueError, match="broken"):
                _failing()

    assert calls == ["failing"]


def test_threads_given_the_run_share_its_results() -> None:
    calls.clear()

    with shared_run(), ThreadPoolExecutor(4) as pool:
        results = list(pool.map(in_run(_square), [5] * 8))

    assert results == [25] * 8
    assert calls == ["square 5"]


def test_a_run_resource_opens_once_and_closes_with_the_run() -> None:
    events: list[str] = []

    @contextmanager
    def resource() -> Generator[str]:
        events.append("open")
        try:
            yield "pool"
        finally:
            events.append("close")

    with shared_run():
        assert run_resource("test", resource) == "pool"
        assert run_resource("test", resource) == "pool"
        assert events == ["open"]
    assert events == ["open", "close"]

    with raises(RuntimeError, match="shared_run"):
        run_resource("test", resource)


def test_load_yaml_reads_an_edited_file_anew(tmp_path: Path) -> None:
    import os

    path = tmp_path / "deckz.yml"
    path.write_text("a: 1\n", encoding="utf-8")
    first = load_yaml(path)
    first["a"] = 2  # The caller's copy: the cache keeps its own.

    assert load_yaml(path) == {"a": 1}

    path.write_text("a: 10\n", encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert load_yaml(path) == {"a": 10}
