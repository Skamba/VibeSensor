"""CLI/bootstrap main-entry coverage for port fallback and reload wiring."""

from __future__ import annotations

import errno
import os
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest


def _runtime_app(port: int):
    return SimpleNamespace(
        state=SimpleNamespace(
            runtime=SimpleNamespace(
                config=SimpleNamespace(server=SimpleNamespace(host="0.0.0.0", port=port)),
            ),
        ),
    )


def _run_main(monkeypatch, *, port: int, fail_port: int | None = None) -> list[int]:
    """Shared harness: patch app_module, call ``main()``, return recorded port calls."""
    from vibesensor.app import bootstrap as app_module

    monkeypatch.setattr(
        app_module.argparse.ArgumentParser,
        "parse_args",
        lambda self: Namespace(config=None, reload=False),
    )
    monkeypatch.setattr(app_module, "create_app", lambda config_path=None: _runtime_app(port))
    calls: list[int] = []

    def _fake_run(*args, **kwargs):
        calls.append(kwargs["port"])
        if fail_port is not None and kwargs["port"] == fail_port:
            raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(app_module.uvicorn, "run", _fake_run)
    app_module.main()
    return calls


@pytest.mark.parametrize(
    ("port", "fail_port", "expected_calls"),
    [
        pytest.param(80, 80, [80, 8000], id="fallback-on-bind-fail"),
        pytest.param(9000, None, [9000], id="configured-port-no-fallback"),
    ],
)
def test_main_port_behaviour(monkeypatch, port, fail_port, expected_calls) -> None:
    assert _run_main(monkeypatch, port=port, fail_port=fail_port) == expected_calls


def test_create_app_from_env_uses_exported_config_path(monkeypatch) -> None:
    from vibesensor.app import bootstrap as app_module

    config_path = Path("apps/server/config.dev.yaml")
    monkeypatch.setenv(app_module._CONFIG_PATH_ENV, str(config_path))
    seen: list[Path | None] = []
    monkeypatch.setattr(
        app_module,
        "create_app",
        lambda config_path=None: seen.append(config_path) or "app-object",
    )

    assert app_module.create_app_from_env() == "app-object"
    assert seen == [config_path]


def test_main_reload_uses_factory_target(monkeypatch, tmp_path) -> None:
    from vibesensor.app import bootstrap as app_module

    config_path = tmp_path / "config.dev.yaml"
    monkeypatch.setattr(
        app_module.argparse.ArgumentParser,
        "parse_args",
        lambda self: Namespace(config=config_path, reload=True),
    )
    monkeypatch.setattr(
        app_module,
        "load_config",
        lambda config_path=None: SimpleNamespace(
            server=SimpleNamespace(host="127.0.0.1", port=8000),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "create_app",
        lambda *args, **kwargs: pytest.fail("reload mode should not eagerly build the app object"),
    )
    calls: list[tuple[object, dict[str, object]]] = []

    def _fake_run(app_target, **kwargs):
        calls.append((app_target, kwargs))

    monkeypatch.setattr(app_module.uvicorn, "run", _fake_run)

    app_module.main()

    assert calls == [
        (
            "vibesensor.app.bootstrap:create_app_from_env",
            {
                "host": "127.0.0.1",
                "port": 8000,
                "log_level": "info",
                "loop": "asyncio",
                "reload": True,
                "factory": True,
            },
        ),
    ]
    assert os.environ[app_module._CONFIG_PATH_ENV] == str(config_path.resolve())
