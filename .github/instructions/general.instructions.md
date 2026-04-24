---
applyTo: "**"
---
Scope: shared workflow, validation, documentation maintenance, and execution guardrails. Keep canonical AI guidance and architectural invariants in `.github/copilot-instructions.md`, and keep repository layout/navigation in `docs/ai/repo-map.md`.

Agent workflow
- For medium/large tasks, always start with an explicit checklist plan. Use highly descriptive titles that include the problem, the fix, and user impact.
- Work in iterative loops until done: `plan → verify current behavior → root cause → blast radius scan → implement complete maintainable fix → targeted tests → broader relevant tests → re-plan`.
- Verify existing behavior before rewriting code; investigate root cause before patching symptoms.
- Scan the blast radius for similar in-scope issues and fix them in the same run.
- Prefer extending and hardening existing logic over adding parallel implementations.
- When a larger refactor or other major in-scope change is the clearest path to better long-term maintainability, prefer that over a narrowly local patch that preserves poor structure.
- Analysis-first default: examine the issue from multiple angles, choose the strongest approach, and deliver the most direct, validated, complete in-scope fix that addresses root cause and nearby in-scope blast radius.
- Avoid symptom-only patches. Prefer fixes that make sense to a human maintainer and reduce future maintenance burden in the touched area.
- Avoid over-conservative blocking behavior: do not hold a clear fix for exhaustive hypothetical analysis.
- Use bounded risk rather than risk avoidance: keep changes reversible, validate early, and recover quickly on failures.
- Continue autonomously on clearly adjacent in-scope issues without waiting for another prompt, but do not turn incidental cleanup into a new project.
- Stop only when one of these conditions is true:
  1. all plan items are complete and validated,
  2. no similar in-scope issues remain,
  3. a real blocker exists (credentials/hardware/external dependency),
  4. the user explicitly asks to pause.
- Long, thorough runs are allowed for deeper tasks when the requested scope and validation needs justify them.
- Execution-completion bias: finish the requested work, not merely a first pass. Do not stop at analysis, planning, or partial implementation. Do not treat "first green test pass" as completion if architectural residue remains.
- Task size is not a blocker by itself. For large tasks, decompose into execution buckets and work through the in-scope buckets in order.
- Avoid hedging language such as "this is probably too large for one session" or "I'll do as much as possible." Instead, state the execution buckets, current validation target, and any real blocker.
- Context/noise control:
  - avoid scanning generated/build/cache/vendor artifacts unless debugging them (`artifacts/`, `.cache/`, `node_modules/`, `dist/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`),
  - use focused file reads and scoped searches,
  - avoid huge command output unless needed.
- No-cheating implementation rules:
  - put executable logic in proper code files, not hidden in docs/json/txt wrappers,
  - when adding large inline data definitions, move them into appropriate data files (`.json`, `.yaml`, etc.),
  - do not create duplicate parallel implementations when extending existing logic is cleaner.

Deliberate reasoning gates
- Medium/large code changes need an architecture pass before edits: owner module, data flow, invariants, root cause, and validation target.
- Compare at least two viable approaches before non-trivial implementation, then choose the one that best preserves correctness, simplicity, and existing architecture.
- Gather current-behavior evidence before refactoring: read owner code, direct callers, and nearest tests; run or inspect the closest relevant test when practical.
- When an AI mistake repeats, prefer a lint/static guard/hygiene test or tighter path-scoped instruction over more prose.
- Keep instructions short and scoped: repo-wide rules must affect most tasks; area rules belong near their paths; add a rule only when removing it would cause real mistakes.

Complexity hygiene
- Remove config fields that are not read by any code path. Do not add speculative config knobs.
- Maintain one definition for each default value; do not duplicate defaults across files.
- Do not add forward-extensibility machinery (overflow columns, plugin hooks, generic registries) until a concrete second consumer exists.
- Prefer flat, direct structures. Only introduce grouping or wrapping when more than three consumers benefit from the indirection.
- Aggressive simplification: remove wrappers, shims, compatibility adapters, and transitional architecture when they no longer serve a real consumer. Do not preserve them out of caution or habit.
- Aggressive consolidation: collapse toward one canonical code path. Dead code, obsolete fallback branches, and duplicate implementations must be deleted outright, not archived or left behind.
- Aggressive caller updates: when a refactor requires touching many files or all callers, touch all of them. Coordinated, invasive changes that produce a cleaner result are preferred over partial migrations that leave residue in place.
- Aggressive deletion of dead code and transitional architecture is preferred. Do not keep migration scaffolding, deprecated aliases, or old DTO shapes once they are no longer consumed.
- Route handlers must be thin HTTP translators. Extract business logic into service functions that are independently testable.
- Do not create duplicate API endpoints for the same operation.
- Do not duplicate utility functions across modules. Maintain one implementation and import from it. Exception: standalone tooling scripts (e.g. ``tools/build_ui_static.py``) that must run without the server package installed may carry a local copy; mark it with a comment pointing at the primary source.

