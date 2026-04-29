"""Granian main-entry coverage for platform loop selection."""

from __future__ import annotations

import logging
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from granian.constants import Interfaces, Loops
from granian.log import LogLevels


def _loaded_config(*, host: str, port: int) -> SimpleNamespace:
    return SimpleNamespace(
        server=SimpleNamespace(host=host, port=port),
        logging=SimpleNamespace(app_log_path=None),
        tracing=SimpleNamespace(enabled=False, output_path=Path("/tmp/traces.jsonl")),
    )


def _run_with_restored_root_logging(callable_obj) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    try:
        callable_obj()
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            if handler not in original_handlers:
                handler.close()
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def _run_main_for_platform(monkeypatch, *, platform: str) -> dict[str, object]:
    from vibesensor.app import bootstrap as app_module

    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        app_module.argparse.ArgumentParser,
        "parse_args",
        lambda self: Namespace(config=None, reload=False),
    )
    monkeypatch.setattr(
        app_module,
        "load_config",
        lambda config_path=None: _loaded_config(host="127.0.0.1", port=8000),
    )
    monkeypatch.setattr(app_module, "export_config_path_env", lambda config_path: None)
    monkeypatch.setattr(app_module.sys, "platform", platform)
    if platform.startswith("linux"):
        monkeypatch.setitem(sys.modules, "uvloop", SimpleNamespace(new_event_loop=lambda: None))

    class FakeGranian:
        def __init__(self, *args, **kwargs):
            recorded["args"] = args
            recorded["kwargs"] = kwargs

        def serve(self) -> None:
            recorded["served"] = True

    monkeypatch.setattr(app_module, "Granian", FakeGranian)
    _run_with_restored_root_logging(app_module.main)
    return recorded


def test_main_uses_uvloop_on_linux(monkeypatch) -> None:
    recorded = _run_main_for_platform(monkeypatch, platform="linux")

    assert recorded == {
        "args": ("vibesensor.app.bootstrap:create_app_from_env",),
        "kwargs": {
            "address": "127.0.0.1",
            "port": 8000,
            "interface": Interfaces.ASGI,
            "log_enabled": True,
            "log_level": LogLevels.info,
            "loop": Loops.uvloop,
            "reload": False,
            "factory": True,
        },
        "served": True,
    }


def test_main_uses_asyncio_off_linux(monkeypatch) -> None:
    recorded = _run_main_for_platform(monkeypatch, platform="darwin")

    assert recorded == {
        "args": ("vibesensor.app.bootstrap:create_app_from_env",),
        "kwargs": {
            "address": "127.0.0.1",
            "port": 8000,
            "interface": Interfaces.ASGI,
            "log_enabled": True,
            "log_level": LogLevels.info,
            "loop": Loops.asyncio,
            "reload": False,
            "factory": True,
        },
        "served": True,
    }
