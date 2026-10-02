# History DB Schema (v15)

The VibeSensor server stores run history, samples, analysis results,
application settings and client names in a single SQLite file located at
`~/.vibesensor/history.db` (or the path specified by `--data-dir`).

## Design goals

| Goal | Approach |
|------|----------|
| Low overhead on Raspberry Pi 3A+ | WAL journal mode, batched inserts (256 rows), typed columns (no per-row JSON parsing) |
| Efficient long recordings | Keyset pagination (`id > ?`), streaming iterator, no full-run memory load |
| Queryable time-series | Typed columns for accel, speed, frequency, strength; indexed by `(run_id, t_s)` |

## Module organization

`adapters/persistence/history_db/` is one synchronous repository over stdlib `sqlite3`:

- `_history_db.py`: `HistoryDB`. Constructing it opens a writer connection and a
  `query_only` reader connection (WAL lets reads proceed during writes), each guarded by a
  `threading.Lock`, then enforces the schema and runs `PRAGMA quick_check`. It owns run
  creation/finalization, sample appends and keyset-paginated reads, analysis writes, delete
  and retention flows, stale-recording recovery, settings snapshots, and client names.
  Async callers (route handlers, history use cases) offload calls with `asyncio.to_thread`.
- `_schema.py`: schema DDL, `SCHEMA_VERSION`, open-time schema enforcement, quick check, and
  incompatible-schema backup/run-summary export.
- `_projection.py`: row-to-record projection for history list/detail reads.
- `_samples.py`: row-serialization helpers for `samples_v2`.
- `_raw_capture_store.py` / `_whole_run_artifact_store.py`: file-backed raw waveform and
  whole-run artifact sidecars next to the DB file.

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
| `whole_run_artifact_manifest_json` | TEXT | Whole-run sidecar manifest for dense post-analysis artifacts |
| `analysis_json` | TEXT | Post-run analysis summary (`AnalysisSummary` in `shared/types/history_analysis_contracts.py`) |
| `error_message` | TEXT | Error description when status = `error` |
| `sample_count` | INTEGER | Running count of appended samples |
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
| `analysis_window_start_us` | INTEGER | Optional raw-analysis window start timestamp in run-monotonic microseconds |
| `analysis_window_end_us` | INTEGER | Optional raw-analysis window end timestamp in run-monotonic microseconds |
| `analysis_window_synced` | INTEGER | Optional boolean flag (`0`/`1`) indicating whether the analysis window is synchronized to raw capture timing |
| `client_id` | TEXT | Sensor MAC address (hex) |
| `client_name` | TEXT | Human-readable sensor name |
| `location` | TEXT | Mounting position (e.g. `front_left`) |
| `sample_rate_hz` | INTEGER | Raw ADC sample rate |
| `speed_kmh` | REAL | Effective vehicle speed |
| `gps_speed_kmh` | REAL | GPS-derived speed |
| `speed_source` | TEXT | `gps`, `obd2`, or `manual` |
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
| `queue_overflow_drops` | INTEGER | Queue overflow drop count |
| `top_peaks` | TEXT | JSON array of combined top peaks |

**Indexes:**
- `idx_samples_v2_run_id` on `(run_id)` — fast lookup by run
- `idx_samples_v2_run_time` on `(run_id, t_s)` — time-range queries

### `settings_snapshot`

Single-row table for persistent application settings.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Always 1 (CHECK constraint) |
| `value_json` | TEXT | JSON-encoded settings snapshot |
| `updated_at` | TEXT | Last update timestamp |

`value_json` is decoded by `SettingsSnapshotRecord` in
`shared/boundaries/settings.py` (msgspec, defaults for missing top-level keys).
Each entry in `cars` is a `CarConfigPayload` (`shared/types/car_config.py`): the
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

## Startup retention policy

On startup, the container opens `HistoryDB`, first recovers stale `recording`
rows into `error`, then deletes `complete` and `error` runs older than
`RUN_RETENTION_DAYS` (7 days, in `apps/server/vibesensor/app/composition/history.py`).

The cutoff uses the run's terminal timestamp (`analysis_completed_at`, then
`end_time_utc`, then `created_at`) so active `recording` / `analyzing` runs are
never deleted by the automatic policy. Full run deletion still removes sample
rows through the existing `ON DELETE CASCADE` foreign key on `samples_v2`, plus
raw/whole-run sidecar directories.

## Dense whole-run sidecars

Dense post-run arrays stay outside SQLite under
`whole-run-artifacts/<run_id>/`. The `runs.whole_run_artifact_manifest_json`
column stores only a compact manifest: schema/storage versions, input `run_id`,
window policy, algorithm versions, source raw-capture manifest summaries,
configuration, generated artifact paths, and per-artifact record counts/formats.
The same manifest is also written to `whole-run-artifacts/<run_id>/manifest.json`.

`analysis_json.analysis_metadata` keeps the query-friendly run summary:
availability/status, manifest path, generated timestamp, algorithm versions,
configuration, artifact count/keys/paths/formats, window/sensor counts, warning
codes, and compact top findings/summaries. Dense spectra use `.npy` float32
sidecars; window labels, order traces, summary rows, and spatial coherence rows
use JSONL sidecars. History reads treat missing artifact files as `missing` and
ignore corrupt manifest JSON instead of failing the whole run detail/list path.
