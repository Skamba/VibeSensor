from __future__ import annotations

import errno
from argparse import Namespace
from types import SimpleNamespace

import pytest


def _runtime_app(port: int):
    return SimpleNamespace(
        state=SimpleNamespace(
            runtime=SimpleNamespace(
                config=SimpleNamespace(server=SimpleNamespace(host="0.0.0.0", port=port))
            )
        )
    )


def _run_main(monkeypatch, *, port: int, fail_port: int | None = None) -> list[int]:
    """Shared harness: patch app_module, call ``main()``, return recorded port calls."""
    monkeypatch.setenv("VIBESENSOR_DISABLE_AUTO_APP", "1")
    from vibesensor import app as app_module

    monkeypatch.setattr(
        app_module.argparse.ArgumentParser, "parse_args", lambda self: Namespace(config=None)
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
