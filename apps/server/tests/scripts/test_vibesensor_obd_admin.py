from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "vibesensor_obd_admin.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_vibesensor_obd_admin", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ensure_repo_venv_python_reexecs_when_sys_prefix_is_not_the_repo_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    target_python = tmp_path / ".venv" / "bin" / "python"
    target_python.parent.mkdir(parents=True)
    target_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "VENV_ROOT_CANDIDATES", (tmp_path / ".venv",))
    monkeypatch.setattr(module, "VENV_PYTHON_BASENAMES", ("python",))
    monkeypatch.setattr(module.sys, "prefix", "/usr")
    monkeypatch.setattr(module.sys, "argv", ["vibesensor_obd_admin.py", "scan"])

    execv_calls: list[tuple[str, list[str]]] = []

    def _fake_execv(executable: str, argv: list[str]) -> None:
        execv_calls.append((executable, argv))
        raise SystemExit(0)

    monkeypatch.setattr(module.os, "execv", _fake_execv)

    with pytest.raises(SystemExit, match="0"):
        module._ensure_repo_venv_python()

    assert module.sys.argv == ["vibesensor_obd_admin.py", "scan"]
    assert execv_calls == [
        (
            str(target_python),
            [str(target_python), "-m", "vibesensor.adapters.obd.admin_helper", "scan"],
        )
    ]


def test_ensure_repo_venv_python_accepts_symlinked_venv_when_sys_prefix_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    venv_root = tmp_path / ".venv"
    target_python = venv_root / "bin" / "python"
    target_python.parent.mkdir(parents=True)
    target_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "VENV_ROOT_CANDIDATES", (venv_root,))
    monkeypatch.setattr(module, "VENV_PYTHON_BASENAMES", ("python",))
    monkeypatch.setattr(module.sys, "prefix", str(venv_root))

    def _unexpected_execv(executable: str, argv: list[str]) -> None:
        raise AssertionError(f"os.execv should not be called: {executable} {argv}")

    monkeypatch.setattr(module.os, "execv", _unexpected_execv)

    module._ensure_repo_venv_python()
    assert module.sys.prefix == str(venv_root)


def test_find_repo_venv_python_falls_back_to_python3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    venv_root = tmp_path / ".venv"
    target_python = venv_root / "bin" / "python3"
    target_python.parent.mkdir(parents=True)
    target_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "VENV_ROOT_CANDIDATES", (venv_root,))
    monkeypatch.setattr(module, "VENV_PYTHON_BASENAMES", ("python", "python3"))

    assert module._find_repo_venv_python() == target_python
    assert target_python.name == "python3"


def test_ensure_repo_venv_python_reports_checked_candidates_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    venv_root = tmp_path / ".venv"

    monkeypatch.setattr(module, "VENV_ROOT_CANDIDATES", (venv_root,))
    monkeypatch.setattr(module, "VENV_PYTHON_BASENAMES", ("python", "python3"))

    with pytest.raises(SystemExit) as exc_info:
        module._ensure_repo_venv_python()

    message = str(exc_info.value)
    assert "Missing expected virtualenv interpreter" in message
    assert str(venv_root / "bin" / "python") in message
    assert str(venv_root / "bin" / "python3") in message
