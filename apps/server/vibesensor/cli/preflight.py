from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from vibesensor.app.config_defaults import documented_default_config
from vibesensor.app.config_loader import load_config
from vibesensor.app.config_schema import AppConfig
from vibesensor.shared.constants.ui import UI_HEAVY_PUSH_HZ, UI_PUSH_HZ
from vibesensor.shared.process_settings import load_update_env_settings, summarize_process_settings

_DIR_WRITE_ACCESS = os.W_OK | os.X_OK


@dataclass(frozen=True, slots=True)
class _WritablePathCheck:
    label: str
    path: Path
    expects_directory: bool = False


def summarize(cfg: AppConfig) -> dict[str, object]:
    return {
        "config_path": str(cfg.config_path),
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "udp": {
            "data_host": cfg.udp.data_host,
            "data_port": cfg.udp.data_port,
            "control_host": cfg.udp.control_host,
            "control_port": cfg.udp.control_port,
        },
        "processing": {
            "sample_rate_hz": cfg.processing.sample_rate_hz,
            "ui_push_hz": UI_PUSH_HZ,
            "ui_heavy_push_hz": UI_HEAVY_PUSH_HZ,
        },
        "paths": {
            "history_db_path": str(cfg.logging.history_db_path),
        },
        "process_settings": summarize_process_settings(),
    }


def _writable_path_checks(cfg: AppConfig) -> tuple[_WritablePathCheck, ...]:
    update = load_update_env_settings()
    checks: list[_WritablePathCheck] = [
        _WritablePathCheck("logging.history_db_path", cfg.logging.history_db_path),
    ]
    if cfg.logging.app_log_path is not None:
        checks.append(_WritablePathCheck("logging.app_log_path", cfg.logging.app_log_path))
    if cfg.ap.self_heal.enabled:
        checks.append(_WritablePathCheck("ap.self_heal.state_file", cfg.ap.self_heal.state_file))
    if cfg.tracing.enabled:
        checks.append(_WritablePathCheck("tracing.output_path", cfg.tracing.output_path))
    checks.extend(
        (
            _WritablePathCheck(
                "update.rollback_dir", cfg.update.rollback_dir, expects_directory=True
            ),
            _WritablePathCheck("process_settings.update_state_path", update.update_state_path),
            _WritablePathCheck(
                "process_settings.firmware_cache_dir",
                update.firmware_cache_dir,
                expects_directory=True,
            ),
        )
    )
    return tuple(checks)


def _not_writable(check: _WritablePathCheck, detail: str) -> ValueError:
    return ValueError(f"{check.label} is not writable: {detail}")


def _nearest_existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            raise ValueError(f"could not find an existing parent for {path}")
        current = parent
    return current


def _ensure_writable_directory(
    check: _WritablePathCheck,
    directory: Path,
    *,
    relation: str,
) -> None:
    if not directory.is_dir():
        raise _not_writable(check, f"{relation} {directory} exists but is not a directory")
    if not os.access(directory, _DIR_WRITE_ACCESS):
        raise _not_writable(check, f"{relation} {directory} is not writable")


def _validate_writable_path(check: _WritablePathCheck) -> None:
    path = check.path
    if check.expects_directory:
        if path.exists():
            _ensure_writable_directory(check, path, relation="directory")
            return
        ancestor = _nearest_existing_ancestor(path)
        relation = "parent directory" if ancestor == path.parent else "nearest existing parent"
        _ensure_writable_directory(check, ancestor, relation=relation)
        return
    if path.exists():
        if path.is_dir():
            raise _not_writable(check, f"path {path} exists but is a directory")
        if not os.access(path, os.W_OK):
            raise _not_writable(check, f"file {path} exists but is not writable")
        return
    ancestor = _nearest_existing_ancestor(path.parent)
    relation = "parent directory" if ancestor == path.parent else "nearest existing parent"
    _ensure_writable_directory(check, ancestor, relation=relation)


def _validate_writable_runtime_paths(cfg: AppConfig) -> None:
    for check in _writable_path_checks(cfg):
        _validate_writable_path(check)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and print resolved VibeSensor config")
    parser.add_argument("config", type=Path, nargs="?", help="Path to config YAML")
    parser.add_argument(
        "--dump-defaults",
        action="store_true",
        help="Print the documented default config and exit",
    )
    args = parser.parse_args()
    if args.dump_defaults and args.config is not None:
        parser.error("--dump-defaults and config are mutually exclusive")
    if not args.dump_defaults and args.config is None:
        parser.error("config is required unless --dump-defaults is set")
    return args


def main() -> int:
    args = parse_args()
    if args.dump_defaults:
        print(json.dumps(documented_default_config(), indent=2, sort_keys=True))
        return 0
    try:
        cfg = load_config(args.config)
        _validate_writable_runtime_paths(cfg)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summarize(cfg), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
