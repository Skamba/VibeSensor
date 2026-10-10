# History DB Schema (v15)

The VibeSensor server stores run history, samples, analysis results,
application settings and client names in a single SQLite file located at
`~/.vibesensor/history.db` (or the path specified by `--data-dir`).

## Design goals

| Goal | Approach |
|------|----------|
| Low overhead on Raspberry Pi 3A+ | WAL journal mode, batched inserts (256 rows), typed columns (no per-row JSON parsing) |
| Efficient long recordings | Keyset pagination (`id > ?`), streaming iterator, no full-run memory load; post-analysis selects rows from a light column pass and decodes only those |
| Queryable time-series | Typed columns for accel, speed, frequency, strength; indexed by `(run_id, t_s)` |

## Module organization

`history/` (`history_db.py` and its `*_store.py` helpers) is one synchronous repository over stdlib `sqlite3`:

- `history_db.py`: `HistoryDB`. Constructing it opens a writer connection and a
  `query_only` reader connection (WAL lets reads proceed during writes), each guarded by a
  `threading.Lock`, then enforces the schema and runs `PRAGMA quick_check`. It owns run
  creation/finalization, sample appends and keyset-paginated reads, analysis writes, delete
  and free-space pruning, stale-recording recovery, settings snapshots, and client names.
  Async callers (route handlers, history use cases) offload calls with `asyncio.to_thread`.
- `db_schema.py`: schema DDL, `SCHEMA_VERSION`, open-time schema enforcement, quick check, and
  incompatible-schema backup/run-summary export.
- `db_projection.py`: row-to-record projection for history list/detail reads.
- `sample_store.py`: row-serialization helpers for `samples_v2`.
- `raw_capture_store.py`: file-backed raw waveform sidecars next to the DB file.

## Tables

### `runs`

