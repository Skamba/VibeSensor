"""``vibesensor-server`` CLI entry point."""

from __future__ import annotations

import os


def main() -> None:
    """Entry point for the ``vibesensor-server`` CLI command."""
    os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")
    from vibesensor.app import main as app_main

    app_main()
