"""Print hotspot config as shell variable exports for sourcing by hotspot_nmcli.sh."""

from __future__ import annotations

import sys
from pathlib import Path

from vibesensor.app.settings import DEFAULT_CONFIG


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/etc/vibesensor/config.yaml")
    ap_defaults = DEFAULT_CONFIG["ap"]
    assert isinstance(ap_defaults, dict), "DEFAULT_CONFIG['ap'] must be a dict"
    defaults = {k: v for k, v in ap_defaults.items() if k != "self_heal"}

    cfg: dict[str, object] = {}
    if config_path.exists():
        try:
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                cfg = raw.get("ap", {}) or {}
        except Exception:
            cfg = {}

    ap = {**defaults, **cfg}
    for k, v in ap.items():
        if not isinstance(v, dict):
            print(f"{k.upper()}={v!r}")


if __name__ == "__main__":
    main()
