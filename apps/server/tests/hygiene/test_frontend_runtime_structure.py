from __future__ import annotations

from pathlib import Path

from _paths import REPO_ROOT


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ui_runtime_is_a_thin_composition_root() -> None:
    ui_runtime = REPO_ROOT / "apps" / "ui" / "src" / "app" / "ui_app_runtime.ts"
    source = _read(ui_runtime)

    assert 'from "./runtime/ui_shell_controller"' in source
    assert 'from "./runtime/ui_live_transport_controller"' in source
    assert 'from "./runtime/ui_spectrum_controller"' in source

    forbidden_imports = (
        'from "../ws"',
        'from "../server_payload"',
        'from "../spectrum"',
        'from "../vehicle_math"',
        'from "../i18n"',
        'from "uplot"',
    )
    for forbidden in forbidden_imports:
        assert forbidden not in source, (
            "UiAppRuntime should stay a composition root after the runtime split; "
            f"found low-level import {forbidden!r} in {ui_runtime}"
        )

    line_count = len(source.splitlines())
    assert line_count <= 180, (
        f"UiAppRuntime should stay compact after the refactor, got {line_count} lines"
    )


def test_frontend_runtime_controllers_exist() -> None:
    runtime_dir = REPO_ROOT / "apps" / "ui" / "src" / "app" / "runtime"
    expected = {
        "ui_shell_controller.ts",
        "ui_live_transport_controller.ts",
        "ui_spectrum_controller.ts",
    }
    existing = {path.name for path in runtime_dir.glob("*.ts")}
    missing = expected - existing
    assert not missing, f"Missing frontend runtime controllers: {sorted(missing)}"
