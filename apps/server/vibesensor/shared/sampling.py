"""Iterator sampling utilities."""

from __future__ import annotations

from collections.abc import Iterator


def bounded_sample[SampleT](
    samples: Iterator[SampleT],
    *,
    max_items: int,
    total_hint: int = 0,
) -> tuple[list[SampleT], int, int]:
    """Down-sample *samples* to at most *max_items*.

    When *total_hint* is available the stride is computed upfront so
    that we never over-collect and re-halve.

    Returns
    -------
    tuple[list[SampleT], int, int]
        ``(kept_samples, total_count, final_stride)`` where
        *kept_samples* is the down-sampled list, *total_count* is the
        number of items consumed from the iterator, and *final_stride*
        is the stride factor that was applied.

    Raises
    ------
    ValueError
        If *max_items* is not a positive integer.

    """
    if max_items <= 0:
        raise ValueError(f"bounded_sample: max_items must be >= 1, got {max_items}")
    stride: int = max(1, -(-total_hint // max_items)) if total_hint > max_items else 1
    kept: list[SampleT] = []
    total = 0
    for sample in samples:
        total += 1
        if (total - 1) % stride != 0:
            continue
        kept.append(sample)
        if len(kept) > max_items:
            kept = kept[::2]
            stride *= 2
    # Final trim: the halving loop can leave len(kept) == max_items + 1
    # in edge cases (e.g. max_items=1).  Guarantee the contract.
    if len(kept) > max_items:
        kept = kept[:max_items]
    return kept, total, stride
