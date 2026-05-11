# ruff: noqa: F403,F405
"""Frontend contract and DOM boundary hygiene checks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


from ._shared import *
from .repo_sync import _git_tracked_files


def _ui_source_files() -> list[Path]:
    return [
        path
        for path in _git_tracked_files()
        if path.is_file()
        and path.suffix in _UI_SOURCE_SUFFIXES
        and path.is_relative_to(ROOT / "apps" / "ui" / "src")
    ]


def _ui_test_files() -> list[Path]:
    return [
        path
        for path in _git_tracked_files()
        if path.is_file()
        and path.suffix in _UI_SOURCE_SUFFIXES
        and path.is_relative_to(ROOT / "apps" / "ui" / "tests")
    ]


def _extract_import_specifiers(source_text: str) -> list[str]:
    specifiers = [
        *(_IMPORT_FROM_RE.findall(source_text)),
        *(_SIDE_EFFECT_IMPORT_RE.findall(source_text)),
    ]
    return list(dict.fromkeys(specifiers))


def _resolve_ui_local_import(source_path: Path, specifier: str) -> Path | None:
    if not specifier.startswith("."):
        return None
    base = (source_path.parent / specifier).resolve()
    candidates = [base]
    if not base.suffix:
        candidates.extend(base.with_suffix(ext) for ext in sorted(_UI_SOURCE_SUFFIXES))
        candidates.extend(base / f"index{ext}" for ext in sorted(_UI_SOURCE_SUFFIXES))
    for candidate in candidates:
        if candidate.exists():
            return candidate
        if candidate.is_relative_to(ROOT):
            candidate_rel = str(candidate.relative_to(ROOT))
            if candidate_rel in _UI_OPTIONAL_GENERATED_TARGETS:
                return candidate
    return None


def _ui_boundary_import_allowed(importer_rel: str, target_rel: str) -> bool:
    if target_rel == "apps/ui/src/api/types.ts":
        return importer_rel.startswith("apps/ui/src/") and importer_rel != target_rel
    allowed_importers = _UI_FRONTEND_BOUNDARY_IMPORTERS.get(target_rel)
    return allowed_importers is None or importer_rel in allowed_importers


def _ui_boundary_allowed_description(target_rel: str) -> str:
    if target_rel == "apps/ui/src/api/types.ts":
        return "apps/ui/src/**"
    allowed_importers = _UI_FRONTEND_BOUNDARY_IMPORTERS.get(target_rel)
    return (
        ", ".join(sorted(allowed_importers))
        if allowed_importers is not None
        else "approved transport boundary files"
    )


def _ui_boundary_fix_hint(importer_rel: str, target_rel: str) -> str:
    if importer_rel.startswith("apps/ui/src/app/"):
        if target_rel == "apps/ui/src/generated/http_api_contracts.ts":
            return (
                "import HTTP contract aliases through apps/ui/src/api/types.ts instead"
            )
        if target_rel in {
            "apps/ui/src/contracts/ws_payload_types.ts",
            "apps/ui/src/contracts/ws_payload_schema.generated.ts",
        }:
            return (
                "import WS contract data through apps/ui/src/transport/live_models.ts, "
                "apps/ui/src/server_payload.ts, apps/ui/src/ws.ts, or "
                "apps/ui/src/ws_payload_validator.ts instead"
            )
    return f"keep generated transport contracts behind {_ui_boundary_allowed_description(target_rel)}"


def check_frontend_generated_contract_boundaries() -> list[str]:
    errors: list[str] = []
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        for specifier in _extract_import_specifiers(text):
            resolved = _resolve_ui_local_import(path, specifier)
            if resolved is None:
                continue
            resolved_rel = str(resolved.relative_to(ROOT))
            if _ui_boundary_import_allowed(rel, resolved_rel):
                continue
            errors.append(
                f"{rel} must not import {resolved_rel}; {_ui_boundary_fix_hint(rel, resolved_rel)}."
            )
    return errors


def check_frontend_raw_html_boundaries() -> list[str]:
    errors: list[str] = []
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        if rel.startswith(_UI_ALLOWED_RAW_HTML_PREFIX):
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "insertAdjacentHTML(" in line:
                errors.append(
                    f"{rel}:{lineno} uses insertAdjacentHTML outside app/views/**; "
                    "move the markup into a view helper or DOM builder."
                )
            if "createContextualFragment(" in line:
                errors.append(
                    f"{rel}:{lineno} uses createContextualFragment outside app/views/**; "
                    "move the markup into a view helper or DOM builder."
                )
            if ".innerHTML" not in line or "=" not in line:
                continue
            if _EMPTY_INNERHTML_ASSIGNMENT_RE.search(line):
                continue
            errors.append(
                f"{rel}:{lineno} uses innerHTML outside app/views/**; "
                "move the markup into a view helper or DOM builder."
            )
    return errors


def check_frontend_dom_registry_guardrails() -> list[str]:
    errors: list[str] = []
    if _UI_DOM_REGISTRY_PATH.exists():
        errors.append(
            "apps/ui/src/app/ui_dom_registry.ts must stay deleted; "
            "DOM lookup belongs in app/dom/* locators plus focused runtime/view helpers."
        )
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        if not rel.startswith("apps/ui/src/app/"):
            continue
        text = path.read_text(encoding="utf-8")
        for token in _UI_DOM_REGISTRY_TOKENS:
            if token in text:
                errors.append(
                    f"{rel} references {token!r}; keep page-wide DOM registries out of app/** and "
                    "use feature-scoped locators instead."
                )
                break
    return errors


def check_frontend_legacy_test_dom_bridge_guardrails() -> list[str]:
    errors: list[str] = []
    for path in _ui_test_files():
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        for token in _UI_LEGACY_TEST_DOM_TOKENS:
            if token not in text:
                continue
            errors.append(
                f"{rel} references {token!r}; keep UI tests on mountSignalView() plus real DOM panels "
                "instead of legacy fake-element bridge helpers."
            )
    return errors


def check_frontend_component_use_computed_guardrails() -> list[str]:
    errors: list[str] = []
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        if not rel.startswith("apps/ui/src/app/") or path.suffix != ".tsx":
            continue
        text = path.read_text(encoding="utf-8")
        if _UI_COMPONENT_USE_COMPUTED_TOKEN not in text:
            continue
        errors.append(
            f"{rel} references {_UI_COMPONENT_USE_COMPUTED_TOKEN!r}; keep computed owners in "
            "runtime/feature/presenter/shared modules and let component .tsx files read already-derived signals."
        )
    return errors


def check_ui_vite_server_contract() -> list[str]:
    errors: list[str] = []
    package_json = json.loads(_UI_PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    scripts = package_json.get("scripts")
    if not isinstance(scripts, Mapping):
        return ["apps/ui/package.json must define a scripts mapping."]
    for script_name, expected in {
        "dev": "vite",
        "dev:open": "vite --open",
        "preview": "vite preview",
        "wiki:screenshots": "node update-wiki-screenshots.mjs",
    }.items():
        if scripts.get(script_name) != expected:
            errors.append(
                f"apps/ui/package.json script {script_name!r} must stay {expected!r}."
            )

    vite_config = (ROOT / "apps/ui/vite.config.ts").read_text(encoding="utf-8")
    if "preview:" not in vite_config or vite_config.count("strictPort: true") < 2:
        errors.append(
            "apps/ui/vite.config.ts must pin strict dev and preview ports in Vite config."
        )

    smoke_config = (ROOT / "apps/ui/playwright.smoke.config.ts").read_text(
        encoding="utf-8"
    )
    if "--strictPort" not in smoke_config:
        errors.append(
            "apps/ui/playwright.smoke.config.ts must fail fast on Vite port conflicts."
        )

    helper_path = ROOT / "apps/ui/playwright-preview-helpers.mjs"
    helper_text = helper_path.read_text(encoding="utf-8")
    if "--strictPort" not in helper_text:
        errors.append(
            "apps/ui/playwright-preview-helpers.mjs must fail fast on preview port conflicts."
        )
    for rel_path in (
        "apps/ui/take-screenshot.mjs",
        "apps/ui/update-snapshots.mjs",
        "apps/ui/update-wiki-screenshots.mjs",
    ):
        if "./playwright-preview-helpers.mjs" not in (ROOT / rel_path).read_text(
            encoding="utf-8"
        ):
            errors.append(
                f"{rel_path} must use playwright-preview-helpers.mjs for preview startup."
            )
    return errors


def _ui_production_package_names() -> set[str]:
    lockfile = json.loads(
        (ROOT / "apps/ui/package-lock.json").read_text(encoding="utf-8")
    )
    packages = lockfile.get("packages")
    if not isinstance(packages, Mapping):
        return set()

    root_package = packages.get("")
    if not isinstance(root_package, Mapping):
        return set()

    dependencies = root_package.get("dependencies")
    if not isinstance(dependencies, Mapping):
        return set()

    production_package_names: set[str] = set()
    pending = list(dependencies)
    while pending:
        package_name = pending.pop()
        if package_name in production_package_names:
            continue
        production_package_names.add(package_name)

        package_data = packages.get(f"node_modules/{package_name}")
        if not isinstance(package_data, Mapping):
            continue
        package_dependencies = package_data.get("dependencies")
        if isinstance(package_dependencies, Mapping):
            pending.extend(package_dependencies)

    return production_package_names


def check_frontend_manual_chunk_packages() -> list[str]:
    errors: list[str] = []
    vite_config = (ROOT / "apps/ui/vite.config.ts").read_text(encoding="utf-8")
    production_package_names = _ui_production_package_names()
    manual_chunk_package_names = set(_UI_MANUAL_CHUNK_PACKAGE_RE.findall(vite_config))

    stale_package_names = sorted(manual_chunk_package_names - production_package_names)
    for package_name in stale_package_names:
        errors.append(
            f"apps/ui/vite.config.ts manual chunk rule references {package_name!r}, "
            "but it is not in the UI production dependency graph."
        )

    return errors
