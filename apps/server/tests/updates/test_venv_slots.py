"""On-disk behaviour of the A/B venv slot layout (adoption, clone, activate, prune)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_support.venv_slots import make_legacy_venv

from vibesensor.updates.boot_check import PENDING_FILE, REVERTED_FILE, SERVER_APP
from vibesensor.updates.venv_slots import RevertedBoot, VenvSlots, main


def _adopted(tmp_path: Path, name: str = "1.0") -> VenvSlots:
    root = make_legacy_venv(tmp_path / ".venv")
    slots = VenvSlots(root)
    slots.adopt(name)
    return slots


def test_adopt_moves_the_plain_venv_into_a_slot_behind_routes(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)
    root = slots.root

    assert slots.is_adopted()
    assert slots.active_slot() == "1.0"
    assert os.readlink(root / "current") == "slots/1.0"
    for entry in ("bin", "lib", "include", "pyvenv.cfg"):
        assert os.readlink(root / entry) == f"current/{entry}"
    assert os.readlink(root / "lib64") == "lib"
    assert (root / ".gitignore").is_file()
    assert sorted(p.name for p in (root / "slots").iterdir()) == ["1.0"]
    slot_bin = root / "slots" / "1.0" / "bin"
    assert (slot_bin / SERVER_APP).read_text().startswith(f"#!{root}/bin/python")
    assert (
        (slot_bin / "vibesensor-server")
        .read_text()
        .startswith(
            f"#!{slot_bin}/python3 -IS\n",
        )
    )


def test_adopted_paths_keep_working_for_systemd_and_scripts(tmp_path: Path) -> None:
    root = make_legacy_venv(
        tmp_path / ".venv",
        server_script='#!/bin/sh\necho "legacy server $@"\n',
    )
    VenvSlots(root).adopt("1.0")

    server = subprocess.run(
        [str(root / "bin" / "vibesensor-server"), "--config", "/etc/x.yaml"],
        capture_output=True,
        text=True,
        check=True,
    )
    python = subprocess.run(
        [str(root / "bin" / "python3"), "-c", "import sys, legacy_marker; print(sys.prefix)"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert server.stdout == "legacy server --config /etc/x.yaml\n"
    assert python.stdout.strip() == str(root)


def test_adopt_is_idempotent(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)

    slots.adopt("2.0")

    assert slots.active_slot() == "1.0"
    assert sorted(p.name for p in (slots.root / "slots").iterdir()) == ["1.0"]


def test_adopt_resumes_after_an_interruption_before_bin_was_swapped(tmp_path: Path) -> None:
    root = make_legacy_venv(tmp_path / ".venv")
    slot = root / "slots" / "1.0"
    slot.mkdir(parents=True)
    (root / "current").symlink_to("slots/1.0")
    # lib was already moved and routed; bin and the rest were not.
    (root / "lib").rename(slot / "lib")
    (root / "lib").symlink_to("current/lib")

    VenvSlots(root).adopt("1.0")

    assert os.readlink(root / "bin") == "current/bin"
    assert os.readlink(root / "lib") == "current/lib"
    assert (slot / "lib").is_dir()
    assert (slot / "pyvenv.cfg").is_file()
    assert not (root / ".bin.legacy").exists()


def test_clone_slot_copies_the_env_and_repoints_its_own_shebangs(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)
    source_bin = slots.slot_dir("1.0") / "bin"
    (source_bin / "granian").write_text(f"#!{source_bin}/python3\nrun()\n", encoding="utf-8")

    slots.clone_slot("1.0", "2.0")

    target_bin = slots.slot_dir("2.0") / "bin"
    assert (target_bin / "granian").read_text() == f"#!{target_bin}/python3\nrun()\n"
    # Legacy scripts address the routed interpreter and are left alone.
    assert (target_bin / SERVER_APP).read_text().startswith(f"#!{slots.root}/bin/python")
    assert os.readlink(target_bin / "python3") == os.readlink(source_bin / "python3")
    assert slots.active_slot() == "1.0"


def test_install_launcher_keeps_pips_script_as_the_app(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)
    slots.clone_slot("1.0", "2.0")
    bin_dir = slots.slot_dir("2.0") / "bin"
    (bin_dir / "vibesensor-server").write_text("#!pip-generated\n", encoding="utf-8")

    slots.install_launcher("2.0")

    assert (bin_dir / SERVER_APP).read_text() == "#!pip-generated\n"
    launcher = bin_dir / "vibesensor-server"
    assert launcher.read_text().startswith(f"#!{bin_dir}/python3 -IS\n")
    assert os.access(launcher, os.X_OK)


def test_activate_arms_the_boot_check_then_switches(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)
    slots.clone_slot("1.0", "2.0")

    slots.activate("2.0", health_url="http://127.0.0.1:80/api/health")

    assert slots.active_slot() == "2.0"
    assert json.loads((slots.root / PENDING_FILE).read_text()) == {
        "candidate": "2.0",
        "previous": "1.0",
        "health_url": "http://127.0.0.1:80/api/health",
        "starts": 0,
        "deadline_s": 60.0,
    }
    pending = slots.pending_boot()
    assert pending is not None and pending.candidate == "2.0"


def test_prune_keeps_only_the_named_slot(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)
    slots.clone_slot("1.0", "2.0")
    slots.clone_slot("1.0", "3.0")

    slots.prune("2.0")

    assert sorted(p.name for p in (slots.root / "slots").iterdir()) == ["2.0"]


def test_take_reverted_returns_the_record_once(tmp_path: Path) -> None:
    slots = _adopted(tmp_path)
    (slots.root / REVERTED_FILE).write_text(
        json.dumps({"candidate": "2.0", "previous": "1.0", "reason": "boom", "at": 1.0}),
    )

    assert slots.take_reverted() == RevertedBoot(candidate="2.0", previous="1.0", reason="boom")
    assert slots.take_reverted() is None


def test_adopt_cli_names_the_slot_after_the_installed_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_legacy_venv(tmp_path / ".venv")
    monkeypatch.setattr("vibesensor.__version__", "2026.10.1")

    main(["adopt", str(root)])

    assert VenvSlots(root).active_slot() == "2026.10.1"