Documentation maintenance (always required)
- Before merging, review whether docs, repo maps, runbooks, READMEs, and instruction files that reference the touched area have gone stale, and update the relevant ones unless the user explicitly asks you not to touch docs.
- Remove or rewrite obsolete guidance instead of layering caveats on top of it.
- Keep human-facing docs and AI-facing guidance aligned with the live code, paths, commands, and ownership boundaries.

Updater deployment policy
- Treat updater delivery as wheel-first. Runtime fixes must land in repo code and flow through PR/CI; avoid relying on ad-hoc runtime file edits.
- Emergency-only exception: if updater path is broken on a live device, temporary in-place patching on the device is allowed strictly to restore service.
- After any emergency in-place patch, complete the follow-up loop in the same run when feasible: repo fix + tests/lint + PR green + merge + successful updater rerun on device.

Validation (always required)
- Pull request default mode: after opening or updating a PR that should land once checks pass, start the compact watcher from the command list with `--merge-on-green`, use its state-change output as the default CI monitor, fix all blocking issues, push updates, and restart the watcher until it exits successfully. Omit `--merge-on-green` only when the user explicitly wants the PR left open or draft.
- Use the command list (defined in the copilot instructions "Commands" section) for PR check watching, lint/type checks, CI-parity runs, single-area pytest runs, and local Docker bring-up; prefer the watcher over repeated full PR-status dumps, use `docs/testing.md` for test layout, CI limitations, and the optional `act` wrapper, and follow targeted → broader → local-GitHub-workflow validation before finalizing any task.
- Treat watcher exit `RESULT=NON_GREEN` or `RESULT=MERGE_FAILED` as immediate action: inspect the latest failing run or merge blocker promptly, determine root cause, implement the smallest complete maintainable fix, push, and restart the watcher.
- Treat watcher exit `RESULT=MERGED` as the success gate for merge-on-green runs. Treat `RESULT=ALL_GREEN` as the success gate only in watch-only mode.
- If an intentional refactor changes function-level seams or helper boundaries, refactor the affected tests in the same change set so they validate current behavior instead of pinning obsolete internals.
- For runtime-affecting backend or frontend changes that alter local integration behavior (HTTP/WS flows, runtime wiring, static asset serving, container/dev-stack behavior, or UI flows exercised against the live server), exercise the local Docker stack with the commands listed in copilot-instructions (compose up + simulator), confirm `http://127.0.0.1` updates live (`:8000` fallback if `:80` is not serving), then verify updates stop once the simulator stops; inspect container logs if needed.
- Use proportionate validation instead of the local Docker stack for docs-only changes, AI-instruction-only changes, README/repo-map/docs-lint edits, pure test-only changes that do not alter runtime behavior, and CI/workflow-only changes unless they also change local stack behavior.
- Breaking changes are allowed when intentional.
- No-backward-compatibility policy: we own the full codebase end to end. Do not add or preserve backward-compatibility layers (deprecated paths, adapters, fallbacks, shims, version-bridging logic, or legacy schema support) unless explicitly asked. Remove them when encountered. Standardize on the current contract, schema, config, and runtime path. Do not add new compatibility code "just in case". If compatibility seems necessary, flag it explicitly rather than implementing it silently. Internal-only backward compatibility is never the default: when the repo controls both producers and consumers, coordinated breaking changes are preferred over preserving old shapes. The cleaner architecture always wins over old migration scaffolding.
- Completion reports should state files changed, validation commands run, any validation skipped with the reason, and whether docs or AI guidance were updated or confirmed unnecessary.

Docs (`docs/`)
- Keep `docs/` short and focused. Add design changes (e.g. report layout) to `docs/design_language.md`.
- Rewrite or remove stale sections aggressively; do not keep contradictory historical guidance in place.
- Prefer direct pointers to the files that own current commands or workflows over long prose that will drift.
- Keep ownership-language rare. Use it only when a file genuinely owns a fact that other docs should not restate.

Infra / Docker / CI (`docker-compose.yml`, `.github/workflows/`)
- CI: see `.github/workflows/ci.yml` for blocking job names and job commands; do not duplicate that list elsewhere.
- Keep CI steps maintainable; larger CI/workflow updates are allowed when needed. If adding new test dependencies, update `apps/server/pyproject.toml` so CI installs them via the editable install.
- Avoid embedding secrets in workflow files; use repository secrets for tokens.
