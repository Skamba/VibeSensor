"""Behavior of client ring buffers and the processor's snapshot → compute → commit cycle."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from vibesensor.infra.processing import MAX_CLIENT_SAMPLE_RATE_HZ, ClientBuffer, SignalProcessor
from vibesensor.infra.processing.models import MetricsComputationResult, MetricsSnapshot


def _processor(**overrides: object) -> SignalProcessor:
    kwargs: dict[str, object] = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        "fft_n": 128,
        "spectrum_max_hz": 100.0,
    }
    kwargs.update(overrides)
    return SignalProcessor(**kwargs)  # type: ignore[arg-type]


def _noise(n: int, *, seed: int = 0, scale: float = 1.0) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal((n, 3)) * scale).astype(np.float32)


def _buffer(capacity: int = 4) -> ClientBuffer:
    return ClientBuffer(data=np.zeros((3, capacity), dtype=np.float32), capacity=capacity)


def _result(buf: ClientBuffer, **overrides: object) -> MetricsComputationResult:
    fields: dict[str, object] = {
        "client_id": "c",
        "sample_rate_hz": 200,
        "ingest_generation": buf.ingest_generation,
        "metrics": {"combined": {"vib_mag_rms": 1.0, "vib_mag_p2p": 2.0, "peaks": []}},
        "spectrum_by_axis": {},
        "strength_metrics": {},
        "has_fft_data": False,
        "duration_s": 0.01,
        "buffer_epoch": buf.buffer_epoch,
        "reset_generation": buf.reset_generation,
    }
    fields.update(overrides)
    return MetricsComputationResult(**fields)  # type: ignore[arg-type]


def _intercept_compute(
    proc: SignalProcessor,
    monkeypatch: pytest.MonkeyPatch,
    during_compute: Callable[[], None] | None = None,
) -> list[MetricsSnapshot]:
    """Record compute snapshots and optionally mutate the processor mid-compute."""
    snapshots: list[MetricsSnapshot] = []
    real_compute = proc._metrics.compute

    def _compute(snapshot: MetricsSnapshot) -> MetricsComputationResult:
        snapshots.append(snapshot)
        result = real_compute(snapshot)
        if during_compute is not None:
            during_compute()
        return result

    monkeypatch.setattr(proc._metrics, "compute", _compute)
    return snapshots


# -- ClientBuffer ------------------------------------------------------------


def test_append_writes_in_order_and_wraps_with_saturating_count() -> None:
    buf = _buffer(capacity=4)
    first = np.arange(9, dtype=np.float32).reshape(3, 3)
    buf.append(first, t0_us=1_000_000)
    assert (buf.write_idx, buf.count, buf.ingest_generation) == (3, 3, 1)
    np.testing.assert_array_equal(buf.copy_latest(3), first.T)

    second = np.arange(100, 109, dtype=np.float32).reshape(3, 3)
    buf.append(second, t0_us=None)
    assert (buf.write_idx, buf.count) == (2, 4)
    np.testing.assert_array_equal(buf.copy_latest(4), np.vstack([first[-1:], second]).T)
    assert buf.last_t0_us == 1_000_000
    assert buf.samples_since_t0 == 6


def test_append_keeps_newest_t0_anchor_and_clamps_sample_counter() -> None:
    buf = _buffer(capacity=8)
    buf.append(np.ones((4, 3), dtype=np.float32), t0_us=1_000_000)
    buf.append(np.ones((2, 3), dtype=np.float32), t0_us=900_000)
    assert buf.last_t0_us == 1_000_000
    assert buf.samples_since_t0 == 6

    buf.samples_since_t0 = (2**28) - 1
    buf.append(np.ones((2, 3), dtype=np.float32), t0_us=None)
    assert buf.samples_since_t0 == 2**28


@pytest.mark.parametrize(
    ("new_capacity", "expected_capacity", "expected_count"),
    [(10, 10, 10), (20, 20, 10), (5, 5, 5), (0, 1, 1), (-10, 1, 1)],
    ids=["same", "grow", "shrink", "zero", "negative"],
)
def test_resize_keeps_newest_samples(
    new_capacity: int,
    expected_capacity: int,
    expected_count: int,
) -> None:
    buf = _buffer(capacity=10)
    samples = np.arange(30, dtype=np.float32).reshape(10, 3)
    buf.append(samples, t0_us=None)

    buf.resize(new_capacity)

    assert buf.capacity == expected_capacity
    assert buf.count == expected_count
    np.testing.assert_array_equal(buf.copy_latest(expected_count), samples[-expected_count:].T)


def test_reset_clears_samples_and_bumps_generations() -> None:
    buf = _buffer(capacity=8)
    buf.append(np.ones((8, 3), dtype=np.float32), t0_us=5_000_000)
    buf.commit_metrics(_result(buf))
    buf.cached_spectrum_payload = {"combined_spectrum_amp_g": [], "strength_metrics": {}}  # type: ignore[typeddict-item]
    reset_generation = buf.reset_generation
    ingest_generation = buf.ingest_generation

    buf.reset()

    assert (buf.count, buf.write_idx, buf.last_t0_us, buf.samples_since_t0) == (0, 0, 0, 0)
    assert buf.reset_generation == reset_generation + 1
    assert buf.ingest_generation == ingest_generation + 1
    assert (buf.compute_generation, buf.compute_sample_rate_hz) == (-1, 0)
    assert buf.latest_metrics == {}
    assert buf.cached_spectrum_payload is None
    np.testing.assert_array_equal(buf.data, np.zeros_like(buf.data))


@pytest.mark.parametrize(
    "stale_field",
    ["buffer_epoch", "reset_generation", "ingest_generation"],
)
def test_commit_rejects_results_from_replaced_reset_or_older_buffer_state(
    stale_field: str,
) -> None:
    buf = _buffer()
    buf.append(np.ones((4, 3), dtype=np.float32), t0_us=None)
    buf.buffer_epoch = 3
    buf.reset_generation = 2
    buf.compute_generation = buf.ingest_generation
    stale_value = getattr(buf, stale_field) - 1

    assert buf.commit_metrics(_result(buf, **{stale_field: stale_value})) is False
    assert buf.latest_metrics == {}
    assert buf.commit_metrics(_result(buf)) is True
    assert buf.latest_metrics["combined"]["vib_mag_rms"] == 1.0


def test_set_sample_rate_clamps_and_optionally_resizes(caplog: pytest.LogCaptureFixture) -> None:
    buf = _buffer(capacity=4)
    buf.set_sample_rate(100, resize_to_seconds=None)
    assert (buf.sample_rate_hz, buf.capacity) == (100, 4)

    with caplog.at_level("WARNING"):
        buf.set_sample_rate(250_000, resize_to_seconds=2)
    assert buf.sample_rate_hz == MAX_CLIENT_SAMPLE_RATE_HZ
    assert buf.capacity == MAX_CLIENT_SAMPLE_RATE_HZ * 2
    assert "Clamped client sample_rate_hz from 250000" in caplog.text


def test_repr_is_compact() -> None:
    buf = _buffer(capacity=1024)
    assert repr(buf) == (
        "ClientBuffer(capacity=1024, count=0, write_idx=0, sr=0Hz, igen=0, cgen=-1)"
    )


# -- SignalProcessor ingest --------------------------------------------------


def test_oversized_ingest_keeps_newest_samples_and_shifts_t0(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proc = _processor(sample_rate_hz=4, waveform_seconds=1, fft_n=4)
    samples = np.arange(18, dtype=np.float32).reshape(6, 3)

    with caplog.at_level("WARNING"):
        proc.ingest("c", samples, sample_rate_hz=4, t0_us=1_000_000)

    assert "exceeds buffer capacity 4" in caplog.text
    assert "discarding 2 oldest samples" in caplog.text
    assert proc.buffer_overflow_drops() == 2
    assert proc.intake_stats()["total_ingested_samples"] == 4
    assert proc.latest_sample_xyz("c") == (15.0, 16.0, 17.0)
    proc.compute_metrics("c")
    time_range = proc.latest_analysis_time_range("c")
    assert time_range is not None
    assert time_range.start_s == pytest.approx(1.5)
    assert time_range.end_s == pytest.approx(2.5)
    assert time_range.synced is True


# -- SignalProcessor compute -------------------------------------------------


def test_compute_reuses_metrics_until_new_samples_or_rate_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _processor()
    snapshots = _intercept_compute(proc, monkeypatch)
    proc.ingest("c", _noise(256), sample_rate_hz=200)

    first = proc.compute_metrics("c", sample_rate_hz=200)
    assert proc.compute_metrics("c", sample_rate_hz=200) is first
    assert len(snapshots) == 1

    proc.compute_metrics("c", sample_rate_hz=400)
    assert [s.sample_rate_hz for s in snapshots] == [200, 400]

    proc.ingest("c", _noise(10, seed=1))
    proc.compute_metrics("c")
    assert len(snapshots) == 3
    assert proc.intake_stats()["total_compute_calls"] == 3


def test_compute_clamps_excessive_sample_rate_override(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _processor()
    snapshots = _intercept_compute(proc, monkeypatch)
    proc.ingest("c", np.ones((256, 3), dtype=np.float32), sample_rate_hz=200)

    proc.compute_metrics("c", sample_rate_hz=250_000)

    assert snapshots[0].sample_rate_hz == MAX_CLIENT_SAMPLE_RATE_HZ
    assert proc.latest_sample_rate_hz("c") == MAX_CLIENT_SAMPLE_RATE_HZ


@pytest.mark.parametrize(
    ("ingested", "compute_rate_hz", "expected_time", "expected_fft"),
    [
        pytest.param(400, None, 400, 256, id="time-window-covers-fft"),
        pytest.param(50, None, 50, None, id="too-few-samples-for-fft"),
        pytest.param(400, 100, 200, 256, id="fft-longer-than-time-window"),
    ],
)
def test_compute_snapshot_window_sizes(
    monkeypatch: pytest.MonkeyPatch,
    ingested: int,
    compute_rate_hz: int | None,
    expected_time: int,
    expected_fft: int | None,
) -> None:
    proc = _processor(sample_rate_hz=200, waveform_seconds=2, fft_n=256)
    snapshots = _intercept_compute(proc, monkeypatch)
    proc.ingest("c", _noise(ingested), sample_rate_hz=200)

    proc.compute_metrics("c", sample_rate_hz=compute_rate_hz)

    snapshot = snapshots[0]
    assert snapshot.time_window.shape == (3, expected_time)
    if expected_fft is None:
        assert snapshot.fft_block is None
    else:
        assert snapshot.fft_block is not None
        assert snapshot.fft_block.shape == (3, expected_fft)
        assert np.shares_memory(snapshot.time_window, snapshot.fft_block)


def test_short_time_window_is_a_view_of_the_fft_block(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _processor(sample_rate_hz=8, waveform_seconds=1, fft_n=4)
    snapshots = _intercept_compute(proc, monkeypatch)
    proc.ingest("c", np.arange(12, dtype=np.float32).reshape(4, 3), sample_rate_hz=8)

    proc.compute_metrics("c", sample_rate_hz=2)

    snapshot = snapshots[0]
    assert snapshot.fft_block is not None
    assert snapshot.time_window.shape == (3, 2)
    assert snapshot.fft_block.shape == (3, 4)
    np.testing.assert_array_equal(snapshot.time_window, snapshot.fft_block[:, -2:])


def test_result_computed_before_flush_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _processor()
    proc.ingest("c", _noise(256), sample_rate_hz=200)
    _intercept_compute(proc, monkeypatch, during_compute=lambda: proc.flush_client_buffer("c"))

    proc.compute_metrics("c")

    assert proc.latest_metrics("c") == {}
    assert proc.latest_sample_xyz("c") is None


def test_result_computed_before_evict_and_reconnect_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _processor()
    proc.ingest("c", _noise(256), sample_rate_hz=200)

    def _evict_and_reconnect() -> None:
        proc.evict_clients(set())
        proc.ingest("c", _noise(256, seed=1, scale=10.0), sample_rate_hz=200)

    _intercept_compute(proc, monkeypatch, during_compute=_evict_and_reconnect)
    proc.compute_metrics("c")
    assert proc.latest_metrics("c") == {}

    monkeypatch.undo()
    fresh = proc.compute_metrics("c")
    assert proc.latest_metrics("c") is fresh
    assert fresh["x"]["rms"] > 5.0


def test_older_result_does_not_overwrite_newer_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _processor()
    proc.ingest("c", _noise(256), sample_rate_hz=200)

    def _ingest_and_compute_newer() -> None:
        monkeypatch.undo()
        proc.ingest("c", _noise(256, seed=1, scale=10.0))
        proc.compute_metrics("c")

    _intercept_compute(proc, monkeypatch, during_compute=_ingest_and_compute_newer)
    stale = proc.compute_metrics("c")

    latest = proc.latest_metrics("c")
    assert latest is not stale
    assert latest["x"]["rms"] > 5.0


def test_compute_all_skips_failing_client(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    proc = _processor()
    proc.ingest("bad", _noise(256), sample_rate_hz=200)
    proc.ingest("good", _noise(256, seed=1), sample_rate_hz=200)
    real_compute = proc._metrics.compute

    def _compute(snapshot: MetricsSnapshot) -> MetricsComputationResult:
        if snapshot.client_id == "bad":
            raise ValueError("boom")
        return real_compute(snapshot)

    monkeypatch.setattr(proc._metrics, "compute", _compute)
    with caplog.at_level("WARNING"):
        result = proc.compute_all(["bad", "good", "missing"])

    assert set(result) == {"good", "missing"}
    assert result["missing"] == {}
    assert "compute_metrics failed for bad" in caplog.text
    assert proc.intake_stats()["last_compute_all_duration_s"] > 0
