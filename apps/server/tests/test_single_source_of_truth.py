"""Guardrail tests ensuring key definitions have a single source of truth.

These tests prevent regression of the consolidation work by verifying:
1. DEFAULT_DIAGNOSTIC_SETTINGS is the same object as DEFAULT_ANALYSIS_SETTINGS
2. Spectrum payloads do not contain dead alias fields
3. The legacy strength_scoring module is removed
4. Metrics log records use canonical field names only
5. as_float_or_none is the single canonical float converter
6. percentile is the single canonical percentile implementation
7. compute_vibration_strength_db output has no dead alias fields
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from vibesensor.analysis_settings import DEFAULT_ANALYSIS_SETTINGS
from vibesensor.diagnostics_shared import DEFAULT_DIAGNOSTIC_SETTINGS


def test_diagnostic_settings_is_analysis_settings() -> None:
    """DEFAULT_DIAGNOSTIC_SETTINGS must be the same object as DEFAULT_ANALYSIS_SETTINGS."""
    assert DEFAULT_DIAGNOSTIC_SETTINGS is DEFAULT_ANALYSIS_SETTINGS


def test_analysis_settings_keys_match() -> None:
    """Both default dicts have identical keys and values."""
    assert set(DEFAULT_DIAGNOSTIC_SETTINGS.keys()) == set(DEFAULT_ANALYSIS_SETTINGS.keys())
    for key in DEFAULT_ANALYSIS_SETTINGS:
        assert DEFAULT_DIAGNOSTIC_SETTINGS[key] == DEFAULT_ANALYSIS_SETTINGS[key]


def test_strength_scoring_module_removed() -> None:
    """The legacy strength_scoring.py wrapper should no longer exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("vibesensor.strength_scoring")


def test_spectrum_payload_has_no_combined_alias() -> None:
    """Spectrum payload must not contain the dead 'combined' alias field."""
    import numpy as np

    from vibesensor.processing import SignalProcessor

    proc = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=120,
        fft_n=512,
        spectrum_max_hz=200,
    )
    # Empty client
    payload = proc.spectrum_payload("nonexistent")
    assert "combined" not in payload
    assert "combined_spectrum_amp_g" in payload

    # Client with data
    samples = np.random.randn(600, 3).astype(np.float32) * 0.01
    proc.ingest("test_client", samples, sample_rate_hz=800)
    proc.compute_metrics("test_client")
    payload = proc.spectrum_payload("test_client")
    assert "combined" not in payload
    assert "combined_spectrum_amp_g" in payload


def test_selected_payload_has_no_combined_alias() -> None:
    """Selected payload spectrum must not contain the dead 'combined' alias."""
    import numpy as np

    from vibesensor.processing import SignalProcessor

    proc = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=120,
        fft_n=512,
        spectrum_max_hz=200,
    )
    samples = np.random.randn(600, 3).astype(np.float32) * 0.01
    proc.ingest("test_client", samples, sample_rate_hz=800)
    proc.compute_metrics("test_client")
    payload = proc.selected_payload("test_client")
    assert "combined" not in payload["spectrum"]
    assert "combined_spectrum_amp_g" in payload["spectrum"]


def test_metrics_log_no_legacy_field_names() -> None:
    """New metrics log records must not contain legacy field aliases."""
    from vibesensor.runlog import default_units

    units = default_units()
    legacy_fields = {
        "accel_magnitude_rms_g",
        "accel_magnitude_p2p_g",
        "dominant_peak_amp_g",
        "noise_floor_amp",
        "vib_mag_rms_g",
        "vib_mag_p2p_g",
        "noise_floor_amp_p20_g",
        "strength_floor_amp_g",
        "strength_peak_band_rms_amp_g",
        "strength_db",
    }
    present = legacy_fields & set(units.keys())
    assert not present, f"Legacy fields still in default_units: {present}"
    assert "vibration_strength_db" in units, "vibration_strength_db missing from default_units"


def test_as_float_single_source_of_truth() -> None:
    """diagnostics_shared._as_float must be the canonical as_float_or_none
    from runlog, not a local re-definition."""
    from vibesensor.diagnostics_shared import _as_float as diag_as_float
    from vibesensor.runlog import as_float_or_none

    assert diag_as_float is as_float_or_none, (
        "diagnostics_shared._as_float must be imported from runlog.as_float_or_none"
    )


