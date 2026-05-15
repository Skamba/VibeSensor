"""Guard the manual Pi install script's Python runtime policy."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests._paths import SERVER_ROOT

_INSTALL_PI = SERVER_ROOT / "scripts" / "install_pi.sh"
_PYPROJECT = SERVER_ROOT / "pyproject.toml"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _prepare_install_pi_workspace(tmp_path: Path) -> Path:
    server_root = tmp_path / "server"
    scripts_dir = server_root / "scripts"
    scripts_dir.mkdir(parents=True)
    install_pi = scripts_dir / "install_pi.sh"
    install_pi.write_text(_INSTALL_PI.read_text(encoding="utf-8"), encoding="utf-8")
    install_pi.chmod(0o755)
    (server_root / "pyproject.toml").write_text(
        _PYPROJECT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return install_pi


def _write_fake_sudo(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "sudo",
        "\n".join(
            [
                "#!/bin/sh",
                'exec "$@"',
                "",
            ]
        ),
    )


def _write_fake_apt_get(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "apt-get",
        "\n".join(
            [
                f"#!{sys.executable}",
                "import sys",
                "sys.exit(0)",
                "",
            ]
        ),
    )


def _write_fake_python3(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "python3",
        "\n".join(
            [
                f"#!{sys.executable}",
                "import os",
                "import sys",
                "from pathlib import Path",
                "",
                "version = os.environ['FAKE_PYTHON_VERSION']",
                "python_log = Path(os.environ['FAKE_PYTHON_LOG'])",
                "with python_log.open('a', encoding='utf-8') as handle:",
                "    handle.write(' '.join(sys.argv[1:]) + '\\n')",
                "",
                "if sys.argv[1:2] == ['-c']:",
                "    print(version)",
                "    sys.exit(0)",
                "",
                "if sys.argv[1:3] == ['-m', 'venv'] and len(sys.argv) == 4:",
                "    venv_dir = Path(sys.argv[3])",
                "    bin_dir = venv_dir / 'bin'",
                "    bin_dir.mkdir(parents=True, exist_ok=True)",
                "    pip_path = bin_dir / 'pip'",
                "    pip_path.write_text(",
                "        '\\n'.join([",
                "            f'#!{sys.executable}',",
                "            'import os',",
                "            'import sys',",
                "            'from pathlib import Path',",
                "            \"log_path = Path(os.environ['FAKE_PIP_LOG'])\",",
                "            \"with log_path.open('a', encoding='utf-8') as handle:\",",
                "            \"    handle.write(' '.join(sys.argv[1:]) + '\\\\n')\",",
                "            \"sys.exit(int(os.environ['FAKE_PIP_EXIT_CODE']))\",",
                "            '',",
                "        ]),",
                "        encoding='utf-8',",
                "    )",
                "    pip_path.chmod(0o755)",
                "    sys.exit(0)",
                "",
                "raise SystemExit(f'unexpected fake python3 args: {sys.argv[1:]}')",
                "",
            ]
        ),
    )


def _run_install_pi(
    tmp_path: Path, *, python_version: str, pip_exit_code: int
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str], Path]:
    install_pi = _prepare_install_pi_workspace(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_log = tmp_path / "python.log"
    pip_log = tmp_path / "pip.log"
    _write_fake_sudo(bin_dir)
    _write_fake_apt_get(bin_dir)
    _write_fake_python3(bin_dir)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_PYTHON_VERSION": python_version,
        "FAKE_PYTHON_LOG": str(python_log),
        "FAKE_PIP_LOG": str(pip_log),
        "FAKE_PIP_EXIT_CODE": str(pip_exit_code),
    }
    result = subprocess.run(
        ["bash", str(install_pi)],
        cwd=install_pi.parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    python_calls = (
        python_log.read_text(encoding="utf-8").splitlines() if python_log.exists() else []
    )
    pip_calls = pip_log.read_text(encoding="utf-8").splitlines() if pip_log.exists() else []
    return result, python_calls, pip_calls, install_pi.parent.parent


def test_install_pi_fails_fast_when_python3_is_below_supported_floor(tmp_path: Path) -> None:
    result, python_calls, pip_calls, server_root = _run_install_pi(
        tmp_path,
        python_version="3.12.9",
        pip_exit_code=0,
    )

    assert result.returncode == 1
    assert "requires python3 >= 3.13" in result.stderr
    assert "docs/runtime_support_matrix.md" in result.stderr
    assert "pip install" not in result.stderr
    assert not any(call.startswith("-m venv ") for call in python_calls)
    assert pip_calls == []
    assert not (server_root / ".venv").exists()


def test_install_pi_reaches_venv_creation_with_supported_python(tmp_path: Path) -> None:
    result, python_calls, pip_calls, server_root = _run_install_pi(
        tmp_path,
        python_version="3.13.4",
        pip_exit_code=41,
    )

    assert result.returncode == 41
    assert f"-m venv {server_root / '.venv'}" in python_calls
    assert pip_calls == ["install --upgrade pip"]
    assert (server_root / ".venv" / "bin" / "pip").is_file()
