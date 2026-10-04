"""Fake on-disk venvs and slot commands for the A/B slot updater tests."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from vibesensor.updates.venv_slots import VenvSlots


def make_venv(root: Path, *, server_shebang: str | None = None) -> Path:
    """Create a venv-shaped directory the way ``venv`` and pip lay it out.

    ``bin/python3`` points at the test interpreter so launchers can really run.
    With *server_shebang*, ``bin/vibesensor-server`` is a console script using it.
    """
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").symlink_to(sys.executable)
    (bin_dir / "python").symlink_to("python3")
    site_packages = root / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
    site_packages = site_packages / "site-packages"
    site_packages.mkdir(parents=True)
    home = Path(os.path.realpath(sys.executable)).parent
    (root / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")
    (root / "include").mkdir()
    (root / ".gitignore").write_text("*\n", encoding="utf-8")
    if server_shebang is not None:
        write_script(
            bin_dir / "vibesensor-server",
            f"#!{server_shebang}\nfrom vibesensor.cli.server import main\nmain()\n",
        )
    return root


def make_legacy_venv(root: Path, *, server_script: str | None = None) -> Path:
    """Create a plain (pre-A/B) venv at *root*, as flashed images before slots had."""
    make_venv(root, server_shebang=f"{root}/bin/python")
    bin_dir = root / "bin"
    if server_script is not None:
        write_script(bin_dir / "vibesensor-server", server_script)
    write_script(bin_dir / "vibesensor-config-preflight", f"#!{root}/bin/python\nprint('ok')\n")
    site_packages = next((root / "lib").glob("python*/site-packages"))
    (site_packages / "legacy_marker.py").write_text("LEGACY = True\n", encoding="utf-8")
    (root / "lib64").symlink_to("lib")
    return root


def add_slot(slots: VenvSlots, name: str, *, server_script: str | None = None) -> Path:
    """Create installed slot *name* (venv + pip console script + launcher)."""
    slot = make_venv(slots.slot_dir(name), server_shebang=str(slots.slot_python(name)))
    if server_script is not None:
        write_script(slot / "bin" / "vibesensor-server", server_script)
    slots.install_launcher(name)
    return slot


def simulate_slot_command(args: Sequence[str]) -> None:
    """Mimic the file effects of ``python -m venv <dir>`` and ``python -m pip install``."""
    if list(args[1:3]) == ["-m", "venv"]:
        make_venv(Path(args[3]))
    elif list(args[1:4]) == ["-m", "pip", "install"]:
        python = Path(args[0])
        write_script(python.parent / "vibesensor-server", f"#!{python}\n# installed\n")


def write_script(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
