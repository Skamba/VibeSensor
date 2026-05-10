# Canonical Dataflows

This page is the short canonical map for the four server-side dataflows. Use it
to answer "where does this data come from, where does it cross a boundary, and
who consumes it?" Then follow the linked deep dives for step-by-step details.

## Live dataflow

| Field | Value |
|------|-------------|
| Source | UDP sensor datagrams from the ESP32 fleet |
| Main path | `apps/server/vibesensor/adapters/udp/udp_data_rx.py` -> registry + `apps/server/vibesensor/infra/processing/` -> `apps/server/vibesensor/infra/runtime/ws_payload_projection.py` -> `apps/server/vibesensor/infra/runtime/ws_broadcast.py` |
| Boundary | Live WebSocket payload projection only; no history DB or post-stop analysis in this path |
| Final consumer | Dashboard live UI |
| Data shape | Live and transient, not replayable |

Live flow is for "what is happening right now". It may expose connectivity,
speed, spectra, and strength metrics, but it does not carry persisted findings
or PDF/report facts. If live data is stale or absent, the UI shows that state
directly; it does not synthesize history/report readiness from the live path.

Deep dive: `docs/intake_buffering.md`

## Recording dataflow

| Field | Value |
|------|-------------|
| Source | The same UDP stream while a run is active |
| Main path | registry + `apps/server/vibesensor/infra/processing/` -> `apps/server/vibesensor/use_cases/run/sample_flush.py` -> `apps/server/vibesensor/use_cases/run/persistence_writer.py` -> history DB |
| Boundary | `SampleFlushOrchestrator` owns row building/flush timing; `RunPersistenceWriter` owns the history DB boundary |
| Final consumer | Persisted run samples, run metadata, and post-stop queueing |
| Data shape | Persisted summary/sample rows, not replayable raw sensor capture |

Recording flow turns live samples into durable run history. It is the only path
that writes run rows into the history DB during an active run. Missing or
degraded recording artifacts propagate later through persisted run status,
lifecycle, and history/report warnings rather than through the live transport.

Deep dive: `docs/run_lifecycle.md`

## Raw capture dataflow

| Field | Value |
|------|-------------|
| Source | Optional per-run raw capture written alongside an active recording |
| Main path | `use_cases/run/raw_capture_writer.py` -> raw capture manifest/store -> `use_cases/run/post_analysis_loader.py` -> `use_cases/run/post_analysis_input.py` + `raw_capture_replay.py` + `post_analysis_whole_run_builders.py` |
| Boundary | Raw capture is read through `RunPersistence`; compact replay and dense sidecar production stay inside the post-analysis pipeline |
| Final consumer | Offline post-stop analysis: raw replay compatibility plus whole-run sidecar builders |
| Data shape | Persisted and replayable raw artifacts, dense sidecar artifacts, and compact persisted summaries |

Raw capture is not the report path and not the live UI path. Post-analysis may
use raw replay when the manifest/store exists, or fall back to persisted summary
rows when it does not. When raw capture is available, whole-run spectra use
bounded raw range reads, then the sidecar path builds context labels, order
traces/summaries, family
summaries, and spatial coherence through `post_analysis_whole_run_builders.py`
and the `whole_run_*` diagnostics modules. Dense spectra/traces/matrices stay in
`whole-run-artifacts/<run_id>/`; compact report-facing summaries and manifest
metadata are appended to `analysis_json`.

`use_cases/diagnostics/post_run_raw_windows.py` remains a compatibility/support
bounded raw range-window iterator. The connected whole-run spectral executor is
`use_cases/diagnostics/whole_run_spectra.py`. Degraded or missing raw/whole-run
state must propagate forward as
lifecycle/artifact status and report context instead of triggering a second ad
hoc recovery path in history or PDF code.

Deep dives: `docs/run_lifecycle.md`, `docs/analysis_pipeline.md`

## Report dataflow

| Field | Value |
|------|-------------|
| Source | Persisted run metadata, persisted analysis outputs, and already-derived report facts |
| Main path | history DB -> `use_cases/history/report_loader.py` -> shared report boundaries/fact builders -> `app/container.py::_build_pdf_bytes` -> PDF/UI consumers |
| Boundary | History/report loading reads persisted truth only; it does not rerun live processing or raw replay directly |
| Final consumer | History detail UI, quick report readiness, and generated PDFs |
| Data shape | Persisted, replay-free report state |

Report flow is the read-side consumer of completed run truth. It can surface
degraded or missing analysis/raw artifacts, but it must do so from persisted
lifecycle/artifact/report state rather than by bypassing back into recording or
raw-capture internals.

Deep dives: `docs/analysis_pipeline.md`, `docs/report_pipeline.md`, `docs/run_lifecycle.md`

## Guard mapping

Each flow has at least one automated architecture/static guard:

| Flow | Guard owner |
|------|-------------|
| Live | `tools/dev/verify_backend_static_guards.py`: live processing stays analysis-free; `WsBroadcast` stays behind `ws_payload_projection` |
| Recording | `tools/dev/verify_backend_static_guards.py`: recording flow uses `sample_flush` and `persistence_writer` |
| Raw capture | `tools/dev/verify_backend_static_guards.py`: raw capture replay stays in post-analysis boundaries |
| Report | `tools/dev/verify_backend_static_guards.py`: report loader avoids boundary re-wraps; PDF entrypoint renders `ReportDocument` |
