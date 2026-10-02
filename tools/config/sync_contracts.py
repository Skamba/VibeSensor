"""Regenerate every committed contract artifact from backend sources.

Run through ``make sync-contracts``. Writes:

- ``apps/ui/src/generated/http_api_contracts.ts`` (HTTP OpenAPI -> TypeScript)
- ``apps/ui/src/contracts/ws_payload_types.ts`` (WS JSON Schema -> TypeScript)
- ``apps/ui/src/constants.ts`` (backend-owned shared constants)
- ``docs/protocol.md`` (protocol/ports reference)

The intermediate OpenAPI/JSON Schema documents are exported to a temporary
directory and fed to ``openapi-typescript`` from ``apps/ui/node_modules``; they
are not committed. CI checks drift by running this and ``git diff --exit-code``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_contract_reference_doc import render_contract_reference_markdown  # noqa: E402
from generate_ui_shared_constants import render_ui_shared_constants_module  # noqa: E402

from vibesensor.cli.http_api_schema_export import export_schema as export_http_schema  # noqa: E402
from vibesensor.cli.ws_schema_export import export_schema as export_ws_schema  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "apps" / "ui"
OPENAPI_TS_CLI = UI_DIR / "node_modules" / "openapi-typescript" / "bin" / "cli.js"
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


def _openapi_typescript(schema_path: Path) -> str:
    if not OPENAPI_TS_CLI.is_file():
        raise SystemExit(
            f"Missing {OPENAPI_TS_CLI.relative_to(ROOT)}; run `make setup` to install UI deps."
        )
    result = subprocess.run(
        ["node", str(OPENAPI_TS_CLI), str(schema_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _rewrite_defs_refs(value: object) -> object:
    if isinstance(value, list):
        return [_rewrite_defs_refs(item) for item in value]
    if not isinstance(value, dict):
        return value
    rewritten: dict[str, object] = {}
    for key, entry in value.items():
        if key == "$ref" and isinstance(entry, str) and entry.startswith("#/$defs/"):
            rewritten[key] = "#/components/schemas/" + entry.removeprefix("#/$defs/")
        else:
            rewritten[key] = _rewrite_defs_refs(entry)
    return rewritten


def _ws_schema_as_openapi(ws_schema: dict[str, object]) -> dict[str, object]:
    """Wrap the WS JSON Schema as an OpenAPI document so openapi-typescript accepts it."""
    root_schema = dict(ws_schema)
    defs = root_schema.pop("$defs", {})
    assert isinstance(defs, dict)
    schemas = {"LiveWsPayload": _rewrite_defs_refs(root_schema)}
    schemas.update({name: _rewrite_defs_refs(schema) for name, schema in defs.items()})
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "VibeSensor WebSocket Payload",
            "version": _ws_schema_version(ws_schema),
        },
        "paths": {},
        "components": {"schemas": schemas},
    }


def _ws_schema_version(ws_schema: dict[str, object]) -> str:
    properties = ws_schema.get("properties")
    assert isinstance(properties, dict)
    schema_version = properties["schema_version"]
    assert isinstance(schema_version, dict)
    return str(schema_version.get("default", "1"))


def _render_ws_types(tmp_dir: Path) -> str:
    ws_schema = json.loads(export_ws_schema())
    openapi_path = tmp_dir / "ws_openapi.json"
    openapi_path.write_text(
        json.dumps(_ws_schema_as_openapi(ws_schema), indent=2), "utf-8"
    )
    aliases = "".join(
        f'export type {alias} = WsSchema<"{name}">;\n'
        for alias, name in _WS_ALIASES.items()
    )
    return (
        _GENERATED_HEADER.format(source="vibesensor.cli.ws_schema_export")
        + _openapi_typescript(openapi_path)
        + "\n"
        + f"export const EXPECTED_SCHEMA_VERSION = {json.dumps(_ws_schema_version(ws_schema))}"
        + " as const;\n\n"
        + 'type WsSchema<Name extends keyof components["schemas"]> = '
        + 'components["schemas"][Name];\n\n'
        + aliases
    )


def _render_http_types(tmp_dir: Path) -> str:
    schema_path = tmp_dir / "http_api_schema.json"
    export_http_schema(out_path=schema_path)
    return _GENERATED_HEADER.format(
        source="vibesensor.cli.http_api_schema_export"
    ) + _openapi_typescript(schema_path)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vibesensor-contracts-") as tmp:
        tmp_dir = Path(tmp)
        outputs = {
            HTTP_TYPES_PATH: _render_http_types(tmp_dir),
            WS_TYPES_PATH: _render_ws_types(tmp_dir),
            CONSTANTS_PATH: render_ui_shared_constants_module(),
            PROTOCOL_DOC_PATH: render_contract_reference_markdown(),
        }
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
