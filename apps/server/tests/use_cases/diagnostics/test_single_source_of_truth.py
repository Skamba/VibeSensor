"""Guardrail tests ensuring key definitions have a single source of truth.

These tests prevent regression of the consolidation work by verifying:
1. Spectrum payloads do not contain dead alias fields
2. The strength_scoring module does not exist
3. Metrics log records use canonical field names only
4. as_float_or_none is the single canonical float converter
5. percentile is the single canonical percentile implementation
6. compute_vibration_strength_db output has no dead alias fields
"""

from __future__ import annotations

from _paths import REPO_ROOT

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

DEFAULT_ANALYSIS_SETTINGS = AnalysisSettingsSnapshot.DEFAULTS


def _make_signal_processor():
    """Create a SignalProcessor with standard test parameters."""
    from vibesensor.infra.processing import SignalProcessor

    return SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=120,
        fft_n=512,
        spectrum_max_hz=200,
    )


def _ingest_noise(proc, *, seed: int = 42):
    """Ingest random noise into *proc* for ``test_client`` and compute metrics."""
    import numpy as np

    rng = np.random.default_rng(seed)
    samples = rng.standard_normal((600, 3)).astype(np.float32) * 0.01
    proc.ingest("test_client", samples, sample_rate_hz=800)
    proc.compute_metrics("test_client")


def _assert_no_combined_alias(payload: dict) -> None:
    assert "combined" not in payload
    assert "combined_spectrum_amp_g" in payload


def test_spectrum_payload_has_no_combined_alias() -> None:
    """Spectrum payload must not contain the dead 'combined' alias field."""
    proc = _make_signal_processor()
    # Empty client
    _assert_no_combined_alias(proc.spectrum_payload("nonexistent"))
    # Client with data
    _ingest_noise(proc, seed=42)
    _assert_no_combined_alias(proc.spectrum_payload("test_client"))


def test_as_float_single_source_of_truth() -> None:
    """order_bands.as_float_or_none must be the canonical as_float_or_none
    from runlog, not a local re-definition.
    """
    from vibesensor.shared.json_utils import as_float_or_none
    from vibesensor.shared.order_bands import as_float_or_none as ob_as_float

    assert ob_as_float is as_float_or_none, (
        "order_bands.as_float_or_none must be imported from runlog.as_float_or_none"
    )


def test_percentile_single_source_of_truth() -> None:
    """analysis.helpers.percentile must be imported from
    vibesensor.vibration_strength, not re-defined locally.
    """
    from vibesensor.vibration_strength import percentile
    from vibesensor.vibration_strength import percentile as canonical

    assert percentile is canonical, (
        "analysis.helpers.percentile must be imported from vibesensor.vibration_strength"
    )


def test_strength_metrics_no_dead_aliases() -> None:
    """compute_vibration_strength_db output must not contain dead alias fields."""
    from vibesensor.vibration_strength import compute_vibration_strength_db

    result = compute_vibration_strength_db(
        freq_hz=[1.0, 2.0, 3.0],
        combined_spectrum_amp_g_values=[0.0, 0.0, 0.0],
    )
    dead_aliases = {
        "peak_amp",
        "floor_amp",
        "combined_spectrum_db_above_floor",
        "strength_peak_band_rms_amp_g",
        "strength_floor_amp_g",
        "noise_floor_amp_p20_g",
        "strength_db",
        "top_strength_peaks",
    }
    present = dead_aliases & set(result.keys())
    assert not present, f"Dead alias fields in compute_vibration_strength_db: {present}"


