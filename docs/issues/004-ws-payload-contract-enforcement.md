# [Non-security] Server↔UI live WebSocket payload contract has no schema version or enforcement

**Labels:** reliability, maintainability, backend, frontend

## Summary

The live WebSocket payload between the Python server and the TypeScript UI has
no schema version field, no shared type definition, and no automated
compatibility check. The server builds a `dict[str, Any]` and the UI manually
parses it with defensive runtime checks. A field rename, removal, or type
change on either side will silently break the other with no clear error.

## Evidence

| File | Symbol / Line | Observation |
|---|---|---|
| `apps/server/vibesensor/app.py` | `build_ws_payload()` L274-309 | Constructs payload as untyped `dict[str, Any]` |
| `apps/ui/src/server_payload.ts` | `adaptServerPayload()` L105-192 | Parses raw JSON with manual `typeof` / `Array.isArray()` guards |
| `apps/ui/src/server_payload.ts` | `ClientInfo` type L9-17 | Includes `[key: string]: unknown` catch-all, silently accepts arbitrary extra fields |
| `apps/ui/src/ws.ts` | `onmessage` L83-96 | Raw `JSON.parse()` with no version or schema check |
| `apps/server/vibesensor/ws_hub.py` | `broadcast()` L94-171 | Serialises `payload_builder` result directly with no schema validation |
| `libs/shared/contracts/` | `metrics_fields.json` | Shared contracts exist for metric field names but NOT for the live WS payload structure |
| Both | — | No `payload_version` or `schema_version` field anywhere in the WS payload |

### Concrete mismatch risk

The server payload shape is defined implicitly by `build_ws_payload()`:
```
{server_time, speed_mps, clients, selected_client_id, rotational_speeds, spectra, diagnostics}
```

The UI adapter at `server_payload.ts` expects exactly this shape but verifies
it field-by-field at runtime with defensive checks. If, for example, the server
renames `speed_mps` to `speed_m_s` or restructures `diagnostics`, the UI would
silently fall back to default values (`null`, `[]`, `{}`) without any error
visible to the user or logged anywhere.

The `ClientInfo` type uses `[key: string]: unknown` (L16-17), meaning the
TypeScript compiler cannot catch field name mismatches at compile time.

### No version negotiation

There is no mechanism for the UI to know which payload version the server is
sending. If the server is updated but the browser cache serves an old UI
bundle (or vice versa), there is no compatibility check or graceful
degradation. The `WsClient` class in `ws.ts` will simply display stale or
missing data.

## Impact

- Server or UI changes that modify the payload shape can silently break the
  live dashboard with no error message, causing a frustrating debugging
  experience.
- Stale browser caches after an update can cause the UI to show incorrect or
  missing data.
- The lack of a shared schema makes it impossible to auto-generate type-safe
  code or validate payloads in tests.

## Suggested direction

- Add a `payload_version: int` field to the WS payload and increment it on
  breaking changes. The UI can check this field and show a "please refresh"
  banner when it encounters an unknown version.
- Define a shared schema (e.g. JSON Schema or a TypeScript interface generated
  from the Python dataclass) and validate it in CI tests.
- Remove the `[key: string]: unknown` catch-all from `ClientInfo` and other
  types to enable compile-time field validation.
