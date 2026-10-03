"""A/B virtualenv slots inside the server's ``.venv`` directory.

``root`` is ``<repo>/apps/server/.venv``. Its parent is root-owned, but the
directory itself belongs to the service user, so every switch happens inside it::

    current -> slots/<version>         the active slot, flipped atomically
    bin, lib, pyvenv.cfg, ...          routes: symlinks to current/<entry>
    slots/<version>/                   complete venvs, created in place, never moved
    boot-pending.json                  candidate awaiting its boot check
    boot-reverted.json                 last automatic revert (read once at startup)

systemd units, hotspot scripts, and docs only know ``.venv/bin/...`` and follow
``current`` through the routes. Each slot's ``bin/vibesensor-server`` is the
stdlib-only launcher from :mod:`vibesensor.updates.boot_check`.

Devices flashed before A/B slots have a plain venv at ``root``; :meth:`VenvSlots.adopt`
moves it into a slot once. The Pi image build and ``install_pi.sh`` run the same
adoption through ``python -m vibesensor.updates.venv_slots adopt <root>``.
"""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import msgspec

from vibesensor.updates import boot_check
from vibesensor.updates.boot_check import (
    CURRENT_LINK,
    PENDING_FILE,
    REVERTED_FILE,
    SERVER_APP,
    SLOTS_DIR,
    PendingBoot,
    read_pending,
    switch_current,
    write_json_atomic,
)

__all__ = ["RevertedBoot", "VenvSlots"]

SERVER_SCRIPT = "vibesensor-server"
_LEGACY_BIN = ".bin.legacy"


class RevertedBoot(msgspec.Struct, frozen=True):
    """A candidate the boot check rejected and switched away from."""

    candidate: str
    previous: str
    reason: str


class VenvSlots:
    """Create, activate, and prune venv slots under one ``.venv`` root."""

    __slots__ = ("root",)

    def __init__(self, root: Path) -> None:
        self.root = root

    def slot_dir(self, name: str) -> Path:
        return self.root / SLOTS_DIR / name

    def slot_python(self, name: str) -> Path:
        return self.slot_dir(name) / "bin" / "python3"

    def is_adopted(self) -> bool:
        return (self.root / "bin").is_symlink()

    def active_slot(self) -> str | None:
        link = self.root / CURRENT_LINK
        if not link.is_symlink():
            return None
        return Path(os.readlink(link)).name

    def pending_boot(self) -> PendingBoot | None:
        return read_pending(self.root)

    def adopt(self, name: str) -> None:
        """Turn a plain venv at ``root`` into slot *name*; resumable and idempotent.

        Each top-level venv entry moves into the slot and is replaced by a route.
        ``bin`` goes last: until then the legacy scripts keep working, and its
        swap is two renames that ext4 journals together.
        """
        if self.is_adopted():
            return
        if not (self.root / "bin").is_dir():
            raise FileNotFoundError(f"no venv to adopt at {self.root}")
        slot = self.slot_dir(name)
        slot.mkdir(parents=True, exist_ok=True)
        if not (self.root / CURRENT_LINK).is_symlink():
            switch_current(self.root, name)
        if not (slot / "bin").exists():
            staging = slot / ".bin.tmp"
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(self.root / "bin", staging, symlinks=True)
            self._install_launcher(staging, slot_python=slot / "bin" / "python3")
            os.replace(staging, slot / "bin")
        for entry in sorted(self.root.iterdir()):
            if entry.is_symlink() or entry.name in {"bin", SLOTS_DIR}:
                continue
            if entry.name.startswith((".", "boot-")):
                continue
            os.replace(entry, slot / entry.name)
            os.symlink(f"{CURRENT_LINK}/{entry.name}", entry)
        legacy_bin = self.root / _LEGACY_BIN
        shutil.rmtree(legacy_bin, ignore_errors=True)
        if (self.root / "bin").exists():
            os.replace(self.root / "bin", legacy_bin)
        route = self.root / ".bin.route"
        route.unlink(missing_ok=True)
        os.symlink(f"{CURRENT_LINK}/bin", route)
        os.replace(route, self.root / "bin")
        shutil.rmtree(legacy_bin, ignore_errors=True)

    def install_launcher(self, name: str) -> None:
        """Move pip's ``vibesensor-server`` aside and put the boot-check launcher there."""
        self._install_launcher(self.slot_dir(name) / "bin", slot_python=self.slot_python(name))

    @staticmethod
    def _install_launcher(bin_dir: Path, *, slot_python: Path) -> None:
        launcher = bin_dir / SERVER_SCRIPT
        os.replace(launcher, bin_dir / SERVER_APP)
        source = Path(boot_check.__file__).read_text(encoding="utf-8")
        staging = bin_dir / f".{SERVER_SCRIPT}.tmp"
        staging.write_text(f"#!{slot_python} -IS\n{source}", encoding="utf-8")
        staging.chmod(0o755)
        os.replace(staging, launcher)

    def remove_slot(self, name: str) -> None:
        shutil.rmtree(self.slot_dir(name), ignore_errors=True)

    def prune(self, keep: str) -> None:
        """Delete every slot except *keep* (the active one)."""
        for slot in (self.root / SLOTS_DIR).iterdir():
            if slot.name != keep:
                shutil.rmtree(slot)

    def activate(self, candidate: str, *, health_url: str) -> None:
        """Arm the boot check for *candidate*, then make it the active slot."""
        previous = self.active_slot()
        if previous is None:
            raise RuntimeError(f"{self.root} has no active slot")
        pending = PendingBoot(candidate=candidate, previous=previous, health_url=health_url)
        write_json_atomic(self.root / PENDING_FILE, asdict(pending))
        try:
            switch_current(self.root, candidate)
        except OSError:
            (self.root / PENDING_FILE).unlink(missing_ok=True)
            raise

    def take_reverted(self) -> RevertedBoot | None:
        """Return and clear the record of the last automatic revert, if any."""
        path = self.root / REVERTED_FILE
        try:
            raw = path.read_bytes()
            path.unlink()
        except OSError:
            return None
        try:
            return msgspec.json.decode(raw, type=RevertedBoot)
        except (msgspec.DecodeError, msgspec.ValidationError):
            return RevertedBoot(candidate="?", previous="?", reason="unreadable revert record")


def main(argv: list[str] | None = None) -> None:
    """``adopt <root>``: convert a freshly built plain venv into the slot layout."""
    parser = argparse.ArgumentParser(description="Manage VibeSensor A/B venv slots")
    sub = parser.add_subparsers(dest="command", required=True)
    adopt = sub.add_parser("adopt", help="move a plain venv into a slot named after its version")
    adopt.add_argument("root", type=Path)
    args = parser.parse_args(argv)

    from vibesensor import __version__

    VenvSlots(args.root).adopt(__version__)
    print(f"{args.root}: active slot {__version__}")


if __name__ == "__main__":
    main()
