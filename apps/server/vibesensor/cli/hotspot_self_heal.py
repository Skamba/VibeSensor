"""CLI entry point for the hotspot watchdog (``vibesensor-hotspot-self-heal``)."""

from __future__ import annotations

import logging

from vibesensor.hotspot.watchdog import check_hotspot


def main() -> None:
    """Run one hotspot watchdog pass.

    Arguments are ignored: systemd units installed by earlier images pass
    ``--mode check-heal --config …`` and keep calling this entry point after an
    over-the-air update.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raise SystemExit(check_hotspot())
