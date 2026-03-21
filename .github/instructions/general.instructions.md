---
applyTo: "**"
---
Agent workflow
- For medium/large tasks, always start with an explicit checklist plan. Use highly descriptive titles that include the problem, the fix, and user impact.
- Work in iterative loops until done: `plan → verify current behavior → root cause → blast radius scan → implement complete maintainable fix → targeted tests → broader relevant tests → re-plan`.
- Verify existing behavior before rewriting code; investigate root cause before patching symptoms.
- Scan the blast radius for similar in-scope issues and fix them in the same run.
- Prefer extending and hardening existing logic over adding parallel implementations.
- When a larger refactor or other major in-scope change is the clearest path to better long-term maintainability, prefer that over a narrowly local patch that preserves poor structure.
- Analysis-first default: examine the issue from multiple angles, choose the strongest approach, and deliver the smallest validated **complete** in-scope fix that addresses root cause and nearby in-scope blast radius.
- Avoid symptom-only patches. Prefer fixes that make sense to a human maintainer and reduce future maintenance burden in the touched area.
- Avoid over-conservative blocking behavior: do not hold a clear fix for exhaustive hypothetical analysis.
- Use bounded risk rather than risk avoidance: keep changes reversible, validate early, and recover quickly on failures.
- Continue autonomously on clearly adjacent in-scope issues without waiting for another prompt.
- Stop only when one of these conditions is true:
  1. all plan items are complete and validated,
  2. no similar in-scope issues remain,
  3. a real blocker exists (credentials/hardware/external dependency),
  4. the user explicitly asks to pause.
- Long, thorough runs are allowed and preferred for deeper tasks; multi-hour runs are acceptable when needed to complete in-scope work well.
- Context/noise control:
  - avoid scanning generated/build/cache/vendor artifacts unless debugging them (`artifacts/`, `.cache/`, `node_modules/`, `dist/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`),
  - use focused file reads and scoped searches,
  - avoid huge command output unless needed.
- No-cheating implementation rules:
  - put executable logic in proper code files, not hidden in docs/json/txt wrappers,
  - when adding large inline data definitions, move them into appropriate data files (`.json`, `.yaml`, etc.),
  - do not create duplicate parallel implementations when extending existing logic is cleaner.

Complexity hygiene
- Remove config fields that are not read by any code path. Do not add speculative config knobs.
- Maintain one definition for each default value; do not duplicate defaults across files.
- Do not add forward-extensibility machinery (overflow columns, plugin hooks, generic registries) until a concrete second consumer exists.
- Prefer flat, direct structures. Only introduce grouping or wrapping when more than three consumers benefit from the indirection.
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
- Pull request default mode: after opening or updating a PR, check CI/review status, fix all blocking issues, push updates, and keep monitoring until required checks are green.
- Use the command list (defined in the copilot instructions "Commands" section) for PR check watching, lint/type checks, CI-parity runs, single-area pytest runs, and local Docker bring-up; use `docs/testing.md` for test layout, CI limitations, and the optional `act` wrapper, and follow targeted → broader → local-GitHub-workflow validation before finalizing any task.
- Treat watcher exit `RESULT=NON_GREEN` as immediate action: inspect the latest failing run promptly, determine root cause, implement the smallest complete maintainable fix, push, and restart the watcher.
- Treat watcher exit `RESULT=ALL_GREEN` as the merge-ready gate for CI checks.
- If an intentional refactor changes function-level seams or helper boundaries, refactor the affected tests in the same change set so they validate current behavior instead of pinning obsolete internals.
- After any backend or frontend change, exercise the local Docker stack with the commands listed in copilot-instructions (compose up + simulator), confirm `http://127.0.0.1` updates live (`:8000` fallback if `:80` is not serving), then verify updates stop once the simulator stops; inspect container logs if needed.
- Breaking changes are allowed when intentional.
- No-backward-compatibility policy: we own the full codebase end to end. Do not add or preserve backward-compatibility layers (deprecated paths, adapters, fallbacks, shims, version-bridging logic, or legacy schema support) unless explicitly asked. Remove them when encountered. Standardize on the current contract, schema, config, and runtime path. Do not add new compatibility code "just in case". If compatibility seems necessary, flag it explicitly rather than implementing it silently.

Docs (`docs/`)
- Keep `docs/` short and focused. Add design changes (e.g. report layout) to `docs/design_language.md`.
- Rewrite or remove stale sections aggressively; do not keep contradictory historical guidance in place.
- Prefer direct pointers to the files that own current commands or workflows over long prose that will drift.
- Keep ownership-language rare. Use it only when a file genuinely owns a fact that other docs should not restate.

Infra / Docker / CI (`docker-compose.yml`, `.github/workflows/`)
- CI: see `.github/workflows/ci.yml` for blocking job names and job commands; do not duplicate that list elsewhere.
- Keep CI steps maintainable; larger CI/workflow updates are allowed when needed. If adding new test dependencies, update `apps/server/pyproject.toml` so CI installs them via the editable install.
- Avoid embedding secrets in workflow files; use repository secrets for tokens.
