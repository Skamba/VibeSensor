"""Replay the committed fuzz corpora against the live regression entry points."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import pytest
from pydantic import TypeAdapter

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.infra.processing import SignalProcessor
from vibesensor.shared.fft_analysis import compute_fft_spectrum
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.payload_types import (
    AxisPeak,
    ClientMetrics,
    IntakeStatsPayload,
    SpectraPayload,
    SpectrumSeriesPayload,
    TimeAlignmentPayload,
)
from vibesensor.vibration_strength import (
    VibrationStrengthMetrics,
    combined_spectrum_amp_g,
    compute_vibration_strength_db,
    noise_floor_amp_p20_g,
    peak_band_rms_amp_g,
    vibration_strength_db_scalar,
)


class ArtifactExpectation(TypedDict, total=False):
    kind: str
    rows: int
    peak_hz: float
    min_bins: int
    clients: list[str]


class SavedFuzzArtifact(TypedDict):
    target: str
    notes: str
    expect: ArtifactExpectation
    case: dict[str, object]


_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORPUS_DIR = _REPO_ROOT / "artifacts" / "fuzz"
_CORPUS_FILES = sorted(_CORPUS_DIR.glob("*.json"))


def _load_artifact(path: Path) -> SavedFuzzArtifact:
    return cast(SavedFuzzArtifact, json.loads(path.read_text(encoding="utf-8")))


def _json_no_nan(value: object) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def _is_sorted_desc(values: Sequence[float]) -> bool:
    return all(left >= right for left, right in zip(values, values[1:], strict=False))


def _replay_strength_artifact(
    artifact: SavedFuzzArtifact,
) -> tuple[VibrationStrengthMetrics, ArtifactExpectation]:
    case = artifact["case"]
    expect = artifact["expect"]
    axis_spectra_raw = case["axis_spectra"]
    assert isinstance(axis_spectra_raw, Sequence)
    axis_spectra = [
        [float(value) for value in axis_values]
        for axis_values in axis_spectra_raw
        if isinstance(axis_values, Sequence)
    ]
    combined = combined_spectrum_amp_g(
        axis_spectra_amp_g=axis_spectra,
        axis_count_for_mean=(
            int(case["axis_count_for_mean"])
            if isinstance(case.get("axis_count_for_mean"), int)
            else None
        ),
    )
    floor_amp = noise_floor_amp_p20_g(combined_spectrum_amp_g=combined)
    band_rms = peak_band_rms_amp_g(
        freq_hz=[
            float(case["start_hz"]) + (float(case["freq_step_hz"]) * idx)
            for idx in range(len(combined))
        ],
        combined_spectrum_amp_g=combined,
        center_idx=int(case["center_idx"]),
        bandwidth_hz=float(case["bandwidth_hz"]),
    )
    scalar_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=band_rms,
        floor_amp_g=floor_amp,
        epsilon_g=float(case["epsilon_g"]) if case.get("epsilon_g") is not None else None,
    )
    assert np.isfinite(scalar_db)
    metrics = compute_vibration_strength_db(
        freq_hz=[
            float(case["start_hz"]) + (float(case["freq_step_hz"]) * idx)
            for idx in range(len(combined))
        ],
        combined_spectrum_amp_g_values=combined,
        top_n=8,
    )
    TypeAdapter(VibrationStrengthMetrics).validate_python(metrics)
    peak_strengths = [float(peak["vibration_strength_db"]) for peak in metrics["top_peaks"]]
    assert _is_sorted_desc(peak_strengths)
    _json_no_nan(metrics)
    return metrics, expect


def _replay_fft_artifact(
    artifact: SavedFuzzArtifact,
) -> tuple[dict[str, object], ArtifactExpectation]:
    case = artifact["case"]
    expect = artifact["expect"]
    sample_rate_hz = int(case["sample_rate_hz"])
    fft_n = int(case["fft_n"])
    block = np.asarray(case["base_block"], dtype=np.float32)
    block += np.float32(float(case["dc_offset"]))
    block[int(case["spike_axis"]), int(case["spike_col"])] += np.float32(float(case["spike_value"]))
    window = np.hanning(fft_n).astype(np.float32)
    scale = float(2.0 / max(1.0, float(np.sum(window))))
    freqs = np.fft.rfftfreq(fft_n, d=1.0 / sample_rate_hz)
    valid = (freqs >= float(case["spectrum_min_hz"])) & (freqs <= float(case["spectrum_max_hz"]))
    result = compute_fft_spectrum(
        block,
        sample_rate_hz,
        fft_window=window,
        fft_scale=scale,
        freq_slice=freqs[valid].astype(np.float32),
        valid_idx=np.flatnonzero(valid),
        spike_filter_enabled=bool(case["spike_filter_enabled"]),
    )
    freq_slice = result["freq_slice"]
    combined_amp = result["combined_amp"]
    assert np.all(np.isfinite(freq_slice))
    assert np.all(np.isfinite(combined_amp))
    assert np.all(combined_amp >= 0.0)
    for axis in ("x", "y", "z"):
        TypeAdapter(list[AxisPeak]).validate_python(result["axis_peaks"][axis])
    TypeAdapter(VibrationStrengthMetrics).validate_python(result["strength_metrics"])
    serializable = {
        "freq_slice": freq_slice.tolist(),
        "combined_amp": combined_amp.tolist(),
        "axis_peaks": result["axis_peaks"],
        "strength_metrics": result["strength_metrics"],
    }
    _json_no_nan(serializable)
    return serializable, expect


def _replay_processor_artifact(
    artifact: SavedFuzzArtifact,
) -> tuple[dict[str, object], ArtifactExpectation]:
    case = artifact["case"]
    expect = artifact["expect"]
    processor = SignalProcessor(
        sample_rate_hz=int(case["sample_rate_hz"]),
        waveform_seconds=int(case["waveform_seconds"]),
        waveform_display_hz=int(case["waveform_display_hz"]),
        fft_n=int(case["fft_n"]),
        spectrum_min_hz=float(case["spectrum_min_hz"]),
        spectrum_max_hz=float(case["spectrum_max_hz"]),
        accel_scale_g_per_lsb=(
            float(case["accel_scale_g_per_lsb"])
            if case.get("accel_scale_g_per_lsb") is not None
            else None
        ),
    )
    clients = [str(client_id) for client_id in cast(list[object], case["clients"])]
    for chunk in cast(list[dict[str, object]], case["chunks"]):
        rows = np.asarray(chunk["rows"], dtype=np.float32)
        processor.ingest(
            str(chunk["client_id"]),
            rows,
            sample_rate_hz=(
                int(chunk["sample_rate_hz"])
                if isinstance(chunk.get("sample_rate_hz"), int)
                else None
            ),
            t0_us=int(chunk["t0_us"]) if isinstance(chunk.get("t0_us"), int) else None,
        )

    metrics_by_client: dict[str, ClientMetrics] = {}
    spectrum_by_client: dict[str, SpectrumSeriesPayload] = {}
    latest_xyz: dict[str, tuple[float, float, float] | None] = {}
    for client_id in clients:
        metrics = processor.compute_metrics(client_id)
        TypeAdapter(ClientMetrics).validate_python(metrics)
        metrics_by_client[client_id] = metrics
        spectrum_payload = processor.spectrum_payload(client_id)
        TypeAdapter(SpectrumSeriesPayload).validate_python(spectrum_payload)
        spectrum_by_client[client_id] = spectrum_payload
        latest_xyz[client_id] = processor.latest_sample_xyz(client_id)

    compute_all_result = processor.compute_all(clients)
    for metrics in compute_all_result.values():
        TypeAdapter(ClientMetrics).validate_python(metrics)
    multi = processor.multi_spectrum_payload(clients)
    TypeAdapter(SpectraPayload).validate_python(multi)
    time_alignment = processor.time_alignment_info(clients)
    TypeAdapter(TimeAlignmentPayload).validate_python(time_alignment)
    intake_stats = processor.intake_stats()
    TypeAdapter(IntakeStatsPayload).validate_python(intake_stats)
    fresh_clients = processor.clients_with_recent_data(clients, max_age_s=60.0)
    serializable = {
        "metrics_by_client": metrics_by_client,
        "spectrum_by_client": spectrum_by_client,
        "latest_xyz": latest_xyz,
        "compute_all_result": compute_all_result,
        "multi": multi,
        "time_alignment": time_alignment,
        "intake_stats": intake_stats,
        "fresh_clients": fresh_clients,
    }
    _json_no_nan(serializable)
    return serializable, expect


def _replay_analysis_artifact(
    artifact: SavedFuzzArtifact,
) -> tuple[AnalysisSummary, ArtifactExpectation]:
    case = artifact["case"]
    expect = artifact["expect"]
    summary = summarize_run_data(
        cast(dict[str, object], case["metadata"]),
        cast(list[dict[str, object]], case["samples"]),
        lang=cast(str | None, case.get("lang")),
        include_samples=bool(case.get("include_samples", False)),
        file_name=f"{case['metadata']['run_id']}.jsonl",
    )
    TypeAdapter(AnalysisSummary).validate_python(summary)
    _json_no_nan(summary)
    return summary, expect


def _assert_expected_outcome(artifact: SavedFuzzArtifact) -> None:
    expect = artifact["expect"]
    assert expect["kind"] == "success"
    target = artifact["target"]
    if target == "strength":
        metrics, target_expect = _replay_strength_artifact(artifact)
        assert metrics["top_peaks"]
        assert float(metrics["top_peaks"][0]["hz"]) == pytest.approx(
            float(target_expect["peak_hz"])
        )
        return
    if target == "fft":
        result, target_expect = _replay_fft_artifact(artifact)
        assert len(cast(list[object], result["freq_slice"])) >= int(target_expect["min_bins"])
        return
    if target == "processor":
        result, target_expect = _replay_processor_artifact(artifact)
        assert set(cast(dict[str, object], result["compute_all_result"])) == set(
            cast(list[str], target_expect["clients"])
        )
        return
    if target == "analysis":
        summary, target_expect = _replay_analysis_artifact(artifact)
        assert int(summary["rows"]) == int(target_expect["rows"])
        assert summary["findings"] is not None
        assert summary["run_suitability"] is not None
        return
    raise AssertionError(f"Unknown fuzz artifact target: {target}")


def test_saved_fuzz_corpus_directory_is_not_empty() -> None:
    assert _CORPUS_FILES, "expected committed fuzz corpora under artifacts/fuzz/"


@pytest.mark.parametrize("artifact_path", _CORPUS_FILES, ids=lambda path: path.stem)
def test_saved_fuzz_artifacts_replay_cleanly(artifact_path: Path) -> None:
    artifact = _load_artifact(artifact_path)
    _assert_expected_outcome(artifact)
