# AI Enablement Progress Log

## Iteration 1
### Diagnose
- AI sessions spend too many tokens rediscovering architecture and invariants.
- No canonical small context pack exists.

### Plan
1. Create `docs/ai/context.md` with architecture + invariants.
2. Establish append-only progress log.

### Implement
- Added `docs/ai/context.md` with purpose, user journeys, boundaries, invariants, and minimal read set.
- Added this progress log.

### Validate
- Command: `test -s docs/ai/context.md`
- Result: file exists and non-empty.

### Why this reduces prompt size
- Future agents can start from a single canonical context doc instead of scanning large README/code files.

### Next iteration plan
1. Add canonical entry-point map.
2. Mark safe change zones and hot spots.

## Iteration 2
### Diagnose
- Change requests still require broad file discovery.
- No stable index of critical files and module boundaries.

### Plan
1. Add `docs/ai/map.md` with key entry points and boundaries.
2. Add short decision record for recurring constraints.

### Implement
- Added `docs/ai/map.md` with 20 key entry points, boundaries, hot spots, and safe areas.
- Added `docs/ai/decisions.md` to preserve non-obvious architectural constraints.

### Validate
- Command: `test -s docs/ai/map.md && test -s docs/ai/decisions.md`
- Result: both files exist and non-empty.

### Why this reduces prompt size
- Agents can pick <=10 files from a known map instead of repo-wide search.

### Next iteration plan
1. Add low-noise runbooks.
2. Add AI task runner commands.

## Iteration 3
### Diagnose
- Daily checks are noisy and inconsistent, causing token-heavy terminal logs.
- No single command exists for low-noise AI validation.

### Plan
1. Add `docs/ai/runbooks.md` with minimal commands.
2. Add `scripts/ai/task` with `ai:check`, `ai:test`, `ai:smoke`, `ai:pack`.

### Implement
- Added `docs/ai/runbooks.md` with setup/run/targeted-check guidance.
- Added executable `scripts/ai/task` that writes full logs to `artifacts/ai/logs/` and prints short summaries.
- Fixed runner portability to use `sys.executable` instead of hardcoded `python`.

### Validate
- Command: `scripts/ai/task ai:check`
- Result: `ruff-check`, `ruff-format-check`, and `line-endings` pass; smoke step skipped until smoke tests are added.

### Why this reduces prompt size
- Future prompts can request `ai:check` and receive concise status lines instead of full command output.

### Next iteration plan
1. Add strict handoff template + issue template.
2. Implement context bundle generator (`scripts/ai/pack`).

## Iteration 4
### Diagnose
- Future prompts still vary in format and scope, creating noisy exploratory work.
- No reusable compact context bundle exists.

### Plan
1. Add strict handoff template for AI change requests.
2. Add GitHub issue template for consistent intake.
3. Add `scripts/ai/pack` context bundle generator.

### Implement
- Added `docs/ai/handoff.md` with strict minimal request format and agent rules.
- Added `.github/ISSUE_TEMPLATE/ai_change_request.md`.
- Added executable `scripts/ai/pack` to generate `artifacts/ai/context-bundle/` with docs, top-level tree, key-file headers, and cheatsheet.
- Added `artifacts/ai/.gitkeep` and ignore rules for generated AI artifacts.

### Validate
- Command: `scripts/ai/task ai:pack`
- Result: pack step passes; bundle created under `artifacts/ai/context-bundle` with summary-only terminal output.

### Why this reduces prompt size
- Agents can attach a deterministic, bounded context bundle instead of pasting broad file dumps.

### Next iteration plan
1. Implement `scripts/ai/triage` for scoped summaries.
2. Add scoped-search guidance tied to triage output.

## Iteration 5
### Diagnose
- AI code discovery is still expensive when starting from an ambiguous folder.
- Scoped call-site summaries are not standardized.

### Plan
1. Add `scripts/ai/triage` for bounded module/interface summaries.
2. Wire triage usage into runbooks.

