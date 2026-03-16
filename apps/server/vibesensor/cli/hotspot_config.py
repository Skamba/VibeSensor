"""Print hotspot config as shell variable exports for sourcing by hotspot_nmcli.sh."""

from __future__ import annotations

import sys
from pathlib import Path

from vibesensor.app.settings import DEFAULT_CONFIG


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/etc/vibesensor/config.yaml")
    defaults = {k: v for k, v in DEFAULT_CONFIG["ap"].items() if k != "self_heal"}  # type: ignore[union-attr]

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
