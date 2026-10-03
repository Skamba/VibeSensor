#!/usr/bin/env python3
"""Validate the bundled vehicle library: plausibility, duplicates and source evidence.

Usage: python tools/car_library/validate_vehicle_library.py

Exits non-zero and lists the issues when the packaged vehicle configurations
break a rule. ``apps/server/tests/settings/test_car_library_validation.py`` runs
the same check in CI.
"""

from __future__ import annotations

import sys

from car_library_validation import ensure_valid_vehicle_configurations
from car_library_validation.source_evidence import (
    ensure_valid_vehicle_configuration_source_evidence,
)

from vibesensor.settings.vehicle_configurations import load_vehicle_configurations


def main() -> int:
    configs = load_vehicle_configurations()
    if not configs:
        print("No bundled vehicle configurations found.", file=sys.stderr)
        return 1
    try:
        ensure_valid_vehicle_configurations(configs)
        ensure_valid_vehicle_configuration_source_evidence(configs)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{len(configs)} vehicle configurations are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
