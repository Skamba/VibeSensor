"""Guard: UI contract sync resolves CLI tools through package metadata."""

from __future__ import annotations

from tests._paths import REPO_ROOT

_SYNC_SCRIPT = REPO_ROOT / "tools" / "config" / "sync_shared_contracts_to_ui.mjs"


def test_ui_contract_sync_resolves_openapi_cli_via_package_metadata() -> None:
    script_text = _SYNC_SCRIPT.read_text()

    assert "openapi-typescript/package.json" in script_text
    assert "resolvePackageBinPath" in script_text
    assert "openapi-typescript/bin/cli.js" not in script_text
