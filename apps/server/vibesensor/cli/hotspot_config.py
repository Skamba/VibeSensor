"""Print hotspot config as shell variable exports for sourcing by hotspot_nmcli.sh."""

from __future__ import annotations

import sys
from pathlib import Path

from vibesensor.app.config_defaults import DEFAULT_CONFIG


def _warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def _load_ap_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        _warn(f"Failed to import YAML support for {config_path}: {exc}; using defaults.")
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        _warn(f"Failed to parse hotspot config {config_path}: {exc}; using defaults.")
        return {}

    if not isinstance(raw, dict):
        _warn(f"Hotspot config {config_path} must contain a top-level mapping; using defaults.")
        return {}

    cfg = raw.get("ap", {}) or {}
    if not isinstance(cfg, dict):
        _warn(f"Hotspot config {config_path} has a non-mapping 'ap' section; using defaults.")
        return {}
    return cfg


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/etc/vibesensor/config.yaml")
    ap_defaults = DEFAULT_CONFIG["ap"]
    assert isinstance(ap_defaults, dict), "DEFAULT_CONFIG['ap'] must be a dict"
    defaults = {k: v for k, v in ap_defaults.items() if k != "self_heal"}
    cfg = _load_ap_config(config_path)
    ap = {**defaults, **cfg}
    for k, v in ap.items():
        if not isinstance(v, dict):
            print(f"{k.upper()}={v!r}")


if __name__ == "__main__":
    main()
