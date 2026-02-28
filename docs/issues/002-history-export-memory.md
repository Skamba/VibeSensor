# [Non-security] History export builds ZIP in memory and scans the run twice, risking high memory and latency

**Labels:** performance, backend

## Summary

The `/api/history/{run_id}/export` endpoint builds the entire ZIP archive in
an `io.BytesIO` buffer. It also scans the sample set **twice** under a single
read transaction (once for CSV header discovery, once for CSV writing). For
large runs the combination of double-scan + in-memory ZIP can consume hundreds
of megabytes and block the export thread for tens of seconds.

## Evidence

| File | Symbol / Line | Observation |
|---|---|---|
| `apps/server/vibesensor/api.py` | `export_history_run()` L626-690 | Full endpoint |
| `apps/server/vibesensor/api.py` | First scan L643-651 | Iterates all samples via `iter_run_samples()` just to collect fieldnames |
| `apps/server/vibesensor/api.py` | Second scan L673-676 | Iterates all samples **again** to write CSV rows |
| `apps/server/vibesensor/api.py` | ZIP in memory L656-680 | `io.BytesIO()` → `zipfile.ZipFile(zip_buffer)` → `zip_buffer.getvalue()` |
| `apps/server/vibesensor/api.py` | `_EXPORT_BATCH_SIZE = 2048` L80 | Batched reads, but all batches accumulate into the in-memory ZIP |
| `apps/server/vibesensor/api.py` | Thread offload L682 | `await asyncio.to_thread(_build_zip)` – good for async, but the thread itself holds all data |
| `apps/server/vibesensor/history_db.py` | `read_transaction()` L106-119 | Holds the DB lock for the entire double-scan duration |

### Memory estimate for a 30-min run (4 sensors @ 4 Hz)

- 28 800 samples × ~1.5 KB JSON = ~42 MB parsed **twice** (first scan retains
  only fieldnames, but the JSON still must be parsed).
- CSV text before compression: ~28 800 rows × ~0.8 KB ≈ 23 MB.
- ZIP buffer in memory: ~8-15 MB (deflated).
- `getvalue()` copies the buffer: peak memory ≈ CSV + ZIP copy ≈ 30-40 MB.

On the Raspberry Pi 3A+ (512 MB RAM) this is a significant fraction of
available memory and can trigger OOM if another large operation runs
concurrently.

### Latency

The double-scan means every sample row is read from SQLite and `json.loads()`'d
twice. For a 30-min run this is ~57 600 `json.loads()` calls. On Pi hardware
this can take 10-30 seconds, during which the read transaction blocks writes.

## Impact

- Large exports can OOM the Pi or cause the watchdog to restart the service.
- UI shows a spinner with no progress indication during the long export.
- The held read transaction may block concurrent recording writes.

## Suggested direction

- Collect fieldnames during the same pass that writes CSV rows (buffer the
  first batch, emit header, then continue).
- Stream the ZIP to the HTTP response instead of buffering in memory
  (`StreamingResponse` with a generator that yields ZIP chunks).
- If streaming ZIP is too complex, at minimum avoid the double-scan by
  using a fixed/known fieldname order from `SensorFrame.to_dict().keys()`.