def test_percentile_single_source_of_truth() -> None:
    """report.helpers.percentile must be imported from
    vibesensor_core.vibration_strength, not re-defined locally."""
    from vibesensor_core.vibration_strength import percentile as canonical

    from vibesensor.report.helpers import percentile

    assert percentile is canonical, (
        "report.helpers.percentile must be imported from vibesensor_core.vibration_strength"
    )


def test_strength_metrics_no_dead_aliases() -> None:
    """compute_vibration_strength_db output must not contain dead alias fields."""
    from vibesensor_core.vibration_strength import compute_vibration_strength_db

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


def test_constants_used_for_speed_conversion() -> None:
    """Speed conversion must use constants, not hardcoded 3.6."""
    from vibesensor.constants import KMH_TO_MPS, MPS_TO_KMH

    assert MPS_TO_KMH == 3.6
    assert abs(KMH_TO_MPS - 1.0 / 3.6) < 1e-15
    assert abs(MPS_TO_KMH * KMH_TO_MPS - 1.0) < 1e-15


def test_constants_used_for_peak_detection() -> None:
    """Peak detection defaults must come from constants module."""
    from vibesensor_core.vibration_strength import compute_vibration_strength_db

    from vibesensor.constants import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ

    assert PEAK_BANDWIDTH_HZ == 1.2
    assert PEAK_SEPARATION_HZ == 1.2

    # Verify the function signature defaults match constants
    import inspect

    sig = inspect.signature(compute_vibration_strength_db)
    assert sig.parameters["peak_bandwidth_hz"].default == PEAK_BANDWIDTH_HZ
    assert sig.parameters["peak_separation_hz"].default == PEAK_SEPARATION_HZ


def test_silence_db_constant() -> None:
    """SILENCE_DB must be the canonical silence floor value."""
    from vibesensor.constants import SILENCE_DB

    assert SILENCE_DB == -120.0


def test_config_preflight_no_removed_fields() -> None:
    """config_preflight.summarize must not reference removed config fields."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    preflight_path = root / "tools" / "config" / "vibesensor_tools_config" / "config_preflight.py"
    source = preflight_path.read_text(encoding="utf-8")
    assert "metrics_csv_path" not in source, (
        "config_preflight.py still references removed metrics_csv_path"
    )


def test_wheel_hz_and_engine_rpm_single_source() -> None:
    """wheel_hz and engine_rpm formulas must not be inlined in consumers."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    files_to_check = [
        root / "vibesensor" / "metrics_log.py",
        root / "vibesensor" / "report" / "helpers.py",
        root / "vibesensor" / "report" / "summary.py",
    ]
    for fpath in files_to_check:
        source = fpath.read_text(encoding="utf-8")
        assert "* 60.0" not in source, (
            f"{fpath.name} still contains inline engine RPM formula (* 60.0)"
        )


def test_simulator_defaults_match_analysis_settings() -> None:
    """Simulator vehicle defaults must be imported from the canonical source."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    # Read the simulator source to verify it doesn't hardcode tire/vehicle constants
    sim_source = (root / "apps" / "simulator" / "vibesensor_simulator" / "sim_sender.py").read_text(
        encoding="utf-8"
    )
    # The simulator should NOT contain hardcoded tire/vehicle values as literal assignments
    for line in sim_source.splitlines():
        stripped = line.strip()
        # Skip comments and the DEFAULT_SPEED_KMH (which is simulator-specific)
        if stripped.startswith("#") or "DEFAULT_SPEED_KMH" in stripped:
            continue
        for val in ("285.0", "= 30.0", "= 21.0", "= 3.08", "= 0.64"):
            assert val not in stripped, (
                f"sim_sender.py hardcodes vehicle default '{val}' instead of "
                "importing from DEFAULT_ANALYSIS_SETTINGS"
            )


def test_simulator_no_production_asserts() -> None:
    """Simulator module-level and standalone functions must not use bare assert."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sim_source = (root / "apps" / "simulator" / "vibesensor_simulator" / "sim_sender.py").read_text(
        encoding="utf-8"
    )
    lines = sim_source.splitlines()
    in_method = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Track whether we're inside a class method (indented def inside class)
        if stripped.startswith("def ") and not line.startswith(" "):
            in_method = False
        elif stripped.startswith("def ") and line.startswith("    "):
            in_method = True
        # Only flag asserts in module-level or standalone functions
        if not in_method and stripped.startswith("assert "):
            raise AssertionError(
                f"sim_sender.py:{i} uses bare assert in non-method context: {stripped!r}"
            )


