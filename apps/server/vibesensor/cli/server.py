"""``vibesensor-server`` CLI entry point."""

from __future__ import annotations


def main() -> None:
    """Entry point for the ``vibesensor-server`` CLI command."""
    from vibesensor.app.bootstrap import main as app_main

    app_main()
