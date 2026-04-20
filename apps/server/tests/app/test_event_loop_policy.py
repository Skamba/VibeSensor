"""Event-loop policy coverage for backend startup."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import yaml


def _write_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "history_db_path": str(tmp_path / "history.db"),
                },
            },
        ),
        encoding="utf-8",
    )
    return cfg_path


def test_install_runtime_event_loop_policy_uses_uvloop_on_linux(monkeypatch) -> None:
    from vibesensor.app import bootstrap as app_module

    class FakeUvloopPolicy(asyncio.DefaultEventLoopPolicy):
        pass

    FakeUvloopPolicy.__module__ = "uvloop"

    recorded: list[asyncio.AbstractEventLoopPolicy] = []
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(
        app_module.asyncio,
        "get_event_loop_policy",
        lambda: asyncio.DefaultEventLoopPolicy(),
    )
    monkeypatch.setattr(
        app_module.asyncio,
        "set_event_loop_policy",
        lambda policy: recorded.append(policy),
    )
    fake_uvloop = type(
        "FakeUvloopModule",
        (),
        {"EventLoopPolicy": FakeUvloopPolicy},
    )
    monkeypatch.setitem(sys.modules, "uvloop", fake_uvloop)

    app_module._install_runtime_event_loop_policy()

    assert len(recorded) == 1
    assert isinstance(recorded[0], FakeUvloopPolicy)


def test_install_runtime_event_loop_policy_skips_non_linux(monkeypatch) -> None:
    from vibesensor.app import bootstrap as app_module

    called = {"set": False}
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        app_module.asyncio,
        "set_event_loop_policy",
        lambda policy: called.__setitem__("set", True),
    )

    app_module._install_runtime_event_loop_policy()

    assert called["set"] is False


def test_create_app_installs_runtime_event_loop_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_path = _write_config(tmp_path)
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    from vibesensor import app as app_module
    from vibesensor.app import bootstrap as bootstrap_mod

    calls: list[str] = []
    monkeypatch.setattr(
        bootstrap_mod,
        "_install_runtime_event_loop_policy",
        lambda: calls.append("install"),
    )

    app_module.create_app(config_path=cfg_path)

    assert calls == ["install"]
