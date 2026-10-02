"""Tests for the WS payload JSON Schema export utility."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from vibesensor.cli.ws_schema_export import export_schema

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Module-scoped fixtures – call export_schema() once for read-only tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_text() -> str:
    """Cached raw output of export_schema()."""
    return export_schema()


@pytest.fixture(scope="module")
def schema_dict(schema_text: str) -> dict[str, object]:
    """Cached parsed schema dict."""
    return json.loads(schema_text)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_export_schema_returns_valid_json(schema_dict: dict[str, object]) -> None:
    """export_schema() must return a valid JSON string."""
    assert isinstance(schema_dict, dict)
    assert "properties" in schema_dict or "$defs" in schema_dict


def test_export_schema_ends_with_newline(schema_text: str) -> None:
    """Exported schema must end with a trailing newline for POSIX compliance."""
    assert schema_text.endswith("\n")


def test_export_schema_writes_to_file(tmp_path: Path) -> None:
    """When out_path is given, the schema must be written to disk."""
    out = tmp_path / "schema.json"
    text = export_schema(out_path=out)
    assert out.exists()
    on_disk = out.read_text()
    assert on_disk == text


def test_export_schema_creates_parent_dirs(tmp_path: Path) -> None:
    """export_schema() must create missing parent directories."""
    out = tmp_path / "a" / "b" / "schema.json"
    export_schema(out_path=out)
    assert out.exists()