One row per recording session.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | UUID for the run |
| `case_id` | TEXT | Diagnostic case this run belongs to |
| `status` | TEXT | `recording` → `analyzing` → `complete` (or `error`). CHECK constraint enforces valid values. Transitions are enforced atomically via WHERE guards. |
| `start_time_utc` | TEXT | ISO-8601 start time |
| `end_time_utc` | TEXT | ISO-8601 end time (set on finalize) |
| `metadata_json` | TEXT | Run-level metadata (car config, language, sensor model, etc.) |
| `car_name` | TEXT | Denormalized active car name used by the history list path |
| `raw_capture_manifest_json` | TEXT | Raw waveform sidecar manifest; may remain after raw files are pruned so history can report missing raw capture explicitly |
| `analysis_json` | TEXT | Post-run analysis summary (`AnalysisSummary` in `summary/contracts.py`) |
| `error_message` | TEXT | Error description when status = `error` |
| `sample_count` | INTEGER | Running count of appended `samples_v2` rows (analysis windows, not raw accelerometer samples; the raw count is the manifest's `total_samples`) |
| `created_at` | TEXT | Row creation timestamp |
| `analysis_started_at` | TEXT | When analysis started |
| `analysis_completed_at` | TEXT | When analysis finished |

### `samples_v2`

One row per sensor frame — **no JSON blobs**. All `SensorFrame` scalar fields
are stored as typed columns; peak arrays use compact JSON in a TEXT column and
are rehydrated back into typed `SensorFrame.top_peaks` data on read.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment row ID |
| `run_id` | TEXT FK | References `runs(run_id)` with `ON DELETE CASCADE` |
| `timestamp_utc` | TEXT | ISO-8601 sample time |
| `t_s` | REAL | Seconds since run start (monotonic) |
| `analysis_window_start_us` | INTEGER | Optional start of the row's FFT block in run-monotonic microseconds (never negative for a synced window) |
| `analysis_window_end_us` | INTEGER | Optional raw-analysis window end timestamp in run-monotonic microseconds |
| `analysis_window_synced` | INTEGER | Optional boolean flag (`0`/`1`) indicating whether the analysis window is synchronized to raw capture timing |
| `client_id` | TEXT | Sensor MAC address (hex) |
| `client_name` | TEXT | Human-readable sensor name |
| `location` | TEXT | Mounting position (e.g. `front_left`) |
| `sample_rate_hz` | INTEGER | Raw ADC sample rate |
| `speed_kmh` | REAL | Effective vehicle speed |
| `gps_speed_kmh` | REAL | GPS-derived speed |
| `speed_source` | TEXT | `gps`, `obd2`, `manual`, `fallback_manual`, `none`, or `gps_unaligned` / `obd2_unaligned` (live source chosen, no speed for this row) |
| `engine_rpm` | REAL | Engine RPM |
| `engine_rpm_source` | TEXT | Source of RPM data |
| `gear` | REAL | Current gear |
| `final_drive_ratio` | REAL | Final drive ratio |
| `accel_x_g` | REAL | X-axis acceleration (g) |
| `accel_y_g` | REAL | Y-axis acceleration (g) |
| `accel_z_g` | REAL | Z-axis acceleration (g) |
| `dominant_freq_hz` | REAL | Dominant vibration frequency |
| `dominant_axis` | TEXT | Real dominant axis (`x`/`y`/`z`) when one axis clearly owns the strongest peak, `combined` when the strongest peak is non-directional across axes, empty when unavailable |
| `vibration_strength_db` | REAL | Vibration strength in dB |
| `strength_bucket` | TEXT | Strength classification label |
| `strength_peak_amp_g` | REAL | Peak amplitude (g) |
| `strength_floor_amp_g` | REAL | Noise floor amplitude (g) |
| `frames_dropped_total` | INTEGER | Cumulative dropped frames |
| `queue_overflow_drops` | INTEGER | Cumulative sensor queue-overflow drops, without expected (server restart, Bluetooth scan) drops |
| `top_peaks` | TEXT | JSON array of combined top peaks |

**Indexes:**
- `idx_samples_v2_run_id` on `(run_id)` — fast lookup by run
- `idx_samples_v2_run_time` on `(run_id, t_s)` — time-range queries

### `unfinished_analyses`

Post-analysis attempts not yet finished, one row per run being analysed.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | References `runs(run_id)` with `ON DELETE CASCADE` |
| `boot_id` | TEXT | Boot id of the latest attempt's start (`NULL` off Linux) |
| `crash_count` | INTEGER | Attempts that ended with the server process dying in the boot they started in |

`begin_analysis_attempt(run_id, boot_id=...)` (only while the run is
`analyzing`) runs before the worker starts: a row left from the same boot means
the previous attempt crashed the server, so `crash_count` goes up; a row from
another boot (power lost) leaves it unchanged. `store_analysis()` and
`store_analysis_error()` delete the row. A `crash_count` of 2 means the worker
stores the run as `error` instead of trying again (see
`docs/run_lifecycle.md`). The table is created with `CREATE TABLE IF NOT
EXISTS` on every open, so a current-version (v15) database gains it without a
version bump; the same open drops its predecessor `analysis_attempts`, which
counted power cuts as crashes.

### `settings_snapshot`

Single-row table for persistent application settings.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Always 1 (CHECK constraint) |
| `value_json` | TEXT | JSON-encoded settings snapshot |
| `updated_at` | TEXT | Last update timestamp |

`value_json` is decoded by `SettingsSnapshotRecord` in
`settings/snapshot_codec.py` (msgspec, defaults for missing top-level keys).
Each entry in `cars` is a `CarConfigPayload` (`settings/car_config.py`): the
same shape is served by `GET /api/settings/cars`, and it carries the car's
`aspects` (`AnalysisSettingsPayload`) and optional `order_reference_status`.

### `client_names`

Legacy compatibility table for sensor client display names.

Canonical user-managed sensor metadata now lives in the `settings_snapshot`
payload (`sensorsByMac`). The runtime registry may still read `client_names`
for older/offline compatibility paths, but it is no longer the authoritative
home for persisted sensor name/location semantics.

| Column | Type | Description |
|--------|------|-------------|
| `client_id` | TEXT PK | Sensor MAC (hex) |
| `name` | TEXT | Legacy display name |
| `updated_at` | TEXT | Last update timestamp |

## Schema version policy

Schema versioning uses SQLite's `PRAGMA user_version`. The current schema is the
only supported runtime schema. On startup `HistoryDB` checks
the stored integer version:

| Stored version | Action |
|----------------|--------|
| `0` on a fresh DB with no user tables | Create all tables, stamp `user_version = 15` |
| `0` with a legacy `schema_meta` table present | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` without requiring destructive deletion |
| `0` with unexpected user tables | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` |
| `15` | No action needed beyond ensuring current tables/indexes exist |
| Any older value, including `11`-`14` | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` |
| Newer than `15` | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` (downgrade not supported) |

There are no in-place migrations from older history DB versions. Before
rejecting a populated non-current database, `HistoryDB` writes a backup copy under
`history-db-backups/` next to the live database and, when a readable `runs` table
exists, exports a best-effort JSONL summary of stored runs. The server then
raises a clear error; reset or reinstall to create a fresh current-schema DB.

## Performance settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| `journal_mode` | WAL | Allows concurrent reads during writes |
| `wal_autocheckpoint` | 500 | Prevents unbounded WAL growth |
| `foreign_keys` | ON | Cascade deletes for samples when a run is deleted |
| `busy_timeout` | 5000 ms | Waits out short lock contention instead of failing |
| `query_only` | ON (reader connection) | The reader connection can never write |
| Batch insert size | 256 | Balances transaction overhead vs. memory usage |
| Read batch size | 1000 (default) | Keyset pagination for streaming reads |

## Historical storage comparison (approximate)

This comparison records why the schema moved from older opaque sample JSON blobs
to typed `samples_v2` columns. It is historical design context, not current
guidance for choosing a storage version; current databases use schema v15.

For a 30-minute run at 4 Hz × 4 sensors (~28,800 samples):

| Metric | v4 (JSON blobs) | v5 (structured) |
|--------|-----------------|-----------------|
| Storage | ~42 MB | ~15 MB |
| Write speed | Slower (JSON serialize per row) | Faster (typed bind params) |
| Read speed | Slower (JSON parse per row) | Faster (direct column access) |
| Queryable | No (opaque blobs) | Yes (indexed typed columns) |

## Run export

`GET /api/history/{run_id}/export` (History → Export) returns one ZIP:

| Entry | Contents |
|-------|----------|
| `<run>.json` | Run metadata and the stored analysis |
| `<run>_analysis_windows.csv` | One row per `samples_v2` row: the per-window summaries (speed, peaks, strength) the analysis used, not raw samples |
| `raw-capture/manifest.json` | Raw capture manifest (sensors, sample rates, sample counts, clock sync, losses) |
| `raw-capture/<sensor>.raw.i16le` | Raw accelerometer samples, interleaved little-endian int16 x/y/z |
| `raw-capture/<sensor>.index.jsonl` | One line per received chunk: `sample_start`, `sample_count`, first-sample time `t0_us`, `byte_offset` into the `.raw.i16le` file |

The `raw-capture/` entries are left out when the run kept no raw capture (or its
files were pruned). A 10-minute single-sensor run adds about 3 MB before
compression. Export spools that outgrow memory are written next to the database,
not to the Pi's RAM-backed `/tmp`.

## Startup retention policy

On startup, the container opens `HistoryDB`, first recovers runs left
`recording` by a power cut (see "Cut off before Stop" in
`docs/run_lifecycle.md`), then keeps every run, however old, while the disk
holding the database has at least `RUN_HISTORY_MIN_FREE_BYTES` (1 GiB, in
`apps/server/vibesensor/app/composition.py`) free. Below that,
`HistoryDB.prune_oldest_runs_for_free_space` deletes the oldest `complete` or
`error` run (in recording order, `rowid`, so a run stamped on a wrong clock is
not mistaken for old or new) with its raw capture, one at a time, until enough
is free. The database's free pages (`PRAGMA freelist_count`) count as free: the
file does not shrink, but the next runs reuse them. `recording` and `analyzing`
runs are never deleted automatically. The journal logs `Disk below 1024 MiB
free: deleted the N oldest finished run(s): …`.

The 1 GiB floor leaves room for an update's 600 MB download and many drives (a
10-minute single-sensor run is about 3 MB of raw capture plus its sample rows).
Run deletion removes sample rows through the `ON DELETE CASCADE` foreign key on
`samples_v2`, plus the raw-capture sidecar directory.