def test_esp_protocol_constants_match_python() -> None:
    """ESP C++ protocol constants must match the Python protocol module."""
    import re
    from pathlib import Path

    from vibesensor.protocol import (
        ACK_BYTES,
        CMD_HEADER_BYTES,
        CMD_IDENTIFY,
        CMD_IDENTIFY_BYTES,
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

    root = Path(__file__).resolve().parents[3]
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
        "DATA_ACK_BYTES": DATA_ACK_BYTES,
        "CMD_HEADER_BYTES": CMD_HEADER_BYTES,
        "CMD_IDENTIFY_BYTES": CMD_IDENTIFY_BYTES,
    }
    cpp_names = {
        "HELLO_FIXED_BYTES": "kHelloFixedBytes",
        "DATA_HEADER_BYTES": "kDataHeaderBytes",
        "ACK_BYTES": "kAckBytes",
        "DATA_ACK_BYTES": "kDataAckBytes",
        "CMD_HEADER_BYTES": "kCmdHeaderBytes",
        "CMD_IDENTIFY_BYTES": "kCmdIdentifyBytes",
    }
    # Evaluate C++ expressions by substituting kClientIdBytes and kCmdHeaderBytes
    for py_name, expected in py_sizes.items():
        cpp_name = cpp_names[py_name]
        m = re.search(rf"constexpr\s+size_t\s+{cpp_name}\s*=\s*(.+);", header)
        assert m, f"C++ constant {cpp_name} not found"
        expr = m.group(1).strip()
        # Substitute known constants for eval
        expr = expr.replace("kClientIdBytes", "6").replace("kCmdHeaderBytes", str(CMD_HEADER_BYTES))
        computed = eval(expr)  # noqa: S307
        assert computed == expected, f"{cpp_name} = {computed} but Python {py_name} = {expected}"


def test_protocol_docs_byte_sizes_match() -> None:
    """docs/protocol.md byte sizes must match the Python protocol module."""
    import re
    from pathlib import Path

    from vibesensor.protocol import (
        ACK_BYTES,
        CMD_HEADER_BYTES,
        CMD_IDENTIFY_BYTES,
        DATA_ACK_BYTES,
        DATA_HEADER_BYTES,
        HELLO_FIXED_BYTES,
    )

    root = Path(__file__).resolve().parents[3]
    doc = (root / "docs" / "protocol.md").read_text(encoding="utf-8")

    expected = {
        "HELLO fixed bytes": HELLO_FIXED_BYTES,
        "DATA header bytes": DATA_HEADER_BYTES,
        "CMD header bytes": CMD_HEADER_BYTES,
        "CMD identify bytes": CMD_IDENTIFY_BYTES,
        "ACK bytes": ACK_BYTES,
        "DATA_ACK bytes": DATA_ACK_BYTES,
    }
    for label, value in expected.items():
        pattern = rf"{re.escape(label)}.*`(\d+)`"
        m = re.search(pattern, doc, re.IGNORECASE)
        assert m, f"docs/protocol.md missing entry for '{label}'"
        doc_value = int(m.group(1))
        assert doc_value == value, (
            f"docs/protocol.md says {label} = {doc_value} but code says {value}"
        )


def test_protocol_docs_match_generated_contract_reference() -> None:
    """docs/protocol.md must match the generated authoritative contract doc."""
    from vibesensor.contract_reference_doc import render_contract_reference_markdown

    root = Path(__file__).resolve().parents[3]
    doc_path = root / "docs" / "protocol.md"
    observed = doc_path.read_text(encoding="utf-8")
    expected = render_contract_reference_markdown()
    assert observed == expected, (
        "docs/protocol.md is out of date. "
        "Run: python3 tools/config/generate_contract_reference_doc.py"
    )