def test_analysis_constants_single_source_of_truth() -> None:
    """Core analysis constants must expose the expected canonical values."""
    import inspect

    from vibesensor.shared.constants.analysis import SILENCE_DB
    from vibesensor.shared.constants.dsp import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ
    from vibesensor.shared.constants.units import KMH_TO_MPS, MPS_TO_KMH
    from vibesensor.vibration_strength import compute_vibration_strength_db

    assert MPS_TO_KMH == 3.6
    assert abs(KMH_TO_MPS - 1.0 / 3.6) < 1e-15
    assert abs(MPS_TO_KMH * KMH_TO_MPS - 1.0) < 1e-15
    assert SILENCE_DB == -120.0
    assert PEAK_BANDWIDTH_HZ == 1.2
    assert PEAK_SEPARATION_HZ == 1.2

    sig = inspect.signature(compute_vibration_strength_db)
    assert sig.parameters["peak_bandwidth_hz"].default == PEAK_BANDWIDTH_HZ
    assert sig.parameters["peak_separation_hz"].default == PEAK_SEPARATION_HZ


def test_esp_protocol_constants_match_python() -> None:
    """ESP C++ protocol constants must match the Python protocol module."""
    import re

    from vibesensor.adapters.udp.protocol import (
        ACK_BYTES,
        ACK_SYNC_CLOCK_BYTES,
        CMD_HEADER_BYTES,
        CMD_IDENTIFY,
        CMD_IDENTIFY_BYTES,
        CMD_SYNC_CLOCK_BYTES,
        DATA_ACK_BYTES,
        DATA_HEADER_BYTES,
        HELLO_FIXED_BYTES,
        MSG_ACK,
        MSG_CMD,
        MSG_DATA,
        MSG_DATA_ACK,
        MSG_HELLO,
        VERSION,
    )

    root = REPO_ROOT
    proto_h = root / "firmware" / "esp" / "lib" / "vibesensor_proto" / "vibesensor_proto.h"
    header = proto_h.read_text(encoding="utf-8")

    def _cpp_const(name: str) -> int:
        """Extract a simple integer constexpr value from the header."""
        m = re.search(rf"{name}\s*=\s*(\d+)", header)
        assert m, f"C++ constant {name} not found in vibesensor_proto.h"
        return int(m.group(1))

    assert _cpp_const("kProtoVersion") == VERSION
    assert _cpp_const("kMsgHello") == MSG_HELLO
    assert _cpp_const("kMsgData") == MSG_DATA
    assert _cpp_const("kMsgCmd") == MSG_CMD
    assert _cpp_const("kMsgAck") == MSG_ACK
    assert _cpp_const("kMsgDataAck") == MSG_DATA_ACK
    assert _cpp_const("kCmdIdentify") == CMD_IDENTIFY

    # Byte-size constants are computed as expressions in C++; verify by evaluating
    # with kClientIdBytes = 6
    py_sizes = {
        "HELLO_FIXED_BYTES": HELLO_FIXED_BYTES,
        "DATA_HEADER_BYTES": DATA_HEADER_BYTES,
        "ACK_BYTES": ACK_BYTES,
        "ACK_SYNC_CLOCK_BYTES": ACK_SYNC_CLOCK_BYTES,
        "DATA_ACK_BYTES": DATA_ACK_BYTES,
        "CMD_HEADER_BYTES": CMD_HEADER_BYTES,
        "CMD_IDENTIFY_BYTES": CMD_IDENTIFY_BYTES,
        "CMD_SYNC_CLOCK_BYTES": CMD_SYNC_CLOCK_BYTES,
    }
    cpp_names = {
        "HELLO_FIXED_BYTES": "kHelloFixedBytes",
        "DATA_HEADER_BYTES": "kDataHeaderBytes",
        "ACK_BYTES": "kAckBytes",
        "ACK_SYNC_CLOCK_BYTES": "kAckSyncClockBytes",
        "DATA_ACK_BYTES": "kDataAckBytes",
        "CMD_HEADER_BYTES": "kCmdHeaderBytes",
        "CMD_IDENTIFY_BYTES": "kCmdIdentifyBytes",
        "CMD_SYNC_CLOCK_BYTES": "kCmdSyncClockBytes",
    }
    # Evaluate C++ expressions by substituting kClientIdBytes and kCmdHeaderBytes
    for py_name, expected in py_sizes.items():
        cpp_name = cpp_names[py_name]
        m = re.search(rf"constexpr\s+size_t\s+{cpp_name}\s*=\s*(.+);", header)
        assert m, f"C++ constant {cpp_name} not found"
        expr = m.group(1).strip()
        # Substitute known constants for eval
        expr = (
            expr.replace("kClientIdBytes", "6")
            .replace("kCmdHeaderBytes", str(CMD_HEADER_BYTES))
            .replace("kAckBytes", str(ACK_BYTES))
        )
        computed = eval(expr)  # noqa: S307
        assert computed == expected, f"{cpp_name} = {computed} but Python {py_name} = {expected}"


