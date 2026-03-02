"""Tests for the WS payload JSON Schema export utility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibesensor.ws_schema_export import export_schema


def test_export_schema_returns_valid_json() -> None:
    """export_schema() must return a valid JSON string."""
    text = export_schema()
    schema = json.loads(text)
    assert isinstance(schema, dict)
    assert "properties" in schema or "$defs" in schema


def test_export_schema_ends_with_newline() -> None:
    """Exported schema must end with a trailing newline for POSIX compliance."""
    text = export_schema()
    assert text.endswith("\n")


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


def test_export_schema_matches_committed_schema() -> None:
    """Generated schema must match the committed contract file."""
    committed_path = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "ui"
        / "src"
        / "contracts"
        / "ws_payload_schema.json"
    )
    if not committed_path.exists():
        pytest.skip("UI contracts not available")
    generated = export_schema()
    committed = committed_path.read_text()
    assert committed == generated, (
        "Committed ws_payload_schema.json is out of sync with generated schema. "
        "Run 'python -m vibesensor.ws_schema_export' and commit the result."
    )


def test_export_schema_has_schema_version() -> None:
    """The schema must include the schema_version field."""
    text = export_schema()
    schema = json.loads(text)
    # schema_version should be in the top-level properties or definitions
    props = schema.get("properties", {})
    assert "schema_version" in props, "schema_version must be a top-level property"
