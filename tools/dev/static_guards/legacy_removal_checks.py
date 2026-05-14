# ruff: noqa: F403,F405
"""Legacy compatibility and static-data removal guards."""

from __future__ import annotations


from .core_utils import *

_CHECK_PROCESS_SETTINGS_SHIM_REMOVED = _legacy_module_import_check(
    legacy_path=VIBESENSOR_DIR / "app" / "process_settings.py",
    legacy_path_message=(
        "apps/server/vibesensor/app/process_settings.py should stay removed; use "
        "vibesensor.shared.process_settings directly"
    ),
    scan_roots=(SERVER_ROOT, REPO_ROOT / "tools"),
    direct_module="vibesensor.app.process_settings",
    direct_module_message=(
        "imports from vibesensor.app.process_settings; use "
        "vibesensor.shared.process_settings directly"
    ),
    reexport_module="vibesensor.app",
    reexport_name="process_settings",
    reexport_message=(
        "imports process_settings from vibesensor.app; use "
        "vibesensor.shared.process_settings directly"
    ),
)

_CHECK_SETTINGS_FACADE_REMOVED = _legacy_module_import_check(
    legacy_path=VIBESENSOR_DIR / "app" / "settings.py",
    legacy_path_message=(
        "apps/server/vibesensor/app/settings.py should stay removed; import "
        "config owners directly"
    ),
    scan_roots=(SERVER_ROOT, REPO_ROOT / "tools"),
    direct_module="vibesensor.app.settings",
    direct_module_message=(
        "imports from vibesensor.app.settings; import config owners directly"
    ),
    reexport_module="vibesensor.app",
    reexport_name="settings",
    reexport_message=(
        "imports settings from vibesensor.app; import config owners directly"
    ),
)


def _check_history_db_facade_removed() -> list[str]:
    history_init = (
        VIBESENSOR_DIR / "adapters" / "persistence" / "history_db" / "__init__.py"
    )
    violations: list[str] = []
    if "HistoryDB" in _read_text(history_init):
        violations.append(
            f"{history_init.relative_to(REPO_ROOT)} must not define or export HistoryDB"
        )

    for root in (SERVER_ROOT, REPO_ROOT / "tools"):
        for path in _python_files(root):
            if path == history_init:
                continue
            for lineno, module, names, level in _scan_imports(path):
                if level > 0:
                    continue
                if (
                    module == "vibesensor.adapters.persistence.history_db"
                    and "HistoryDB" in names
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: imports HistoryDB from "
                        "vibesensor.adapters.persistence.history_db; use explicit collaborators"
                    )
    return violations


def _check_update_status_legacy_decode_removed() -> list[str]:
    codec_path = (
        VIBESENSOR_DIR / "use_cases" / "updates" / "status" / "payload_codec.py"
    )
    text = _read_text(codec_path)
    violations: list[str] = []
    for legacy_name in (
        "_normalize_legacy_issues",
        "_normalize_legacy_log_tail",
        "_normalize_legacy_runtime",
        "_legacy_text",
        "_coerce_legacy_bool",
    ):
        if legacy_name in text:
            violations.append(
                f"{codec_path.relative_to(REPO_ROOT)} must not define {legacy_name}; "
                "require the canonical UpdateJobStatusPayload shape instead"
            )
    return violations


