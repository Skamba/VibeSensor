"""The contract TypeScript renderer must fail loudly on schema shapes it cannot translate."""

from __future__ import annotations

import importlib.util
import sys

import pytest

from tests._paths import REPO_ROOT

_SCRIPT = REPO_ROOT / "tools" / "config" / "sync_contracts.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_contracts_for_tests", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync_contracts = _load_module()


def test_renders_supported_subset() -> None:
    rendered = sync_contracts.render_schema_types(
        {
            "Row": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"enum": ["a", "b"]},
                    "value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "extra": {"description": "Free-form payload."},
                },
                "required": ["id", "kind"],
            }
        }
    )

    assert "id: string;" in rendered
    assert 'kind: "a" | "b";' in rendered
    assert "value?: number | null;" in rendered
    assert "tags?: string[];" in rendered
    assert "extra?: unknown;" in rendered


@pytest.mark.parametrize(
    "schema",
    [
        {"oneOf": [{"type": "string"}, {"type": "number"}]},
        {"allOf": [{"$ref": "#/components/schemas/Base"}]},
        {"type": "array", "prefixItems": [{"type": "string"}]},
        {"type": "array", "items": [{"type": "string"}, {"type": "number"}]},
        {"type": "object", "patternProperties": {"^x-": {"type": "string"}}},
        {"type": "integer", "not": {"const": 0}},
        {"format": "date-time"},
    ],
)
def test_rejects_unsupported_schema(schema: dict[str, object]) -> None:
    with pytest.raises(sync_contracts.UnsupportedSchemaError, match="Broken"):
        sync_contracts.render_schema_types(
            {"Broken": {"type": "object", "properties": {"field": schema}}}
        )
