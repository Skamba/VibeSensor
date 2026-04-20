"""Guards for the native prerequisite checker."""

from __future__ import annotations

import importlib.util
import sys

from tests._paths import REPO_ROOT

_CHECK_PREREQUISITES = REPO_ROOT / "tools" / "dev" / "check_prerequisites.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "check_prerequisites_for_tests",
        _CHECK_PREREQUISITES,
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_CHECK_PREREQUISITES}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_docker_accepts_compose_v2_and_keeps_daemon_check(monkeypatch) -> None:
    module = _load_module()

    def _docker_only(command: str) -> str | None:
        return "/usr/bin/docker" if command == "docker" else None

    monkeypatch.setattr(module, "_which", _docker_only)

    def _fake_run(command: list[str]) -> tuple[bool, str]:
        if command == ["docker", "compose", "version"]:
            return True, "Docker Compose version v2.39.4\n"
        if command == ["docker", "info"]:
            return False, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n"
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(module, "_run", _fake_run)

    results = module._check_docker()

    assert [(item.name, item.status, item.message) for item in results] == [
        ("docker", "OK", "installed"),
        ("docker compose", "OK", "Docker Compose version v2.39.4"),
        (
            "docker daemon",
            "WARN",
            "not reachable: Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
        ),
    ]


def test_check_docker_requires_compose_v2_even_if_legacy_binary_exists(monkeypatch) -> None:
    module = _load_module()

    def _fake_which(command: str) -> str | None:
        if command == "docker":
            return "/usr/bin/docker"
        if command == "docker-compose":
            return "/usr/bin/docker-compose"
        return None

    def _fake_run(command: list[str]) -> tuple[bool, str]:
        if command == ["docker", "compose", "version"]:
            return False, "docker: 'compose' is not a docker command.\n"
        if command == ["docker", "info"]:
            return True, "Server Version: 28.0.0\n"
        if command == ["docker-compose", "version"]:
            raise AssertionError("legacy docker-compose should not be probed")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(module, "_which", _fake_which)
    monkeypatch.setattr(module, "_run", _fake_run)

    results = module._check_docker()

    assert [(item.name, item.status, item.message) for item in results] == [
        ("docker", "OK", "installed"),
        (
            "docker compose",
            "WARN",
            "v2 unavailable: docker: 'compose' is not a docker command.",
        ),
        ("docker daemon", "OK", "reachable"),
    ]
