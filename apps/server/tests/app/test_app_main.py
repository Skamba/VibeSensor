from __future__ import annotations

import errno
from argparse import Namespace
from types import SimpleNamespace


def _runtime_app(port: int):
    return SimpleNamespace(
        state=SimpleNamespace(
            runtime=SimpleNamespace(
                config=SimpleNamespace(server=SimpleNamespace(host="0.0.0.0", port=port))
            )
        )
    )


def test_main_falls_back_to_8000_when_port_80_bind_fails(monkeypatch) -> None:
    monkeypatch.setenv("VIBESENSOR_DISABLE_AUTO_APP", "1")
    from vibesensor import app as app_module

    monkeypatch.setattr(
        app_module.argparse.ArgumentParser, "parse_args", lambda self: Namespace(config=None)
    )
    monkeypatch.setattr(app_module, "create_app", lambda config_path=None: _runtime_app(80))
    calls: list[int] = []

    def _fake_run(*args, **kwargs):
        calls.append(kwargs["port"])
        if kwargs["port"] == 80:
            raise OSError(errno.EACCES, "permission denied")
        return None

    monkeypatch.setattr(app_module.uvicorn, "run", _fake_run)

    app_module.main()

    assert calls == [80, 8000]


def test_main_uses_configured_non_default_port_without_fallback(monkeypatch) -> None:
    monkeypatch.setenv("VIBESENSOR_DISABLE_AUTO_APP", "1")
    from vibesensor import app as app_module

    monkeypatch.setattr(
        app_module.argparse.ArgumentParser, "parse_args", lambda self: Namespace(config=None)
    )
    monkeypatch.setattr(app_module, "create_app", lambda config_path=None: _runtime_app(9000))
    calls: list[int] = []

    def _fake_run(*args, **kwargs):
        calls.append(kwargs["port"])
        return None

    monkeypatch.setattr(app_module.uvicorn, "run", _fake_run)

    app_module.main()

    assert calls == [9000]
