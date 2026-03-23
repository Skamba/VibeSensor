# Contributing

Use this file as the human-facing guide for day-to-day development workflow. Detailed architecture and area-specific rules still live in the focused docs it links to.

## Choose your setup path

- UI-only or quick product checks: use Docker with the simulator.
- Backend logic, tests, or type work: use native Python plus the simulator.
- Firmware work: use the ESP README and PlatformIO toolchain.
- Pi image or deployment-path work: use the server and pi-image READMEs before touching infra.

Primary references:

- Documentation index: [docs/README.md](docs/README.md)
- Repo structure: [docs/ai/repo-map.md](docs/ai/repo-map.md)
- Server setup and deployment: [apps/server/README.md](apps/server/README.md)
- Testing layout and commands: [docs/testing.md](docs/testing.md)
- Operational runbooks: [docs/operational-runbooks.md](docs/operational-runbooks.md)
- Full command reference: [.github/copilot-instructions.md](.github/copilot-instructions.md) § "Commands"

## Local setup

### Docker path

Follow the [Quick Start](README.md#docker-fastest) in the README.

### Native backend path

Start with [README.md#native-python](README.md#native-python) for the native
bootstrap commands.

If you're iterating on the dashboard itself, use
[apps/ui/README.md](apps/ui/README.md) for the frontend dev-server, build, and
contract-sync workflow after that initial bootstrap. In the native setup, the
recommended live-dev path is `vibesensor-server --reload --config
apps/server/config.dev.yaml` plus `npm --prefix apps/ui run dev`, then open
`http://127.0.0.1:5173`.

## Hooks and local safeguards

Enable versioned hooks if you want local guardrails:

```bash
git config core.hooksPath .githooks
```

Current hook behavior:

- Hooks are safe to enable.
- The optional privacy guard only runs when `tools/privacy/privacy_guard.py` exists.
- If a hook blocks you unexpectedly, use the commands below directly and then investigate instead of guessing.

## Validation workflow

Three tiers: use `make test` during iteration, `make test-ci-lite` for the
non-Docker blocking-CI subset, and `make test-all` when you want the broader
local runner (including Docker-backed jobs when Docker is available).

For the recurring repo-wide commands (lint, type checks, docs lint, focused
pytest, CI-parity runs, PR watching, and Docker bring-up), use the command
list in [.github/copilot-instructions.md](.github/copilot-instructions.md)
§ "Commands". Use [docs/testing.md](docs/testing.md) for the test-layout map
and CI-parity guidance.

Additional local-only convenience commands:

| Goal | Command |
|---|---|
| Fast backend tests | `make test` |
| Non-Docker CI subset | `make test-ci-lite` |
| Full local CI runner | `make test-all` |
| Coverage view | `make coverage` |

## CI jobs and local reproduction

The blocking jobs live in
[.github/workflows/ci.yml](.github/workflows/ci.yml). Use the command list in
[.github/copilot-instructions.md](.github/copilot-instructions.md) §
"Commands" plus [docs/testing.md](docs/testing.md) when you need the matching
local reproduction flow.

`backend-quality` includes docs lint, so documentation drift and broken local
markdown links fail PR validation early.

Use `release-smoke` when you need confidence in the packaged wheel and bundled
static assets. Use `e2e` when you need confidence in the Docker/runtime path.
They cover different delivery contracts and neither replaces the other.

When a single shard fails in CI, run the corresponding focused suite locally first instead of rerunning everything.

## Pull requests and merge expectations

- Work on a branch, not directly on `main`.
- Before asking for merge, run the relevant local validation plus the smallest broader suite that matches your change.
- After opening or updating a PR, monitor checks until they are green with the
  PR-watcher command from
  [.github/copilot-instructions.md](.github/copilot-instructions.md) § "Commands".

- Do not merge until required checks are green.

## Documentation expectations

When you change ownership boundaries, commands, or workflows, review the matching docs before merging and update any that became stale. Common touchpoints are:

- [README.md](README.md)
- [apps/server/README.md](apps/server/README.md)
- [docs/testing.md](docs/testing.md)
- [docs/ai/repo-map.md](docs/ai/repo-map.md)
- [docs/operational-runbooks.md](docs/operational-runbooks.md)

Prefer plain pointers to the files that own commands or workflows. Call out
ownership boundaries only when that distinction matters to maintenance.

## Configuration

The backend uses a layered config system. Values are merged in this order (later wins):

1. **Built-in defaults** (`vibesensor.app.settings.DEFAULT_CONFIG`) — always present, never edited
2. **`config.yaml`** — local overrides (gitignored; mostly empty by default)
3. **Environment variables** — override individual keys at runtime

Preset files ship with the repo for common environments:

| File | Purpose |
|---|---|
| `config.dev.yaml` | Native-dev overrides (port 8000, no GPS, relative paths) |
| `config.docker.yaml` | Docker-compose overrides |

**Quick start for local dev:**

```bash
cp apps/server/config.dev.yaml apps/server/config.yaml
```

Then edit `config.yaml` as needed. The file is gitignored, so your local changes won't affect others.

## API contract sync

The contract-sync flow lives in
[apps/ui/README.md#contract-sync](apps/ui/README.md#contract-sync). Use that
section for what `npm run sync:contracts` regenerates (including
`apps/ui/src/constants.ts`) and what to do when CI reports frontend contract
drift.

## Common failure cases

- Hook warning about missing `privacy_guard.py`: this is non-blocking; run the documented validation commands directly.
- Port confusion: production-style access is usually `http://127.0.0.1`, while native dev often uses `http://127.0.0.1:8000`.
- UI contract drift: follow [apps/ui/README.md#contract-sync](apps/ui/README.md#contract-sync) for the generated HTTP/WS/constants sync flow and rerun `npm run sync:contracts`.
- Slow or failing end-to-end runs: check Docker status and the operational runbook before debugging application logic.
