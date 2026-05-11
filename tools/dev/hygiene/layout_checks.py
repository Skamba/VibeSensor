# ruff: noqa: F403,F405
"""Test sizing, ownership, and marker policy checks."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from ._shared import *
from .repo_sync import _git_tracked_files


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))


def _is_tracked_test_file(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if _OVERSIZED_TEST_IGNORED_PARTS.intersection(path.parts):
        return False
    suffix = path.suffix.lower()
    if rel.startswith("apps/server/tests/") or rel.startswith("apps/server/tests_e2e/"):
        return suffix == ".py"
    if rel.startswith("apps/ui/tests/"):
        return suffix in _OVERSIZED_TEST_UI_SUFFIXES
    return False


def _load_oversized_test_allowlist() -> tuple[int, int, dict[str, str], list[str]]:
    errors: list[str] = []
    if not _OVERSIZED_TEST_ALLOWLIST_PATH.exists():
        return (
            _OVERSIZED_TEST_DEFAULT_LIMIT,
            _OVERSIZED_TEST_DEFAULT_REPORT_LIMIT,
            {},
            [
                f"Missing oversized-test allowlist at {_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)}."
            ],
        )

    loaded = yaml.safe_load(_OVERSIZED_TEST_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        return (
            _OVERSIZED_TEST_DEFAULT_LIMIT,
            _OVERSIZED_TEST_DEFAULT_REPORT_LIMIT,
            {},
            [
                f"{_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} must load as a mapping."
            ],
        )

    raw_threshold = loaded.get("threshold_lines", _OVERSIZED_TEST_DEFAULT_LIMIT)
    raw_report_limit = loaded.get("report_limit", _OVERSIZED_TEST_DEFAULT_REPORT_LIMIT)
    threshold = (
        int(raw_threshold)
        if isinstance(raw_threshold, int) and raw_threshold > 0
        else _OVERSIZED_TEST_DEFAULT_LIMIT
    )
    report_limit = (
        int(raw_report_limit)
        if isinstance(raw_report_limit, int) and raw_report_limit > 0
        else _OVERSIZED_TEST_DEFAULT_REPORT_LIMIT
    )
    if threshold != raw_threshold:
        errors.append(
            f"{_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} must set threshold_lines to a positive integer."
        )
    if report_limit != raw_report_limit:
        errors.append(
            f"{_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} must set report_limit to a positive integer."
        )

    allowlist: dict[str, str] = {}
    raw_allowlist = loaded.get("allowlist")
    if not isinstance(raw_allowlist, Mapping):
        errors.append(
            f"{_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} must define allowlist as a mapping of path -> reason."
        )
        return threshold, report_limit, allowlist, errors

    for raw_path, raw_reason in raw_allowlist.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(
                f"{_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} contains a non-string allowlist path."
            )
            continue
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            errors.append(
                f"{raw_path} in {_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} must include a non-empty reason."
            )
            continue
        allowlist[raw_path] = raw_reason.strip()
    return threshold, report_limit, allowlist, errors


def check_oversized_test_files() -> tuple[list[str], list[str]]:
    threshold, report_limit, allowlist, errors = _load_oversized_test_allowlist()
    tracked_test_files = [
        path for path in _git_tracked_files() if _is_tracked_test_file(path)
    ]
    line_counts = {
        path.relative_to(ROOT).as_posix(): _line_count(path)
        for path in tracked_test_files
    }
    oversized = {
        rel_path: count for rel_path, count in line_counts.items() if count >= threshold
    }

    stale_allowlist = sorted(set(allowlist) - set(line_counts))
    if stale_allowlist:
        errors.append(
            f"{_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} contains missing or untracked files: {', '.join(stale_allowlist)}"
        )

    for rel_path, reason in allowlist.items():
        line_count = line_counts.get(rel_path)
        if line_count is None:
            continue
        if line_count < threshold:
            errors.append(
                f"{rel_path} is allowlisted in {_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} but is only {line_count} lines (limit {threshold}); remove the stale entry."
            )
        if not reason:
            errors.append(
                f"{rel_path} in {_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} must keep a non-empty reason."
            )

    for rel_path, line_count in sorted(
        oversized.items(), key=lambda item: (-item[1], item[0])
    ):
        if rel_path not in allowlist:
            errors.append(
                f"{rel_path} is {line_count} lines (limit {threshold}); split it or add it to {_OVERSIZED_TEST_ALLOWLIST_PATH.relative_to(ROOT)} with a reason."
            )

    report = [
        f"{rel_path} ({line_count} lines{' - allowlisted' if rel_path in allowlist else ''})"
        for rel_path, line_count in sorted(
            line_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:report_limit]
    ]
    return errors, report


def _config_array_literal(config_path: Path, key: str) -> list[str]:
    config_text = config_path.read_text(encoding="utf-8")
    match = re.search(rf"{key}:\s*(\[[^\]]+\])", config_text)
    if match is None:
        raise ValueError(
            f"{config_path.relative_to(ROOT)} is missing a {key} array literal."
        )
    normalized_literal = re.sub(r"//.*", "", match.group(1))
    try:
        parsed = ast.literal_eval(normalized_literal)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(
            f"{config_path.relative_to(ROOT)} has an unreadable {key} array literal."
        ) from exc
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) for item in parsed
    ):
        raise ValueError(
            f"{config_path.relative_to(ROOT)} must define {key} as a list of strings."
        )
    return [str(pattern) for pattern in parsed]


def _config_string_literal(config_path: Path, key: str) -> str:
    config_text = config_path.read_text(encoding="utf-8")
    match = re.search(rf'{key}:\s*"([^"]+)"', config_text)
    if match is None:
        raise ValueError(
            f'{config_path.relative_to(ROOT)} is missing a "{key}" string literal.'
        )
    return str(match.group(1))


def _resolve_ui_globs(*patterns: str) -> set[str]:
    resolved: set[str] = set()
    for pattern in patterns:
        for path in _UI_ROOT.glob(pattern):
            if path.is_file():
                resolved.add(path.relative_to(_UI_ROOT).as_posix())
    return resolved


def _resolve_playwright_specs(config_path: Path) -> set[str]:
    test_dir = _config_string_literal(config_path, "testDir")
    test_match_patterns = _config_array_literal(config_path, "testMatch")
    return _resolve_ui_globs(
        *(f"{test_dir}/{pattern}" for pattern in test_match_patterns)
    )


def all_ui_specs() -> set[str]:
    return {
        path.relative_to(_UI_ROOT).as_posix()
        for path in _UI_TESTS_DIR.glob("**/*.spec.ts")
        if path.is_file()
    }


def ui_runner_owned_specs() -> dict[str, set[str]]:
    vitest_include = _resolve_ui_globs(
        *_config_array_literal(_UI_VITEST_CONFIG, "include")
    )
    vitest_exclude = _resolve_ui_globs(
        *_config_array_literal(_UI_VITEST_CONFIG, "exclude")
    )
    return {
        "vitest": vitest_include - vitest_exclude,
        "playwright-smoke": _resolve_playwright_specs(_UI_PLAYWRIGHT_SMOKE_CONFIG),
        "playwright-regression": _resolve_playwright_specs(
            _UI_PLAYWRIGHT_REGRESSION_CONFIG
        ),
        "playwright-mock-smoke": _resolve_playwright_specs(
            _UI_PLAYWRIGHT_MOCK_SMOKE_CONFIG
        ),
        "playwright-visual": _resolve_playwright_specs(_UI_PLAYWRIGHT_VISUAL_CONFIG),
    }


def _load_test_inventory_allowlist() -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    if not _TEST_INVENTORY_ALLOWLIST_PATH.exists():
        return (
            {},
            [
                f"Missing test-inventory allowlist at {_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)}."
            ],
        )

    loaded = yaml.safe_load(_TEST_INVENTORY_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        return (
            {},
            [
                f"{_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} must load as a mapping."
            ],
        )

    allowlist: dict[str, str] = {}
    raw_allowlist = loaded.get("allowlist")
    if not isinstance(raw_allowlist, Mapping):
        errors.append(
            f"{_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} must define allowlist as a mapping of path -> reason."
        )
        return allowlist, errors

    for raw_path, raw_reason in raw_allowlist.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(
                f"{_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} contains a non-string allowlist path."
            )
            continue
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            errors.append(
                f"{raw_path} in {_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} must include a non-empty reason."
            )
            continue
        rel_path = raw_path.strip()
        candidate = Path(rel_path)
        if candidate.suffix != ".py" or not candidate.name.startswith("benchmark_"):
            errors.append(
                f"{rel_path} in {_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} must point to a benchmark_*.py script."
            )
            continue
        allowlist[rel_path] = raw_reason.strip()

    stale_allowlist = sorted(
        rel_path for rel_path in allowlist if not (ROOT / rel_path).is_file()
    )
    if stale_allowlist:
        errors.append(
            f"{_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} contains missing files: {', '.join(stale_allowlist)}"
        )
    return allowlist, errors


def _is_test_inventory_candidate(rel_path: str) -> bool:
    path = Path(rel_path)
    name = path.name
    if rel_path.startswith("apps/server/vibesensor/"):
        return False
    if name.startswith("test_") and path.suffix == ".py":
        return True
    if rel_path.endswith(".spec.ts"):
        return True
    if name.startswith("benchmark_") and path.suffix == ".py":
        return True
    if rel_path.startswith("firmware/esp/test/") and name == "test_main.cpp":
        return True
    return False


def _test_inventory_candidates() -> list[str]:
    candidates: set[str] = set()
    for path in _git_tracked_files():
        rel_path = path.relative_to(ROOT).as_posix()
        if _is_test_inventory_candidate(rel_path):
            candidates.add(rel_path)
    return sorted(candidates)


def _test_inventory_owners(
    rel_path: str,
    *,
    ui_runner_specs: Mapping[str, set[str]],
    benchmark_allowlist: Mapping[str, str],
) -> tuple[str, ...]:
    owners: list[str] = []
    name = Path(rel_path).name
    if rel_path.endswith(".spec.ts"):
        if rel_path.startswith("apps/ui/"):
            ui_rel_path = rel_path.removeprefix("apps/ui/")
            owners.extend(
                runner_name
                for runner_name, owned_specs in ui_runner_specs.items()
                if ui_rel_path in owned_specs
            )
        return tuple(sorted(owners))
    if name.startswith("test_") and rel_path.endswith(".py"):
        if rel_path.startswith("apps/server/tests/"):
            owners.append("backend-pytest")
        elif rel_path.startswith("apps/server/tests_e2e/"):
            owners.append("e2e-pytest")
        return tuple(owners)
    if name.startswith("benchmark_") and rel_path.endswith(".py"):
        if rel_path.startswith("apps/server/tests/"):
            owners.append("backend-pytest-benchmark")
        if rel_path in benchmark_allowlist:
            owners.append("allowlisted-benchmark-script")
        return tuple(owners)
    if rel_path.startswith("firmware/esp/test/") and name == "test_main.cpp":
        owners.append("firmware-native")
    return tuple(owners)


def _test_inventory_guidance(rel_path: str) -> str:
    name = Path(rel_path).name
    if rel_path.endswith(".spec.ts"):
        return (
            "Move it under apps/ui/tests/ and update apps/ui/vitest.config.ts or the "
            "Playwright testMatch config in apps/ui/playwright.smoke.config.ts, "
            "apps/ui/playwright.regression.config.ts, apps/ui/playwright.smoke.msw.config.ts, "
            "or apps/ui/playwright.config.ts so exactly one UI runner owns it."
        )
    if name.startswith("test_") and rel_path.endswith(".py"):
        return (
            "Move it under apps/server/tests/ or apps/server/tests_e2e/ so pytest owns "
            "it, or rename it if it is a helper module."
        )
    if name.startswith("benchmark_") and rel_path.endswith(".py"):
        return (
            "Move it under apps/server/tests/**/benchmark_*.py so the explicit "
            f"pytest-benchmark lane owns it, or document it in "
            f"{_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} as an intentional "
            "standalone benchmark script."
        )
    if rel_path.startswith("firmware/esp/test/") and name == "test_main.cpp":
        return (
            "Keep firmware native suites under firmware/esp/test/<suite>/test_main.cpp "
            "so the PlatformIO native runner can collect them."
        )
    return "Rename it if it is a helper module, or wire it into an owned test runner."


def inventory_errors_for_test_paths(
    candidate_paths: Sequence[str],
    *,
    ui_runner_specs: Mapping[str, set[str]] | None = None,
    benchmark_allowlist: Mapping[str, str] | None = None,
) -> list[str]:
    resolved_ui_runner_specs = (
        dict(ui_runner_specs)
        if ui_runner_specs is not None
        else ui_runner_owned_specs()
    )
    resolved_benchmark_allowlist = (
        dict(benchmark_allowlist) if benchmark_allowlist is not None else {}
    )

    errors: list[str] = []
    for rel_path in sorted(set(candidate_paths)):
        if not _is_test_inventory_candidate(rel_path):
            continue
        owners = _test_inventory_owners(
            rel_path,
            ui_runner_specs=resolved_ui_runner_specs,
            benchmark_allowlist=resolved_benchmark_allowlist,
        )
        if rel_path.endswith(".spec.ts") and len(owners) > 1:
            errors.append(
                f"{rel_path} is owned by multiple UI runners {list(owners)}; tighten "
                "apps/ui/vitest.config.ts include/exclude or the Playwright "
                "testMatch patterns so exactly one runner owns it."
            )
            continue
        if not owners:
            errors.append(
                f"{rel_path} looks like a test but is not owned by any configured runner; "
                f"{_test_inventory_guidance(rel_path)}"
            )
    return errors


def check_test_inventory_ownership() -> list[str]:
    benchmark_allowlist, allowlist_errors = _load_test_inventory_allowlist()
    errors = list(allowlist_errors)

    try:
        runner_specs = ui_runner_owned_specs()
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    errors.extend(
        inventory_errors_for_test_paths(
            _test_inventory_candidates(),
            ui_runner_specs=runner_specs,
            benchmark_allowlist=benchmark_allowlist,
        )
    )

    for rel_path in sorted(benchmark_allowlist):
        runner_owners = _test_inventory_owners(
            rel_path,
            ui_runner_specs=runner_specs,
            benchmark_allowlist={},
        )
        if runner_owners:
            errors.append(
                f"{rel_path} is listed in {_TEST_INVENTORY_ALLOWLIST_PATH.relative_to(ROOT)} "
                f"but is already owned by {list(runner_owners)}; remove the stale allowlist entry."
            )

    return errors


def _is_pytest_mark(expr: ast.expr, marker: str) -> bool:
    if isinstance(expr, ast.Call):
        return _is_pytest_mark(expr.func, marker)
    if not isinstance(expr, ast.Attribute) or expr.attr != marker:
        return False
    base = expr.value
    return (
        isinstance(base, ast.Attribute)
        and base.attr == "mark"
        and isinstance(base.value, ast.Name)
        and base.value.id == "pytest"
    )


def _pytestmark_values(statements: Sequence[ast.stmt]) -> list[ast.expr]:
    values: list[ast.expr] = []
    for stmt in statements:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in stmt.targets
        ):
            continue
        raw_value = stmt.value
        if isinstance(raw_value, (ast.List, ast.Tuple)):
            values.extend(raw_value.elts)
        else:
            values.append(raw_value)
    return values


def _marker_policy_test_files() -> list[Path]:
    files: list[Path] = []
    for path in _git_tracked_files():
        if not path.exists():
            continue
        rel_path = path.relative_to(ROOT).as_posix()
        if path.suffix != ".py":
            continue
        if rel_path.startswith("apps/server/tests/") or rel_path.startswith(
            "apps/server/tests_e2e/"
        ):
            files.append(path)
    return sorted(files)


def _collect_test_marker_usage() -> tuple[dict[str, dict[str, set[str]]], list[str]]:
    errors: list[str] = []
    usage: dict[str, dict[str, set[str]]] = {}

    for path in _marker_policy_test_files():
        rel_path = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            errors.append(
                f"{rel_path} could not be parsed for marker policy checks: {exc}"
            )
            continue

        file_usage = {marker: set() for marker in _MARKER_POLICY_MARKERS}

        for expr in _pytestmark_values(tree.body):
            for marker in _MARKER_POLICY_MARKERS:
                if _is_pytest_mark(expr, marker):
                    file_usage[marker].add(_MARKER_POLICY_NODE_MODULE)

        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for marker in _MARKER_POLICY_MARKERS:
                    if any(_is_pytest_mark(dec, marker) for dec in stmt.decorator_list):
                        file_usage[marker].add(stmt.name)
                continue

            if not isinstance(stmt, ast.ClassDef):
                continue

            for marker in _MARKER_POLICY_MARKERS:
                if any(_is_pytest_mark(dec, marker) for dec in stmt.decorator_list):
                    file_usage[marker].add(stmt.name)

            for expr in _pytestmark_values(stmt.body):
                for marker in _MARKER_POLICY_MARKERS:
                    if _is_pytest_mark(expr, marker):
                        file_usage[marker].add(stmt.name)

            for child in stmt.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                node_id = f"{stmt.name}::{child.name}"
                for marker in _MARKER_POLICY_MARKERS:
                    if any(
                        _is_pytest_mark(dec, marker) for dec in child.decorator_list
                    ):
                        file_usage[marker].add(node_id)

        usage[rel_path] = {
            marker: nodes for marker, nodes in file_usage.items() if nodes
        }

    return usage, errors


def _load_marker_node_allowlist_section(
    loaded: Mapping[str, object],
    key: str,
) -> tuple[dict[tuple[str, str], str], list[str]]:
    errors: list[str] = []
    section = loaded.get(key)
    allowlist: dict[tuple[str, str], str] = {}
    if not isinstance(section, Mapping):
        return allowlist, [
            f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} must define {key} as a mapping of file path -> node id -> reason."
        ]

    for raw_path, raw_nodes in section.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(
                f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} contains a non-string {key} file path."
            )
            continue
        rel_path = raw_path.strip()
        if not isinstance(raw_nodes, Mapping):
            errors.append(
                f"{rel_path} in {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)}::{key} must map node ids to reasons."
            )
            continue
        for raw_node, raw_reason in raw_nodes.items():
            if not isinstance(raw_node, str) or not raw_node.strip():
                errors.append(
                    f"{rel_path} in {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)}::{key} contains a non-string node id."
                )
                continue
            if not isinstance(raw_reason, str) or not raw_reason.strip():
                errors.append(
                    f"{rel_path}::{raw_node} in {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)}::{key} must include a non-empty reason."
                )
                continue
            allowlist[(rel_path, raw_node.strip())] = raw_reason.strip()
    return allowlist, errors


def _load_marker_file_allowlist_section(
    loaded: Mapping[str, object],
    key: str,
) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    section = loaded.get(key)
    allowlist: dict[str, str] = {}
    if not isinstance(section, Mapping):
        return allowlist, [
            f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} must define {key} as a mapping of file path -> reason."
        ]

    for raw_path, raw_reason in section.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(
                f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} contains a non-string {key} file path."
            )
            continue
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            errors.append(
                f"{raw_path} in {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)}::{key} must include a non-empty reason."
            )
            continue
        allowlist[raw_path.strip()] = raw_reason.strip()
    return allowlist, errors


def _load_test_marker_policy_allowlist() -> tuple[
    dict[tuple[str, str], str],
    dict[tuple[str, str], str],
    dict[str, str],
    list[str],
]:
    errors: list[str] = []
    if not _TEST_MARKER_POLICY_ALLOWLIST_PATH.exists():
        return (
            {},
            {},
            {},
            [
                f"Missing test-marker policy allowlist at {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)}."
            ],
        )

    loaded = yaml.safe_load(
        _TEST_MARKER_POLICY_ALLOWLIST_PATH.read_text(encoding="utf-8")
    )
    if not isinstance(loaded, Mapping):
        return (
            {},
            {},
            {},
            [
                f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} must load as a mapping."
            ],
        )

    smoke_allowlist, smoke_errors = _load_marker_node_allowlist_section(loaded, "smoke")
    long_sim_allowlist, long_sim_errors = _load_marker_node_allowlist_section(
        loaded, "long_sim"
    )
    e2e_file_exemptions, e2e_errors = _load_marker_file_allowlist_section(
        loaded, "e2e_file_exemptions"
    )
    errors.extend(smoke_errors)
    errors.extend(long_sim_errors)
    errors.extend(e2e_errors)
    return smoke_allowlist, long_sim_allowlist, e2e_file_exemptions, errors


def _marker_usage_nodes(
    marker_usage: Mapping[str, Mapping[str, set[str]]],
    marker: str,
) -> set[tuple[str, str]]:
    nodes: set[tuple[str, str]] = set()
    for rel_path, file_usage in marker_usage.items():
        for node_id in file_usage.get(marker, set()):
            nodes.add((rel_path, node_id))
    return nodes


def _marker_node_label(rel_path: str, node_id: str) -> str:
    if node_id == _MARKER_POLICY_NODE_MODULE:
        return f"{rel_path} [module]"
    return f"{rel_path}::{node_id}"


def marker_policy_errors(
    marker_usage: Mapping[str, Mapping[str, set[str]]],
    *,
    tracked_e2e_files: Sequence[str],
    tracked_benchmark_files: Sequence[str],
    smoke_allowlist: Mapping[tuple[str, str], str],
    long_sim_allowlist: Mapping[tuple[str, str], str],
    e2e_file_exemptions: Mapping[str, str],
) -> list[str]:
    errors: list[str] = []

    actual_smoke = _marker_usage_nodes(marker_usage, "smoke")
    expected_smoke = set(smoke_allowlist)
    for rel_path, node_id in sorted(expected_smoke - actual_smoke):
        errors.append(
            f"{_marker_node_label(rel_path, node_id)} is listed in "
            f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} under smoke "
            "but is not marked smoke; restore pytest.mark.smoke or remove the stale allowlist entry."
        )
    for rel_path, node_id in sorted(actual_smoke - expected_smoke):
        errors.append(
            f"{_marker_node_label(rel_path, node_id)} is marked smoke but is not listed in "
            f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} under smoke; "
            "remove pytest.mark.smoke or document why it belongs in the compact critical path."
        )

    actual_long_sim = _marker_usage_nodes(marker_usage, "long_sim")
    expected_long_sim = set(long_sim_allowlist)
    for rel_path, node_id in sorted(expected_long_sim - actual_long_sim):
        errors.append(
            f"{_marker_node_label(rel_path, node_id)} is listed in "
            f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} under long_sim "
            "but is not marked long_sim; restore pytest.mark.long_sim or remove the stale allowlist entry."
        )
    for rel_path, node_id in sorted(actual_long_sim - expected_long_sim):
        errors.append(
            f"{_marker_node_label(rel_path, node_id)} is marked long_sim but is not listed in "
            f"{_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} under long_sim; "
            "remove pytest.mark.long_sim or document why it must stay out of fast E2E lanes."
        )

    e2e_nodes = _marker_usage_nodes(marker_usage, "e2e")
    tracked_e2e_file_set = set(tracked_e2e_files)
    for rel_path, _reason in sorted(e2e_file_exemptions.items()):
        if rel_path not in tracked_e2e_file_set:
            errors.append(
                f"{rel_path} is listed in {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} "
                "under e2e_file_exemptions but is not a tracked apps/server/tests_e2e test file."
            )

    for rel_path in sorted(tracked_e2e_file_set):
        has_module_e2e = (rel_path, _MARKER_POLICY_NODE_MODULE) in e2e_nodes
        if rel_path in e2e_file_exemptions:
            if has_module_e2e:
                errors.append(
                    f"{rel_path} is exempted in {_TEST_MARKER_POLICY_ALLOWLIST_PATH.relative_to(ROOT)} "
                    "under e2e_file_exemptions but already has module-level pytest.mark.e2e; remove the stale exemption."
                )
            continue
        if not has_module_e2e:
            errors.append(
                f"{rel_path} lives under apps/server/tests_e2e/ but is missing module-level pytest.mark.e2e; "
                "add pytestmark = pytest.mark.e2e or document a file exemption."
            )

    for rel_path, node_id in sorted(e2e_nodes):
        if rel_path.startswith("apps/server/tests_e2e/"):
            continue
        if (rel_path, node_id) not in actual_long_sim:
            errors.append(
                f"{_marker_node_label(rel_path, node_id)} is marked e2e outside apps/server/tests_e2e/ "
                "but is not marked long_sim; add pytest.mark.long_sim so fast E2E lanes keep excluding it."
            )

    benchmark_nodes = _marker_usage_nodes(marker_usage, "benchmark")
    tracked_benchmark_file_set = set(tracked_benchmark_files)
    for rel_path in sorted(tracked_benchmark_file_set):
        if not marker_usage.get(rel_path, {}).get("benchmark", set()):
            errors.append(
                f"{rel_path} matches apps/server/tests/**/benchmark_*.py but has no pytest.mark.benchmark tests; "
                "add the benchmark marker or rename/move the file."
            )
    for rel_path, node_id in sorted(benchmark_nodes):
        if rel_path in tracked_benchmark_file_set:
            continue
        errors.append(
            f"{_marker_node_label(rel_path, node_id)} is marked benchmark but does not live in "
            "apps/server/tests/**/benchmark_*.py; move it into an explicit benchmark file or remove pytest.mark.benchmark."
        )

    return errors


def check_test_marker_policy() -> list[str]:
    smoke_allowlist, long_sim_allowlist, e2e_file_exemptions, allowlist_errors = (
        _load_test_marker_policy_allowlist()
    )
    marker_usage, parse_errors = _collect_test_marker_usage()
    errors = list(allowlist_errors)
    errors.extend(parse_errors)
    if parse_errors:
        return errors

    tracked_e2e_files = sorted(
        rel_path
        for rel_path in marker_usage
        if rel_path.startswith("apps/server/tests_e2e/")
        and Path(rel_path).name.startswith("test_")
    )
    tracked_benchmark_files = sorted(
        rel_path
        for rel_path in marker_usage
        if rel_path.startswith("apps/server/tests/")
        and Path(rel_path).name.startswith("benchmark_")
    )

    errors.extend(
        marker_policy_errors(
            marker_usage,
            tracked_e2e_files=tracked_e2e_files,
            tracked_benchmark_files=tracked_benchmark_files,
            smoke_allowlist=smoke_allowlist,
            long_sim_allowlist=long_sim_allowlist,
            e2e_file_exemptions=e2e_file_exemptions,
        )
    )
    return errors
