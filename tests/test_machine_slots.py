from pathlib import Path
from threading import Event, Thread

from deckz.components.machine_slots import MachineSlots


def _hold_in_thread(slots: MachineSlots, holding: Event, release: Event) -> Thread:
    def run() -> None:
        with slots.hold():
            holding.set()
            release.wait(5)

    thread = Thread(target=run)
    thread.start()
    return thread


def test_hold_waits_while_every_slot_is_taken(tmp_path: Path) -> None:
    # Each `hold` opens its own descriptors: two holders in one process
    # contend like two processes would.
    slots = MachineSlots(1, tmp_path)
    first_holding, first_release = Event(), Event()
    first = _hold_in_thread(slots, first_holding, first_release)
    assert first_holding.wait(5)

    second_holding, second_release = Event(), Event()
    second = _hold_in_thread(slots, second_holding, second_release)
    assert not second_holding.wait(0.5)

    first_release.set()
    assert second_holding.wait(5)
    second_release.set()
    first.join()
    second.join()


def test_hold_lets_count_holders_through_at_once(tmp_path: Path) -> None:
    slots = MachineSlots(2, tmp_path)
    holdings = [Event(), Event()]
    release = Event()
    threads = [_hold_in_thread(slots, holding, release) for holding in holdings]

    assert all(holding.wait(5) for holding in holdings)
    release.set()
    for thread in threads:
        thread.join()


def test_hold_stops_waiting_when_cancelled(tmp_path: Path) -> None:
    slots = MachineSlots(1, tmp_path)
    holding, release = Event(), Event()
    thread = _hold_in_thread(slots, holding, release)
    assert holding.wait(5)

    with slots.hold(cancelled=lambda: True) as held:
        assert not held
    release.set()
    thread.join()


def test_hold_compiles_without_the_limit_when_slots_cannot_be_opened(
    tmp_path: Path,
) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("", encoding="utf8")
    # A directory under a regular file can't be created.
    slots = MachineSlots(1, blocked / "slots")

    with slots.hold() as held:
        assert held