def _check_settings_snapshot_legacy_decode_removed() -> list[str]:
    snapshot_path = (
        VIBESENSOR_DIR / "shared" / "boundaries" / "settings" / "snapshot.py"
    )
    settings_init_path = (
        VIBESENSOR_DIR / "shared" / "boundaries" / "settings" / "__init__.py"
    )
    violations: list[str] = []

    for legacy_name in (
        "coerce_language_code",
        "coerce_speed_unit_code",
        "settings_snapshot_from_payload",
        "_settings_snapshot_record_from_object",
    ):
        if legacy_name in _read_text(snapshot_path):
            violations.append(
                f"{snapshot_path.relative_to(REPO_ROOT)} must not define {legacy_name}; "
                "require the canonical SettingsSnapshotRecord schema instead"
            )
        if legacy_name in _read_text(settings_init_path):
            violations.append(
                f"{settings_init_path.relative_to(REPO_ROOT)} must not export {legacy_name}; "
                "keep only canonical settings snapshot entrypoints public"
            )

    legacy_imports = {
        "coerce_language_code",
        "coerce_speed_unit_code",
        "settings_snapshot_from_payload",
    }
    for root in (SERVER_ROOT, REPO_ROOT / "tools"):
        for path in _python_files(root):
            if path in {snapshot_path, settings_init_path}:
                continue
            if "build" in path.parts:
                continue
            for lineno, module, names, level in _scan_imports(path):
                if level > 0:
                    continue
                if module in {
                    "vibesensor.shared.boundaries.settings.snapshot",
                    "vibesensor.shared.boundaries.settings",
                }:
                    for legacy_name in sorted(legacy_imports & set(names)):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{lineno}: imports {legacy_name}; "
                            "require the canonical SettingsSnapshotRecord schema instead"
                        )
    return violations


def _check_udp_hello_legacy_compat_removed() -> list[str]:
    protocol_path = VIBESENSOR_DIR / "adapters" / "udp" / "protocol.py"
    control_path = VIBESENSOR_DIR / "adapters" / "udp" / "udp_control_tx.py"
    protocol_tests = TESTS_DIR / "adapters" / "udp" / "test_protocol_validation.py"
    control_tests = TESTS_DIR / "adapters" / "udp" / "test_udp_control_tx.py"
    violations: list[str] = []

    control_text = _read_text(control_path)
    if "HELLO_CAP_EXPLICIT_ACK" in control_text:
        violations.append(
            f"{control_path.relative_to(REPO_ROOT)} must not gate HELLO_ACK on "
            "HELLO_CAP_EXPLICIT_ACK"
        )

    protocol_text = _read_text(protocol_path)
    for legacy_text in (
        "if len(data) >= offset + 4:",
        "if len(data) > offset:",
    ):
        if legacy_text in protocol_text:
            violations.append(
                f"{protocol_path.relative_to(REPO_ROOT)} still contains legacy HELLO "
                "tail fallback logic"
            )

    if "test_parse_hello_defaults_capabilities_to_zero_for_legacy_packet" in _read_text(
        protocol_tests
    ):
        violations.append(
            f"{protocol_tests.relative_to(REPO_ROOT)} must not preserve legacy short HELLO tests"
        )
    if "test_control_datagram_skips_hello_ack_for_legacy_firmware" in _read_text(
        control_tests
    ):
        violations.append(
            f"{control_tests.relative_to(REPO_ROOT)} must not preserve legacy HELLO_ACK skips"
        )
    return violations


def _check_static_data_uses_packaged_tree_only() -> list[str]:
    resolver_path = VIBESENSOR_DIR / "shared" / "_data_files.py"
    resolver_source = _read_text(resolver_path)
    failures: list[str] = []
    for marker in (
        "_SOURCE_DATA_DIR",
        "source_candidate =",
        '_PACKAGE_ROOT.parent / "data"',
    ):
        if marker in resolver_source:
            failures.append(
                f"{resolver_path.relative_to(REPO_ROOT)} must not keep source-tree static-data fallback logic ({marker})"
            )
    for path in (
        SERVER_ROOT / "data" / "report_i18n.json",
        SERVER_ROOT / "data" / "vehicle_configurations.json",
        SERVER_ROOT / "data" / "car_sources",
        SERVER_ROOT / "data" / "scripted_scenarios",
    ):
        if path.exists():
            failures.append(
                f"{path.relative_to(REPO_ROOT)} should not exist; canonical shipped static data lives under apps/server/vibesensor/data/"
            )
    return failures
