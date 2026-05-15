"""Guard language normalization and mypy package-discovery configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.report_i18n import normalize_lang

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
            ("nl_BE.UTF-8", "nl"),
            ("nld", "nl"),
            ("fr", "en"),
            ("en-US", "en"),
            (None, "en"),
            (42, "en"),
            ("", "en"),
        ],
    )
    def test_normalize_lang_handles_variants(self, raw: object, expected: str) -> None:
        assert normalize_lang(raw) == expected


# ── mypy enforcement expansion ────────────────────────────────────────────────


class TestMypyEnforcement:
    """pyproject.toml [tool.mypy] uses package discovery without internal denylists."""

    @pytest.fixture
    def mypy_config(self) -> dict[str, object]:
        import tomllib

        data = tomllib.loads(_PYPROJECT.read_text())
        return data["tool"]["mypy"]

    def test_mypy_uses_package_level_discovery(self, mypy_config: dict[str, object]) -> None:
        assert mypy_config.get("packages") == ["vibesensor"]
        assert "files" not in mypy_config
        assert "namespace_packages" not in mypy_config

    def test_mypy_discovery_has_no_internal_exclude(self, mypy_config: dict[str, object]) -> None:
        assert mypy_config.get("exclude") in (None, [], "")

    def test_mypy_has_no_internal_ignore_errors_override(
        self,
        mypy_config: dict[str, object],
    ) -> None:
        overrides = mypy_config.get("overrides")
        assert isinstance(overrides, list)
        offending_modules: list[str] = []
        for override in overrides:
            if not isinstance(override, dict) or override.get("ignore_errors") is not True:
                continue
            modules = override.get("module", [])
            module_names = [modules] if isinstance(modules, str) else modules
            offending_modules.extend(
                module_name
                for module_name in module_names
                if isinstance(module_name, str) and module_name.startswith("vibesensor.")
            )
        assert offending_modules == []
