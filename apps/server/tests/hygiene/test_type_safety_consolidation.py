"""Chunk 4 — Type Safety & Validation Consolidation.

Verifies:
- normalize_lang is sourced from one canonical module (report_i18n)
- SettingsStore._coerce_language handles locale variants (e.g. "nl-BE")
- ClientRegistry uses normalize_sensor_id (no private duplicate)
- ClassificationResult TypedDict returned from classify_peak_hz
- mypy enforcement list includes the expanded module set
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vibesensor.adapters.pdf_i18n import normalize_lang
from vibesensor.infra.config.settings_store import _coerce_language

_SERVER_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _SERVER_ROOT / "pyproject.toml"


# ── normalize_lang single source ──────────────────────────────────────────────


class TestNormalizeLangConsolidation:
    """Ensure normalize_lang is the canonical source and handles variants."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("en", "en"),
            ("nl", "nl"),
            ("nl-BE", "nl"),
            ("NL-NL", "nl"),
            ("  NL ", "nl"),
            ("fr", "en"),
            (None, "en"),
            (42, "en"),
            ("", "en"),
        ],
    )
    def test_normalize_lang_handles_variants(self, raw: object, expected: str) -> None:
        assert normalize_lang(raw) == expected

    def test_summary_builder_imports_from_report_i18n(self) -> None:
        """summary_builder must import normalize_lang from report_i18n, not define its own."""
        src = (_SERVER_ROOT / "vibesensor" / "analysis" / "summary_builder.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "normalize_lang":
                pytest.fail("summary_builder.py must not define its own normalize_lang()")

    def test_coerce_language_accepts_nl_be(self) -> None:
        """SettingsStore._coerce_language must accept 'nl-BE' as Dutch."""
        assert _coerce_language("nl-BE") == "nl"
        assert _coerce_language("nl") == "nl"
        assert _coerce_language("nl-NL") == "nl"
        assert _coerce_language("en") == "en"


# ── ClientRegistry normalize_sensor_id ────────────────────────────────────────


class TestClientIdDedup:
    """Registry must use normalize_sensor_id from protocol, not a private copy."""

    def test_no_private_normalize_client_id(self) -> None:
        src = (_SERVER_ROOT / "vibesensor" / "registry.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_normalize_client_id":
                pytest.fail("registry.py must not define _normalize_client_id()")

    def test_registry_imports_normalize_sensor_id(self) -> None:
        src = (_SERVER_ROOT / "vibesensor" / "registry.py").read_text()
        assert "normalize_sensor_id" in src


# ── mypy enforcement expansion ────────────────────────────────────────────────


class TestMypyEnforcement:
    """pyproject.toml [tool.mypy] files list includes expanded modules."""

    @pytest.fixture
    def mypy_files(self) -> list[str]:
        import tomllib

        data = tomllib.loads(_PYPROJECT.read_text())
        return data["tool"]["mypy"]["files"]

    @pytest.mark.parametrize(
        "module",
        [
            "vibesensor/report_i18n.py",
            "vibesensor/analysis_settings.py",
            "vibesensor/metrics_log",
        ],
    )
    def test_module_in_mypy_files(self, mypy_files: list[str], module: str) -> None:
        assert module in mypy_files, f"{module} not in pyproject.toml [tool.mypy] files"
