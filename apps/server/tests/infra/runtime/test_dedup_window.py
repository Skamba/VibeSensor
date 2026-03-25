from __future__ import annotations

from vibesensor.infra.runtime.dedup_window import DedupWindow


def test_dedup_window_contains_recorded_sequence() -> None:
    window = DedupWindow()

    assert window.contains(7) is False

    window.record(7)

    assert window.contains(7) is True


def test_dedup_window_prunes_entries_older_than_window_cutoff() -> None:
    window = DedupWindow()
    for seq in (10, 11, 12, 13):
        window.record(seq)

    window.prune(3)

    assert window.contains(10) is False
    assert window.contains(11) is True
    assert window.contains(12) is True
    assert window.contains(13) is True


def test_dedup_window_clear_resets_running_max_state() -> None:
    window = DedupWindow()
    window.record(100)

    window.clear()
    window.record(1)
    window.prune(1)

    assert window.contains(100) is False
    assert window.contains(1) is True
