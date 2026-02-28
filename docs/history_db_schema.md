# History DB Schema (v5)

The VibeSensor server stores run history, samples, analysis results,
application settings and client names in a single SQLite file located at
`~/.vibesensor/history.db` (or the path specified by `--data-dir`).

## Design goals

| Goal | Approach |
|------|----------|
| Low overhead on Raspberry Pi 3A+ | WAL journal mode, batched inserts (256 rows), typed columns (no per-row JSON parsing) |
| Efficient long recordings | Keyset pagination (`id > ?`), streaming iterator, no full-run memory load |
| Queryable time-series | Typed columns for accel, speed, frequency, strength; indexed by `(run_id, t_s)` |
| Backward compatibility | Legacy v4 JSON-blob rows remain readable; auto-migration on first open |

## Tables

### `schema_meta`

Single-row key-value table tracking the schema version.

| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | Always `'version'` |
| `value` | TEXT | Current schema version (`'5'`) |

### `runs`

One row per recording session.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | UUID for the run |
| `status` | TEXT | `recording` → `analyzing` → `complete` (or `error`) |
| `start_time_utc` | TEXT | ISO-8601 start time |
| `end_time_utc` | TEXT | ISO-8601 end time (set on finalize) |
| `metadata_json` | TEXT | Run-level metadata (car config, language, sensor model, etc.) |
| `analysis_json` | TEXT | Post-run analysis summary |
| `error_message` | TEXT | Error description when status = `error` |
| `sample_count` | INTEGER | Running count of appended samples |
| `created_at` | TEXT | Row creation timestamp |
| `analysis_version` | INTEGER | Schema version of the analysis result |
| `analysis_started_at` | TEXT | When analysis started |
| `analysis_completed_at` | TEXT | When analysis finished |

### `samples_v2` (new in v5)

One row per sensor frame — **no JSON blobs**. All SensorFrame scalar fields
are stored as typed columns; peak arrays use compact JSON in TEXT columns.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment row ID |
| `run_id` | TEXT FK | References `runs(run_id)` with `ON DELETE CASCADE` |
| `record_type` | TEXT | Always `'sample'` |
| `schema_version` | TEXT | E.g. `'v2-jsonl'` |
| `timestamp_utc` | TEXT | ISO-8601 sample time |
| `t_s` | REAL | Seconds since run start (monotonic) |
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
| `dominant_axis` | TEXT | Axis with dominant vibration |
| `vibration_strength_db` | REAL | Vibration strength in dB |
| `strength_bucket` | TEXT | Strength classification label |
| `strength_peak_amp_g` | REAL | Peak amplitude (g) |
| `strength_floor_amp_g` | REAL | Noise floor amplitude (g) |
| `frames_dropped_total` | INTEGER | Cumulative dropped frames |
| `queue_overflow_drops` | INTEGER | Queue overflow drop count |
| `top_peaks` | TEXT | JSON array of combined top peaks |
| `top_peaks_x` | TEXT | JSON array of X-axis top peaks |
| `top_peaks_y` | TEXT | JSON array of Y-axis top peaks |
| `top_peaks_z` | TEXT | JSON array of Z-axis top peaks |
| `extra_json` | TEXT | JSON dict of any non-standard keys |

**Indexes:**
- `idx_samples_v2_run_id` on `(run_id)` — fast lookup by run
- `idx_samples_v2_run_time` on `(run_id, t_s)` — time-range queries

### `samples` (legacy, v4)

Only present in databases migrated from v4. One row per sample with
the entire payload stored as a JSON blob.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment row ID |
| `run_id` | TEXT FK | References `runs(run_id)` with `ON DELETE CASCADE` |
| `sample_json` | TEXT | Full sample payload as JSON |

Legacy rows are read transparently when no `samples_v2` rows exist for
a given run.

### `settings_kv`

Persistent application settings.

| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | Setting name |
| `value_json` | TEXT | JSON-encoded value |
| `updated_at` | TEXT | Last update timestamp |

### `client_names`

Maps sensor client IDs to human-readable names.

| Column | Type | Description |
|--------|------|-------------|
| `client_id` | TEXT PK | Sensor MAC (hex) |
| `name` | TEXT | Display name |
| `updated_at` | TEXT | Last update timestamp |

## Schema upgrades / migrations

Schema versioning uses the `schema_meta` table. On startup `HistoryDB`
checks the stored version (the text value of the `'version'` key):

| Stored version | Action |
|----------------|--------|
| No row (fresh DB, `schema_meta` table just created) | Create all v5 tables, insert version `'5'` |
| `'4'` | Run migration: create `samples_v2` table + indexes, bump to `'5'`. Legacy `samples` table is kept as-is. |
| `'5'` | No action needed |
| Anything else | Raise `RuntimeError` (delete and recreate) |

**Migration from v4 to v5** is non-destructive:
- The old `samples` table is **not** deleted or modified.
- New `samples_v2` table and indexes are created.
- New runs write to `samples_v2`; old runs read from `samples`.
- No data copying is needed — old JSON rows remain readable.

## Performance settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| `journal_mode` | WAL | Allows concurrent reads during writes |
| `wal_autocheckpoint` | 500 | Prevents unbounded WAL growth |
| `foreign_keys` | ON | Cascade deletes for samples when a run is deleted |
| Batch insert size | 256 | Balances transaction overhead vs. memory usage |
| Read batch size | 1000 (default) | Keyset pagination for streaming reads |

## Storage comparison (approximate)

For a 30-minute run at 4 Hz × 4 sensors (~28,800 samples):

| Metric | v4 (JSON blobs) | v5 (structured) |
|--------|-----------------|-----------------|
| Storage | ~42 MB | ~15 MB |
| Write speed | Slower (JSON serialize per row) | Faster (typed bind params) |
| Read speed | Slower (JSON parse per row) | Faster (direct column access) |
| Queryable | No (opaque blobs) | Yes (indexed typed columns) |