def test_sanitize_settings_is_single_source() -> None:
    """settings_store._sanitize_aspects must use the canonical sanitize_settings."""
    import inspect

    from vibesensor.analysis_settings import sanitize_settings
    from vibesensor.settings_store import _sanitize_aspects

    # The function should delegate to sanitize_settings (check source contains the call)
    source = inspect.getsource(_sanitize_aspects)
    assert "sanitize_settings" in source, (
        "_sanitize_aspects must delegate to sanitize_settings from analysis_settings"
    )

    # Both must use the same validation logic — verify on a known-invalid input
    bad = {"tire_width_mm": -1.0, "rim_in": 21.0}
    assert sanitize_settings(bad) == _sanitize_aspects(bad)


def test_sanitize_settings_rejects_invalid() -> None:
    """sanitize_settings must drop invalid values."""
    from vibesensor.analysis_settings import sanitize_settings

    result = sanitize_settings(
        {
            "tire_width_mm": -1.0,  # positive required, should be dropped
            "rim_in": 21.0,  # valid
            "speed_uncertainty_pct": -0.5,  # non-negative, should be dropped
            "final_drive_ratio": "not_a_number",  # invalid type
        }
    )
    assert "tire_width_mm" not in result
    assert "speed_uncertainty_pct" not in result
    assert "final_drive_ratio" not in result
    assert result["rim_in"] == 21.0


def test_validation_sets_cover_all_settings_keys() -> None:
    """Every key in DEFAULT_ANALYSIS_SETTINGS must be in exactly one validation set."""
    from vibesensor.analysis_settings import (
        NON_NEGATIVE_KEYS,
        POSITIVE_REQUIRED_KEYS,
    )

    all_keys = set(DEFAULT_ANALYSIS_SETTINGS)
    covered = POSITIVE_REQUIRED_KEYS | NON_NEGATIVE_KEYS
    uncovered = all_keys - covered
    assert not uncovered, (
        f"Keys not in any validation set: {uncovered}. "
        "Add them to POSITIVE_REQUIRED_KEYS or NON_NEGATIVE_KEYS."
    )
    overlap = POSITIVE_REQUIRED_KEYS & NON_NEGATIVE_KEYS
    assert not overlap, f"Keys in both validation sets: {overlap}"


def test_esp_ports_match_python_defaults() -> None:
    """ESP server port constants must match Python DEFAULT_CONFIG."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    main_cpp = (root / "firmware" / "esp" / "src" / "main.cpp").read_text(encoding="utf-8")

    m_data = re.search(r"kServerDataPort\s*=\s*(\d+)", main_cpp)
    m_ctrl = re.search(r"kServerControlPort\s*=\s*(\d+)", main_cpp)
    assert m_data and m_ctrl, "ESP port constants not found in main.cpp"
    esp_data_port = int(m_data.group(1))
    esp_ctrl_port = int(m_ctrl.group(1))

    from vibesensor.config import DEFAULT_CONFIG

    py_data = DEFAULT_CONFIG["udp"]["data_listen"]
    py_ctrl = DEFAULT_CONFIG["udp"]["control_listen"]
    py_data_port = int(str(py_data).rsplit(":", 1)[-1])
    py_ctrl_port = int(str(py_ctrl).rsplit(":", 1)[-1])

    assert esp_data_port == py_data_port, (
        f"ESP data port {esp_data_port} != Python default {py_data_port}"
    )
    assert esp_ctrl_port == py_ctrl_port, (
        f"ESP control port {esp_ctrl_port} != Python default {py_ctrl_port}"
    )


def test_config_example_matches_documented_defaults() -> None:
    """config.example.yaml must be derived from canonical runtime defaults."""
    root = Path(__file__).resolve().parents[3]
    config_example = root / "apps" / "server" / "config.example.yaml"

    observed = yaml.safe_load(config_example.read_text(encoding="utf-8"))

    from vibesensor.config import documented_default_config

    expected = documented_default_config()
    assert observed == expected


def test_server_dockerfile_is_real_build_recipe() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = root / "apps" / "server" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")
    first_line = content.splitlines()[0].strip()
    assert first_line.startswith("FROM "), (
        "apps/server/Dockerfile must be a real Dockerfile, not a placeholder"
    )
