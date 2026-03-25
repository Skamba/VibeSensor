"""Sliding deduplication window for client DATA sequence tracking."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["DedupWindow"]

_DEFAULT_WINDOW_SIZE = 128


@dataclass(slots=True)
class DedupWindow:
    """Track a bounded window of recently seen sequence numbers."""

    _seen_seqs: set[int] = field(default_factory=set)
    _seen_seqs_max: int = -1

    def clear(self) -> None:
        """Reset the dedup window to its initial empty state."""

        self._seen_seqs.clear()
        self._seen_seqs_max = -1

    def contains(self, seq: int) -> bool:
        """Return ``True`` when *seq* is still within the dedup window."""

        return seq in self._seen_seqs

    def record(self, seq: int) -> None:
        """Record *seq* and advance the tracked maximum sequence value."""

        self._seen_seqs.add(seq)
        self._seen_seqs_max = max(self._seen_seqs_max, seq)

    def prune(self, window_size: int) -> None:
        """Discard old entries so the dedup window stays bounded."""

        if len(self._seen_seqs) > window_size:
            cutoff = self._seen_seqs_max - window_size + 1
            self._seen_seqs = {seen for seen in self._seen_seqs if seen >= cutoff}

    def track(self, seq: int, *, window_size: int = _DEFAULT_WINDOW_SIZE) -> bool:
        """Return ``True`` for duplicates; otherwise record *seq* and prune."""

        if self.contains(seq):
            return True
        self.record(seq)
        self.prune(window_size)
        return False
