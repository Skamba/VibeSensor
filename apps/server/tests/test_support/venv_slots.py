"""Fake on-disk venvs for the A/B slot updater tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def make_legacy_venv(root: Path, *, server_script: str | None = None) -> Path:
    """Create a plain (pre-A/B) venv at *root* the way pip and ``venv`` lay it out.

    ``bin/python3`` points at the test interpreter so launchers can really run;
    ``bin/vibesensor-server`` is a console script (or *server_script*).
    """
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").symlink_to(sys.executable)
    (bin_dir / "python").symlink_to("python3")
    shebang = f"#!{root}/bin/python\n"
    _write_script(
        bin_dir / "vibesensor-server",
        server_script or f"{shebang}from vibesensor.cli.server import main\nmain()\n",
    )
    _write_script(bin_dir / "vibesensor-hotspot-config", f"{shebang}print('hotspot')\n")
    site_packages = root / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
    site_packages = site_packages / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "legacy_marker.py").write_text("LEGACY = True\n", encoding="utf-8")
    home = Path(os.path.realpath(sys.executable)).parent
    (root / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")
    (root / "include").mkdir()
    (root / "lib64").symlink_to("lib")
    (root / ".gitignore").write_text("*\n", encoding="utf-8")
    return root


def _write_script(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
