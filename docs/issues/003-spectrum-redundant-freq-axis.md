# [Non-security] WebSocket spectra payload sends redundant per-client frequency axes

**Labels:** performance, backend

## Summary

`multi_spectrum_payload()` sends a top-level shared `freq` array **and** a
duplicate `freq` array inside every per-client entry. In the common case
(all sensors at the same sample rate), the identical frequency axis is
serialised N+1 times (once shared + once per client). This inflates every
heavy WebSocket frame by several kilobytes with no informational benefit.

## Evidence

| File | Symbol / Line | Observation |
|---|---|---|
| `apps/server/vibesensor/processing.py` | `multi_spectrum_payload()` L652-654 | Builds top-level `"freq": shared_freq` |
| `apps/server/vibesensor/processing.py` | Per-client freq L640-641 | `client_payload["freq"] = self._float_list(client_freq)` – adds freq to **every** client |
| `apps/server/vibesensor/processing.py` | `spectrum_payload()` L585-612 | Base per-client payload does NOT include freq – it's injected by `multi_spectrum_payload` |
| `apps/ui/src/server_payload.ts` | `adaptServerPayload()` L176 | UI reads `specObj.freq` from per-client data, ignoring the top-level shared freq |
| `apps/server/vibesensor/processing.py` | Mismatch handling L656-662 | On frequency mismatch, top-level `freq` is emptied and per-client freqs are kept |

### Payload size impact

With a typical FFT window of 1024 and spectrum range limited to e.g. 5-800 Hz
at ~1.5625 Hz resolution, the frequency axis contains ~500 float values.
Each float serialised as JSON is ~6-8 bytes, so each freq array is ~3-4 KB.

For 4 sensors in the common case:
- Necessary: 1 × 4 KB = 4 KB (shared freq)
- Actual: 5 × 4 KB = 20 KB (shared + 4 per-client)
- Waste: **16 KB per heavy frame**, repeated at WS broadcast rate

The UI at `server_payload.ts:176` only reads the per-client `freq`, meaning
the top-level `freq` is computed and serialised but never consumed by the
production UI.

## Impact

- Each heavy WS frame is ~16 KB larger than necessary for 4 sensors.
- On the Pi's limited WiFi hotspot bandwidth, this is measurable overhead
  repeated every heavy-frame tick.
- `_float_list()` conversion and JSON serialisation of the redundant arrays
  also wastes CPU cycles.

## Suggested direction

- In the common case (all clients share the same freq axis), include `freq`
  only at the top level and omit per-client `freq`.
- Include per-client `freq` only when a mismatch is detected (the current
  mismatch code path already handles this scenario).
- Update the UI to prefer the top-level `freq`, falling back to per-client
  `freq` only when the mismatch warning is present.
