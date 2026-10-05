"""Does the device's root side match the one this app release ships?

The root side is ``apps/server/root-helpers/``, ``scripts/``, and
``systemd/``. Root installs it with ``install_systemd_units.sh``, which
copies the helpers into ``/usr/local/lib/vibesensor``, renders the units, and
writes a manifest of the tree it installed from to :data:`ROOT_SIDE_STAMP`.
In-app updates replace only the venv. So after an update to a release that
changed the root side, the device keeps running the old helpers and units,
and hotspot repair or Bluetooth OBD pairing can fail without a clear error.
This module compares the installed manifest with :data:`ROOT_SIDE_DIGEST`, the
manifest digest of this release's tree. The app only reads the stamp. It
never installs root-side files: an operator does that
(docs/operational-runbooks.md, "Installing a release's root side").

Manifest format, shared by the installer, ``push_root_side.sh``, and the
runbook: one ``sha256sum`` line (``<hex>  <dir>/<name>``) per regular file
directly inside the three directories, sorted bytewise. The digest is the
SHA-256 of that text, as printed by::

    cd apps/server && find root-helpers scripts systemd -maxdepth 1 -type f \\
      -exec sha256sum {} + | LC_ALL=C sort | sha256sum
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "ROOT_SIDE_DIGEST",
    "ROOT_SIDE_DIRS",
    "RootSideState",
    "RootSideStatus",
    "inspect_root_side",
    "root_side_manifest",
]

ROOT_SIDE_DIGEST: Final = "af65216dc0308e987499c65334eecc1581b58e478071e629f4fd1b7fb88ca711"
"""Manifest digest of this release's root side.

``tests/hygiene/test_root_side.py`` fails with the new value whenever a
file under root-helpers/, scripts/, or systemd/ changes. Such a release needs
an operator to reinstall the root side on every device; say so in its notes."""

ROOT_SIDE_DIRS: Final = ("root-helpers", "scripts", "systemd")
ROOT_SIDE_STAMP: Final = Path("/usr/local/lib/vibesensor/root-side.sha256")
"""Written by install_systemd_units.sh after the units are installed."""
SERVER_UNIT: Final = Path("/etc/systemd/system/vibesensor.service")
"""Present only on systemd installs (image or install_pi.sh), not in dev or Docker."""

RootSideState = Literal["current", "outdated", "not_installed"]


@dataclass(frozen=True, slots=True)
class RootSideStatus:
    state: RootSideState
    """``not_installed``: the server does not run from a systemd install."""
    installed_digest: str | None
    """Digest of the installed manifest; None when the stamp is missing (an
    install from before the stamp, or an install that stopped half way)."""
    expected_digest: str


def root_side_manifest(server_dir: Path) -> str:
    """Return the manifest of the root side under *server_dir* (apps/server)."""

    lines = []
    for dirname in ROOT_SIDE_DIRS:
        for path in (server_dir / dirname).iterdir():
            if path.is_file() and not path.is_symlink():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                lines.append(f"{digest}  {dirname}/{path.name}\n".encode())
    return b"".join(sorted(lines)).decode()


def inspect_root_side(
    *, server_unit: Path = SERVER_UNIT, stamp: Path = ROOT_SIDE_STAMP
) -> RootSideStatus:
    """Compare the installed root-side stamp with this release's digest."""

    if not server_unit.exists():
        return RootSideStatus("not_installed", None, ROOT_SIDE_DIGEST)
    try:
        installed: str | None = hashlib.sha256(stamp.read_bytes()).hexdigest()
    except OSError:
        installed = None
    state: RootSideState = "current" if installed == ROOT_SIDE_DIGEST else "outdated"
    return RootSideStatus(state, installed, ROOT_SIDE_DIGEST)
