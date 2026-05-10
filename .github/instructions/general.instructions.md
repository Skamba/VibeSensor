---
applyTo: "**"
---
Scope: global workflow, validation, docs, PR/CI, safety, and simplification rules. Keep repo invariants in `.github/copilot-instructions.md`, navigation in `docs/ai/repo-map.md`, and area deltas in sibling instruction files.

## Work loop
- For medium/large tasks, start with an explicit checklist plan. For user-requested trackers, create and update the tracker as work progresses.
- Iterate until done: plan -> verify current behavior -> identify owner/root cause -> scan bounded blast radius -> implement a maintainable fix -> run targeted then broader relevant validation -> re-plan if needed.
- Inspect the repo instead of guessing. Verify current behavior before rewriting, and fix root cause rather than symptoms.
- Continue autonomously through obvious safe next steps, including branch-caused test/CI failures. Stop only when complete and validated, explicitly blocked, or the user pauses.
- Keep scope to the request, direct callers, root-cause fixes, and clearly adjacent regressions found during validation.
- If blocked by credentials, hardware, external services, or unrelated failures, state the blocker and evidence plainly.
- Avoid huge context dumps. Use focused reads/searches; skip generated/build/cache/vendor artifacts unless debugging them.

## Simplicity and architecture
- Prefer one owner, one code path, and one source of truth.
- Prefer direct fixes over new abstractions. Add indirection only for a concrete second consumer or clear maintainability win.
- Do not add speculative config knobs, shims, deprecated aliases, compatibility adapters, fallback paths, duplicate implementations, or old/new parallel paths unless explicitly required.
- When replacing behavior, update callers and remove obsolete paths in the same change.
- Keep route handlers thin HTTP translators; put business logic in independently testable services/use cases.
- Do not duplicate utility functions. Exception: standalone tooling that cannot import the server package may carry a local copy with a comment pointing to the primary source.
- Put executable logic in code, not docs/json/txt wrappers. Move large inline data to appropriate data files.
- Breaking internal-only interfaces is allowed when cleaner; this repo owns both producers and consumers.

## Documentation
- Update docs, runbooks, READMEs, repo maps, and instructions when behavior, contracts, commands, config, paths, or user-facing operations change. Avoid doc churn for unaffected areas.
- Documentation scans must be bounded. Search touched symbols, paths, commands, config names, and public behavior with `rg`. Do not browse all docs unless the task is documentation-wide.
- Keep docs consistent with code. Rewrite or remove stale guidance instead of layering caveats.
- Historical or superseded docs are reference only unless they explicitly say they are Active.

## Validation
- Use proportionate validation. Start with `make plan-validation`; run `./.venv/bin/python tools/tests/plan_validation.py --run` for planned non-Docker jobs, or ACT only for workflow/Docker parity.
- Run targeted tests for the changed seam, then broader relevant gates. Do not run heavy unrelated builds unless the touched area requires them.
- Docs/instruction-only changes should run `make docs-lint` and the validation planner, not the local Docker stack.
- Runtime-affecting backend/frontend changes that alter HTTP/WS flows, runtime wiring, static asset serving, container/dev-stack behavior, or live UI flows require the local Docker stack and simulator flow from the canonical command docs.
- If a refactor changes seams, update tests to validate current behavior instead of obsolete internals.
- Completion reports must state files changed, validation run, skipped validation with reasons, and whether docs/AI guidance were updated or unnecessary.

## PR and CI
- After opening/updating a PR intended to land, run `./.venv/bin/python tools/watch_pr_checks.py --pr <PR_NUMBER> --repo Skamba/VibeSensor --merge-on-green`.
- Treat watcher `RESULT=NON_GREEN`, `RESULT=MERGE_ISSUES`, or `RESULT=MERGE_FAILED` as actionable: inspect annotations and concise log tails, fix branch-caused failures, push, and restart the watcher.
- `RESULT=MERGED` is success for merge-on-green; `RESULT=ALL_GREEN` is success only for watch-only.
- Do not merge on red required checks. Document unrelated or flaky blockers.
- Prefer squash merge unless the repo convention or user says otherwise.
- Avoid full CI log dumps; use failing annotations, test names, and short tails first.

## Security and CI hygiene
- Do not commit secrets, local credentials, `.secrets.act`, tokens, certificates, or device-specific private data.
- Do not weaken authentication, validation, update integrity checks, network safety, or offline-first device defaults.
- Keep CI steps maintainable. If workflow tests need new dependencies, declare them in the owning package config.
- Avoid embedding secrets in workflows; use repository secrets.