## Retired whole-run data

Older versions also ran a dense "whole-run" post-analysis and stored its
sidecars under `whole-run-artifacts/<run_id>/` plus a
`runs.whole_run_artifact_manifest_json` column. That pipeline was removed
without a schema-version bump so existing v15 databases keep opening:

- the column is no longer in the DDL; databases created before the removal
  keep it as an unused nullable column that nothing reads or writes
- `HistoryDB` deletes any leftover `whole-run-artifacts/` directory when it opens
- analyses stored before then carry an older `_schema_version` and are
  re-analysed on startup (see below), so retired `whole_run_*` fields never
  reach readers

## Outdated stored analyses

`runs.analysis_json` carries `_schema_version`
(`PERSISTED_ANALYSIS_SCHEMA_VERSION` in `summary/persisted_analysis.py`). When
the summary contract gains a required field or drops one (the top-level
summary forbids unknown keys), or a stored value changes meaning (the
diagnosis's mg scale, its `db_above_floor` floor), the version is bumped. On startup,
`HistoryDB.requeue_outdated_analyses()` moves every `complete` run whose stored
version differs back to `analyzing` with its analysis cleared, and the startup
re-queue of `analyzing` runs re-analyses them from their stored samples (and raw
capture, when still present). Readers treat an analysis with any other version
as unsupported.