### Implement
- Added executable `scripts/ai/triage`:
	- accepts folder/file/glob target
	- reports module/test counts and sampled public interfaces
	- optionally samples call sites for a given symbol
	- writes details to `artifacts/ai/logs/*-triage-details.txt`
- Updated `docs/ai/runbooks.md` with scoped triage command.

### Validate
- Command: `scripts/ai/triage pi/vibesensor --symbol clients_with_recent_data`
- Result: concise summary printed; detailed report persisted to artifacts log.

### Why this reduces prompt size
- Triage produces compact entry points and interfaces for a narrow area without flooding terminal output.

### Next iteration plan
1. Add narrow smoke tests and marker support.
2. Integrate smoke checks into `ai:smoke`/`ai:check` flow.

## Iteration 6
### Diagnose
- `ai:check` lacked a guaranteed critical-path runtime signal.
- No dedicated smoke marker existed for predictable narrow runs.

### Plan
1. Add pytest `smoke` marker.
2. Add 1–3 focused smoke tests for primary journeys/invariants.
3. Ensure `ai:smoke` and `ai:check` run them quietly.

### Implement
- Added `smoke` marker in `pi/pyproject.toml`.
- Added `pi/tests/test_ai_smoke.py` with three minimal checks:
	- `/api/health` route registration.
	- no runtime `apt-get` in hotspot script.
	- image build wrapper includes hotspot dependency/drop-in assertions.

### Validate
- Command: `scripts/ai/task ai:smoke && scripts/ai/task ai:check`
- Result: smoke + lint + line-ending checks pass with compact output and logs in `artifacts/ai/logs/`.

### Why this reduces prompt size
- Agents can run a single smoke command for high-confidence sanity without broad test output.

### Next iteration plan
1. Reduce hidden knowledge by documenting local module boundaries near code.
2. Add a small, stable backend boundary note for safer edits.

## Iteration 7
### Diagnose
- Some critical invariants were implicit and scattered across multiple files.
- Future agents could still over-read backend files to infer boundaries.

### Plan
1. Add local backend boundary reference near source modules.
2. Add in-code invariant comments where boot/runtime ordering matters.

### Implement
- Added `pi/vibesensor/BOUNDARIES.md` with orchestration/computation/API/persistence/device boundaries.
- Added module-level boundary docstring in `pi/vibesensor/app.py`.
- Added explicit boot-order invariant comment in `pi/scripts/hotspot_nmcli.sh`.

### Validate
- Command: `bash -n pi/scripts/hotspot_nmcli.sh && ruff check pi/vibesensor/app.py pi/tests/test_ai_smoke.py && scripts/ai/task ai:smoke`
- Result: all checks pass.

### Why this reduces prompt size
- Key invariants are now local to the touched modules, reducing cross-file context gathering.

### Next iteration plan
1. Consolidate docs and remove overlap.
2. Verify end-to-end AI tooling workflow (`ai:pack`, `ai:check`, `ai:test`).

## Iteration 8
### Diagnose
- Tooling existed but needed a simpler common entrypoint for day-to-day use.
- Needed final verification that docs + scripts + tests align.

### Plan
1. Add a lightweight task runner wrapper (`Makefile`).
2. Align runbooks with both direct script and make usage.
3. Validate full AI workflow with low-noise outputs.

### Implement
- Added root `Makefile` wrappers: `ai-check`, `ai-test`, `ai-smoke`, `ai-pack` (+ escaped `ai:*` aliases).
- Updated `docs/ai/runbooks.md` to document both direct and make-based commands.

### Validate
- Command:
	- `make ai-check`
	- `make ai-pack`
	- `scripts/ai/task ai:test -- pi/tests/test_ai_smoke.py -q`
	- `make ai-smoke`
- Result: all commands pass; logs persisted to `artifacts/ai/logs/`.

### Why this reduces prompt size
- A future prompt can reference one short command family (`ai-*` / `ai:*`) instead of ad-hoc long command lists.

### Next iteration plan
1. No further structural iteration required for this one-time pass.
2. Keep `docs/ai/progress.md` append-only for future maintenance rounds.
