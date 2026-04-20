"""Granian runtime wiring coverage for backend startup."""

from __future__ import annotations

from granian.constants import Interfaces, Loops
from granian.log import LogLevels


def test_granian_loop_uses_uvloop_on_linux(monkeypatch) -> None:
    from vibesensor.app import bootstrap as app_module

    monkeypatch.setattr(app_module.sys, "platform", "linux")

    assert app_module._granian_loop() is Loops.uvloop


def test_granian_loop_uses_asyncio_off_linux(monkeypatch) -> None:
    from vibesensor.app import bootstrap as app_module

    monkeypatch.setattr(app_module.sys, "platform", "darwin")

    assert app_module._granian_loop() is Loops.asyncio


def test_run_server_uses_granian_with_expected_options(monkeypatch) -> None:
    from vibesensor.app import bootstrap as app_module

    recorded: dict[str, object] = {}

    class FakeGranian:
        def __init__(self, *args, **kwargs):
            recorded["args"] = args
            recorded["kwargs"] = kwargs

        def serve(self) -> None:
            recorded["served"] = True

    monkeypatch.setattr(app_module, "Granian", FakeGranian)
    monkeypatch.setattr(app_module, "_granian_loop", lambda: Loops.uvloop)

    app_module._run_server(
        "vibesensor.app.bootstrap:create_app_from_env",
        host="127.0.0.1",
        port=8000,
        reload=True,
        factory=True,
    )

    assert recorded == {
        "args": ("vibesensor.app.bootstrap:create_app_from_env",),
        "kwargs": {
            "address": "127.0.0.1",
            "port": 8000,
            "interface": Interfaces.ASGI,
            "log_enabled": True,
            "log_level": LogLevels.info,
            "loop": Loops.uvloop,
            "reload": True,
            "factory": True,
        },
        "served": True,
    }
