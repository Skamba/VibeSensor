#!/usr/bin/env python3
"""Check local development prerequisites and workflow availability."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str


def _read_required_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _which(command: str) -> str | None:
    return shutil.which(command)


def _run(command: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = (proc.stdout or "").strip()
    return proc.returncode == 0, output


def _first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


def _python_matches_expected(actual: str, expected: str) -> bool:
    expected_parts = expected.split(".")
    if len(expected_parts) >= 3:
        return actual == expected
    return actual.startswith(f"{expected}.")


def _python_candidates(expected_version: str) -> list[str]:
    expected_parts = expected_version.split(".")
    candidates = [str(ROOT / ".venv" / "bin" / "python")]
    if len(expected_parts) >= 2:
        candidates.append(f"python{expected_parts[0]}.{expected_parts[1]}")
    candidates.extend(["python3", "python"])

    seen: set[str] = set()
    unique_candidates: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate)
    return unique_candidates


def _check_python(expected_version: str) -> CheckResult:
    candidate_errors: list[tuple[str, str]] = []
    for candidate in _python_candidates(expected_version):
        candidate_path = Path(candidate)
        resolved = (
            str(candidate_path) if candidate_path.is_absolute() else _which(candidate)
        )
        if resolved is None:
            continue
        ok, output = _run(
            [
                resolved,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
            ]
        )
        if not ok:
            candidate_errors.append(
                (candidate, f"unable to read version: {_first_line(output)}")
            )
            continue
        actual = output.strip()
        if _python_matches_expected(actual, expected_version):
            return CheckResult(candidate, "OK", f"{actual} (matches .python-version)")
        candidate_errors.append(
            (
                candidate,
                f"found {actual}; expected {expected_version} (see .python-version)",
            )
        )

    if not candidate_errors:
        return CheckResult(
            "python",
            "FAIL",
            f"missing (expected {expected_version} from .python-version)",
        )

    candidate, message = candidate_errors[0]
    return CheckResult(candidate, "FAIL", message)


def _check_node(expected_major: str) -> CheckResult:
    if _which("node") is None:
        return CheckResult(
            "node", "FAIL", f"missing (expected {expected_major}.x from .nvmrc)"
        )
    ok, output = _run(["node", "--version"])
    if not ok:
        return CheckResult(
            "node", "FAIL", f"unable to read version: {_first_line(output)}"
        )
    actual = output.lstrip("v").strip()
    if not actual.startswith(f"{expected_major}."):
        return CheckResult(
            "node",
            "FAIL",
            f"found {actual}; expected {expected_major}.x (see .nvmrc)",
        )
    return CheckResult("node", "OK", f"v{actual} (matches .nvmrc)")


def _check_npm() -> CheckResult:
    if _which("npm") is None:
        return CheckResult("npm", "FAIL", "missing")
    ok, output = _run(["npm", "--version"])
    if not ok:
        return CheckResult(
            "npm", "FAIL", f"unable to read version: {_first_line(output)}"
        )
    return CheckResult("npm", "OK", output.strip())


def _check_docker() -> list[CheckResult]:
    results: list[CheckResult] = []
    if _which("docker") is None:
        return [
            CheckResult(
                "docker", "WARN", "missing (Docker quick-start/dev mode unavailable)"
            ),
            CheckResult(
                "docker compose", "WARN", "unavailable because docker is missing"
            ),
        ]

    results.append(CheckResult("docker", "OK", "installed"))

    compose_ok, compose_output = _run(["docker", "compose", "version"])
    if compose_ok:
        results.append(CheckResult("docker compose", "OK", _first_line(compose_output)))
    else:
        results.append(
            CheckResult(
                "docker compose",
                "WARN",
                f"v2 unavailable: {_first_line(compose_output)}",
            )
        )

    daemon_ok, daemon_output = _run(["docker", "info"])
    if daemon_ok:
        results.append(CheckResult("docker daemon", "OK", "reachable"))
    else:
        results.append(
            CheckResult(
                "docker daemon",
                "WARN",
                f"not reachable: {_first_line(daemon_output)}",
            )
        )
    return results


def _check_platformio() -> CheckResult:
    if _which("pio") is None:
        return CheckResult(
            "platformio", "WARN", "missing (only needed for firmware work)"
        )
    ok, output = _run(["pio", "--version"])
    if not ok:
        return CheckResult(
            "platformio", "WARN", f"installed but unhealthy: {_first_line(output)}"
        )
    match = re.search(r"\bversion\s+([0-9.]+)", output, re.IGNORECASE)
    version = match.group(1) if match else _first_line(output)
    return CheckResult("platformio", "OK", version)


def _print_section(title: str, results: list[CheckResult]) -> None:
    print(title)
    for result in results:
        print(f"  [{result.status}] {result.name}: {result.message}")


def main() -> int:
    expected_python = _read_required_text(ROOT / ".python-version")
    expected_node = _read_required_text(ROOT / ".nvmrc")

    core_results = [
        _check_python(expected_python),
        _check_node(expected_node),
        _check_npm(),
    ]
    docker_results = _check_docker()
    firmware_results = [_check_platformio()]

    _print_section("Core development prerequisites:", core_results)
    print()
    _print_section("Docker workflow availability:", docker_results)
    print()
    _print_section("Firmware workflow availability:", firmware_results)
    print()

    core_failures = [result for result in core_results if result.status == "FAIL"]
    warnings = [
        result
        for result in [*core_results, *docker_results, *firmware_results]
        if result.status == "WARN"
    ]

    if core_failures:
        print(
            "doctor failed: fix the core development prerequisites above before continuing."
        )
        return 1

    if warnings:
        print(
            "doctor passed with warnings: the native Python + Vite workflow is available, but some optional paths are not ready."
        )
        return 0

    print("doctor passed: the native and Docker development workflows are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
