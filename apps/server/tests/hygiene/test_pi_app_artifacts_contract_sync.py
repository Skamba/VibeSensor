"""Guard the Pi app-artifact UI build contract-sync step."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_APP_ARTIFACTS_SCRIPT = REPO_ROOT / "infra/pi-image/pi-gen/lib/app_artifacts.sh"


def test_build_ui_bundle_syncs_generated_contracts_before_build(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ui_dir = repo / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    server_static_dir = repo / "apps" / "server" / "vibesensor" / "static"
    server_static_dir.mkdir(parents=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "npm-commands.log"
    fake_npm = fake_bin / "npm"
    fake_npm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_NPM_LOG}"
case "$*" in
  "ci")
    mkdir -p node_modules
    ;;
  "run sync:generated-contracts")
    mkdir -p src/generated
    : > src/generated/http_api_contracts.ts
    ;;
  "run build")
    mkdir -p dist
    printf '<!doctype html>\n' > dist/index.html
    ;;
  *)
    echo "unexpected npm invocation: $*" >&2
    exit 1
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)

    env = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_NPM_LOG": str(command_log),
        "VS_PYTHON_BIN": sys.executable,
    }
    subprocess.run(
        [
            "bash",
            "-c",
            (
                "set -euo pipefail; "
                f"source {shlex.quote(str(_APP_ARTIFACTS_SCRIPT))}; "
                f"REPO_ROOT={shlex.quote(str(repo))}; "
                "FORCE_UI_BUILD=0; "
                f"UI_HASH_FILE={shlex.quote(str(tmp_path / 'ui.hash'))}; "
                "build_ui_bundle"
            ),
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "ci",
        "run sync:generated-contracts",
        "run build",
    ]
    assert (server_static_dir / "index.html").read_text(encoding="utf-8") == "<!doctype html>\n"
