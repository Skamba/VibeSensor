from __future__ import annotations

import os


def main() -> None:
    os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")
    from vibesensor.app import main as app_main

    app_main()
