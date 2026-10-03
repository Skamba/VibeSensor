"""Regenerate every committed contract artifact from backend sources.

Run through ``make sync-contracts``. Writes:

- ``apps/ui/src/generated/http_api_contracts.ts`` (HTTP OpenAPI schemas -> TypeScript)
- ``apps/ui/src/contracts/ws_payload_types.ts`` (WS JSON Schema -> TypeScript)
- ``apps/ui/src/constants.ts`` (backend-owned shared constants)
- ``docs/protocol.md`` (protocol/ports reference)

Both TypeScript files expose ``components["schemas"][Name]`` types rendered by
``render_schema_types`` below; it covers the JSON Schema subset Pydantic emits
for our models. CI checks drift by running this and ``git diff --exit-code``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_contract_reference_doc import render_contract_reference_markdown  # noqa: E402
from generate_ui_shared_constants import render_ui_shared_constants_module  # noqa: E402

from vibesensor.cli.http_api_schema_export import export_schema as export_http_schema  # noqa: E402
from vibesensor.cli.ws_schema_export import export_schema as export_ws_schema  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "apps" / "ui"
HTTP_TYPES_PATH = UI_DIR / "src" / "generated" / "http_api_contracts.ts"
WS_TYPES_PATH = UI_DIR / "src" / "contracts" / "ws_payload_types.ts"
CONSTANTS_PATH = UI_DIR / "src" / "constants.ts"
PROTOCOL_DOC_PATH = ROOT / "docs" / "protocol.md"

_GENERATED_HEADER = (
    "// Generated from {source}\n// Do not edit manually; run make sync-contracts\n\n"
)

# Stable UI-facing aliases appended to the generated WS types.
_WS_ALIASES = {
    "StrengthMetricPeak": "StrengthPeak",
    "StrengthMetricsPayload": "VibrationStrengthMetrics",
    "WsSpectrumSeries": "SpectrumSeriesPayload",
    "WsAlignmentInfo": "AlignmentInfoPayload",
    "WsFrequencyWarning": "FrequencyWarningPayload",
    "WsSpectraPayload": "SpectraPayload",
    "WsRotationalSpeedValue": "RotationalSpeedValuePayload",
    "WsOrderBand": "OrderBandPayload",
    "WsRotationalSpeeds": "RotationalSpeedsPayload",
    "WsClientInfo": "ClientApiRow",
    "LiveWsPayload": "LiveWsPayload",
}

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_PRIMITIVES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}
_INDENT = "    "


def _key(name: str) -> str:
    return name if _IDENTIFIER.match(name) else json.dumps(name)


def _union(members: list[str]) -> str:
    unique = list(dict.fromkeys(members))
    return " | ".join(f"({m})" if " | " in m and len(unique) > 1 else m for m in unique)


def _doc(schema: dict[str, object], indent: str) -> str:
    description = schema.get("description")
    if not isinstance(description, str):
        return ""
    text = description.replace("*/", "*\\/").splitlines()
    if len(text) == 1:
        return f"{indent}/** {text[0]} */\n"
    body = "".join(f"{indent} * {line}".rstrip() + "\n" for line in text)
    return f"{indent}/**\n{body}{indent} */\n"


def _render(schema: object, depth: int) -> str:
    """Render one JSON Schema node as a TypeScript type expression."""
    if not isinstance(schema, dict):
        return "unknown"
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        return f'components["schemas"][{json.dumps(name)}]'
    if "const" in schema:
        return json.dumps(schema["const"])
    enum = schema.get("enum")
    if isinstance(enum, list):
        return _union([json.dumps(value) for value in enum])
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        return _union([_render(member, depth) for member in any_of])
    kind = schema.get("type")
    if isinstance(kind, list):
        return _union([_render({**schema, "type": k}, depth) for k in kind])
    if kind == "array":
        item = _render(schema.get("items", {}), depth)
        return f"({item})[]" if " | " in item else f"{item}[]"
    if kind == "object" or "properties" in schema:
        return _render_object(schema, depth)
    if isinstance(kind, str) and kind in _PRIMITIVES:
        return _PRIMITIVES[kind]
    return "unknown"


def _render_object(schema: dict[str, object], depth: int) -> str:
    properties = schema.get("properties", {})
    assert isinstance(properties, dict)
    required = set(schema.get("required", []))  # type: ignore[arg-type]
    extra = schema.get("additionalProperties")
    if not properties and extra in (None, False):
        return "Record<string, never>"
    indent = _INDENT * (depth + 1)
    lines = ["{\n"]
    for name, prop in properties.items():
        # A property with a default is always present in responses.
        optional = name not in required and not (
            isinstance(prop, dict) and "default" in prop
        )
        doc = _doc(prop, indent) if isinstance(prop, dict) else ""
        mark = "?" if optional else ""
        lines.append(f"{doc}{indent}{_key(name)}{mark}: {_render(prop, depth + 1)};\n")
    if extra is True or isinstance(extra, dict):
        value = "unknown" if extra is True else _render(extra, depth + 1)
        lines.append(f"{indent}[key: string]: {value};\n")
    lines.append(f"{_INDENT * depth}}}")
    return "".join(lines)


def render_schema_types(schemas: dict[str, object]) -> str:
    """Render named schemas as ``export interface components { schemas: {...} }``."""
    body = "".join(
        f"{_doc(schema, _INDENT * 2) if isinstance(schema, dict) else ''}"
        f"{_INDENT * 2}{_key(name)}: {_render(schema, 2)};\n"
        for name, schema in schemas.items()
    )
    return f"export interface components {{\n{_INDENT}schemas: {{\n{body}{_INDENT}}};\n}}\n"


def _ws_schema_version(ws_schema: dict[str, object]) -> str:
    properties = ws_schema.get("properties")
    assert isinstance(properties, dict)
    schema_version = properties["schema_version"]
    assert isinstance(schema_version, dict)
    return str(schema_version.get("default", "1"))


def _render_ws_types() -> str:
    ws_schema = json.loads(export_ws_schema())
    defs = ws_schema.pop("$defs", {})
    assert isinstance(defs, dict)
    aliases = "".join(
        f'export type {alias} = WsSchema<"{name}">;\n'
        for alias, name in _WS_ALIASES.items()
    )
    return (
        _GENERATED_HEADER.format(source="vibesensor.cli.ws_schema_export")
        + render_schema_types({"LiveWsPayload": ws_schema, **defs})
        + "\n"
        + f"export const EXPECTED_SCHEMA_VERSION = {json.dumps(_ws_schema_version(ws_schema))}"
        + " as const;\n\n"
        + 'type WsSchema<Name extends keyof components["schemas"]> = '
        + 'components["schemas"][Name];\n\n'
        + aliases
    )


def _render_http_types() -> str:
    schemas = json.loads(export_http_schema())["components"]["schemas"]
    return _GENERATED_HEADER.format(
        source="vibesensor.cli.http_api_schema_export"
    ) + render_schema_types(schemas)


def main() -> None:
    outputs = {
        HTTP_TYPES_PATH: _render_http_types(),
        WS_TYPES_PATH: _render_ws_types(),
        CONSTANTS_PATH: render_ui_shared_constants_module(),
        PROTOCOL_DOC_PATH: render_contract_reference_markdown(),
    }
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
