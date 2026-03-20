"""Comprehensive layered-architecture import boundary enforcement.

Scans every ``.py`` file under ``vibesensor/`` and verifies that its imports
respect the layer dependency DAG:

    domain → (nothing)
    shared → {domain}
    use_cases → {domain, shared}
    infra → {domain, shared}
    adapters → {domain, shared, infra, use_cases}
    app → (everything)

Root-level files directly under ``vibesensor/`` (e.g. ``vibration_strength.py``,
``coerce.py``) are classified as **shared**.

Known violations are documented in ``_KNOWN_VIOLATIONS`` so that the test
catches *new* boundary regressions without blocking CI on pre-existing debt.
The allowlist must shrink over time — stale entries cause a test failure too.
"""

from __future__ import annotations

import ast

from _paths import SERVER_ROOT

_PKG_ROOT = SERVER_ROOT / "vibesensor"

# ── Layer definitions ────────────────────────────────────────────────────

_LAYERS = ("domain", "shared", "use_cases", "infra", "adapters", "app")

_ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "shared": frozenset({"domain"}),
    "use_cases": frozenset({"domain", "shared"}),
    "infra": frozenset({"domain", "shared"}),
    "adapters": frozenset({"domain", "shared", "infra", "use_cases"}),
    "app": frozenset({"domain", "shared", "use_cases", "infra", "adapters"}),
}


def _classify_layer(rel_path: str) -> str:
    """Classify a file path (relative to vibesensor/) into a layer.

    Subdirectories map directly (``domain/``, ``shared/``, etc.).
    ``cli/`` is treated as **app**.  Root-level ``.py`` files are **shared**.
    """
    first = rel_path.split("/")[0]
    if first in ("domain", "shared", "use_cases", "infra", "adapters", "app"):
        return first
    if first == "cli":
        return "app"
    return "shared"


def _import_target_layer(module: str) -> str | None:
    """Return the layer that *module* belongs to, or ``None`` if external."""
    if not module.startswith("vibesensor"):
        return None
    rest = module.removeprefix("vibesensor.")
    if not rest:
        return None
    top = rest.split(".")[0]
    if top in ("domain", "shared", "use_cases", "infra", "adapters", "app"):
        return top
    if top == "cli":
        return "app"
    return "shared"


# ── Known violations (allowlist) ─────────────────────────────────────────
#
# Each entry is ``(source_file_relative_to_vibesensor, target_module)``.
# When a cleanup PR removes a violation, delete its entry here — a stale
# entry makes the test fail so the allowlist stays honest.

_KNOWN_VIOLATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # domain → shared (root-level utilities)
        ("domain/finding.py", "vibesensor.coerce"),
        ("domain/location_hotspot.py", "vibesensor.coerce"),
        ("domain/order_match.py", "vibesensor.coerce"),
        ("domain/run_capture.py", "vibesensor.strength_bands"),
        ("domain/run_capture.py", "vibesensor.vibration_strength"),
        ("domain/snapshots.py", "vibesensor.coerce"),
        ("domain/strength_metrics.py", "vibesensor.coerce"),
        # shared → adapters
        # use_cases → adapters
        ("use_cases/run/logger.py", "vibesensor.adapters.gps.gps_speed"),
        # use_cases → infra
        ("use_cases/history/reports.py", "vibesensor.infra.config.settings_store"),
        ("use_cases/history/runs.py", "vibesensor.infra.config.settings_store"),
        ("use_cases/run/logger.py", "vibesensor.infra.config.settings_store"),
        # infra → adapters
        ("infra/config/settings_store.py", "vibesensor.adapters.gps.gps_speed"),
        ("infra/config/settings_store.py", "vibesensor.adapters.persistence.history_db"),
        ("infra/runtime/processing_loop.py", "vibesensor.adapters.udp.udp_control_tx"),
        ("infra/runtime/registry.py", "vibesensor.adapters.udp.protocol"),
        ("infra/runtime/registry.py", "vibesensor.adapters.persistence.history_db"),
        ("infra/runtime/rotational_speeds.py", "vibesensor.adapters.gps.gps_speed"),
        ("infra/runtime/ws_broadcast.py", "vibesensor.adapters.gps.gps_speed"),
        # infra → app
        # RuntimeState is now lifecycle-focused, but LifecycleManager still consumes
        # the app-owned runtime bag directly.
        ("infra/runtime/lifecycle.py", "vibesensor.app.runtime_state"),
        # adapters → app
        ("adapters/hotspot/self_heal.py", "vibesensor.app.settings"),
    }
)


# ── Scanner ──────────────────────────────────────────────────────────────


def _scan_violations() -> set[tuple[str, str]]:
    """Return the set of ``(source_rel, target_module)`` boundary violations."""
    violations: set[tuple[str, str]] = set()
    for py_file in sorted(_PKG_ROOT.rglob("*.py")):
        if "__pycache__" in py_file.parts or "static" in py_file.parts:
            continue
        rel = str(py_file.relative_to(_PKG_ROOT))
        layer = _classify_layer(rel)
        allowed = _ALLOWED_IMPORTS[layer]

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level == 0:
                    modules = [node.module]
            for mod in modules:
                target = _import_target_layer(mod)
                if target is None or target == layer:
                    continue
                if target not in allowed:
                    violations.add((rel, mod))
    return violations


# ── Tests ────────────────────────────────────────────────────────────────


def test_no_new_layer_boundary_violations() -> None:
    """Every cross-layer import must respect the DAG or be in the allowlist."""
    violations = _scan_violations()
    new_violations = violations - _KNOWN_VIOLATIONS
    assert not new_violations, (
        "New layer-boundary violations found (not in allowlist):\n  "
        + "\n  ".join(f"{src} -> {mod}" for src, mod in sorted(new_violations))
        + "\n\nEither fix the import or add it to _KNOWN_VIOLATIONS with a comment."
    )


def test_allowlist_has_no_stale_entries() -> None:
    """Every allowlist entry must correspond to an actual violation.

    When a cleanup removes a violation, its allowlist entry must be deleted
    so the list stays honest and shrinks over time.
    """
    violations = _scan_violations()
    stale = _KNOWN_VIOLATIONS - violations
    assert not stale, (
        "Stale allowlist entries (violation no longer exists — remove them):\n  "
        + "\n  ".join(f"{src} -> {mod}" for src, mod in sorted(stale))
    )


def test_all_layers_are_covered() -> None:
    """Sanity check: every expected layer directory exists in the package."""
    for layer in _LAYERS:
        if layer == "shared":
            assert (_PKG_ROOT / "shared").is_dir()
        elif layer == "app":
            assert (_PKG_ROOT / "app").is_dir()
        else:
            assert (_PKG_ROOT / layer).is_dir(), f"Missing layer directory: {layer}/"


def test_layer_dag_is_acyclic() -> None:
    """The allowed-imports graph must be a DAG (no mutual dependencies)."""
    for layer, allowed in _ALLOWED_IMPORTS.items():
        for target in allowed:
            peer_allowed = _ALLOWED_IMPORTS.get(target, frozenset())
            assert layer not in peer_allowed, (
                f"Cycle detected: {layer} may import {target} and {target} may import {layer}"
            )
