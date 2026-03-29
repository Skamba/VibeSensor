#!/usr/bin/env python3
"""Privileged Bluetooth OBD helper wrapper."""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vibesensor.adapters.obd.admin_helper import main


if __name__ == "__main__":
    raise SystemExit(main())