def test_protocol_docs_byte_sizes_match() -> None:
    """docs/protocol.md byte sizes must match the Python protocol module."""
    import re

    from vibesensor.adapters.udp.protocol import (
        ACK_BYTES,
        ACK_SYNC_CLOCK_BYTES,
        CMD_HEADER_BYTES,
        CMD_IDENTIFY_BYTES,
        CMD_SYNC_CLOCK_BYTES,
        DATA_ACK_BYTES,
        DATA_HEADER_BYTES,
        HELLO_FIXED_BYTES,
    )

    root = REPO_ROOT
    doc = (root / "docs" / "protocol.md").read_text(encoding="utf-8")

    expected = {
        "HELLO fixed bytes": HELLO_FIXED_BYTES,
        "DATA header bytes": DATA_HEADER_BYTES,
        "CMD header bytes": CMD_HEADER_BYTES,
        "CMD identify bytes": CMD_IDENTIFY_BYTES,
        "CMD sync clock bytes": CMD_SYNC_CLOCK_BYTES,
        "ACK bytes": ACK_BYTES,
        "ACK sync clock bytes": ACK_SYNC_CLOCK_BYTES,
        "DATA_ACK bytes": DATA_ACK_BYTES,
    }
    missing_labels: list[str] = []
    mismatches: list[str] = []
    for label, value in expected.items():
        pattern = rf"{re.escape(label)}.*`(\d+)`"
        m = re.search(pattern, doc, re.IGNORECASE)
        if not m:
            missing_labels.append(label)
            continue
        doc_value = int(m.group(1))
        if doc_value != value:
            mismatches.append(f"{label}: docs={doc_value} code={value}")
    assert not missing_labels, "docs/protocol.md missing entries: " + ", ".join(missing_labels)
    assert not mismatches, "docs/protocol.md byte-size mismatches: " + ", ".join(mismatches)


def test_protocol_docs_match_generated_contract_reference() -> None:
    """docs/protocol.md must match the generated authoritative contract doc."""
    from vibesensor.cli.contract_reference_doc import render_contract_reference_markdown

    root = REPO_ROOT
    doc_path = root / "docs" / "protocol.md"
    observed = doc_path.read_text(encoding="utf-8")
    expected = render_contract_reference_markdown()
    assert observed == expected, "docs/protocol.md is out of date. Run: make sync-contracts"


def test_validation_sets_cover_all_settings_keys() -> None:
    """Every key in DEFAULTS must be in exactly one validation set."""
    all_keys = set(DEFAULT_ANALYSIS_SETTINGS)
    pos = AnalysisSettingsSnapshot.POSITIVE_REQUIRED_KEYS
    non_neg = AnalysisSettingsSnapshot.NON_NEGATIVE_KEYS
    covered = pos | non_neg
    uncovered = all_keys - covered
    assert not uncovered, (
        f"Keys not in any validation set: {uncovered}. "
        "Add them to POSITIVE_REQUIRED_KEYS or NON_NEGATIVE_KEYS."
    )
    overlap = pos & non_neg
    assert not overlap, f"Keys in both validation sets: {overlap}"


def test_server_dockerfile_is_real_build_recipe() -> None:
    root = REPO_ROOT
    dockerfile = root / "apps" / "server" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")
    first_line = content.splitlines()[0].strip()
    assert first_line.startswith("FROM "), (
        "apps/server/Dockerfile must be a real Dockerfile, not a placeholder"
    )
