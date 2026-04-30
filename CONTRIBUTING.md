# Contributing

Use this file as the human-facing guide for day-to-day development workflow. Detailed architecture and area-specific rules still live in the focused docs it links to.

## Choose your setup path

- UI-only or quick product checks: use Docker with the simulator.
- Backend logic, tests, or type work: use native Python plus the simulator.
- Firmware work: use the ESP README and PlatformIO toolchain.
- Pi image or deployment-path work: use the server and pi-image READMEs before touching infra.

Primary references:

- Documentation index: [docs/README.md](docs/README.md)
- Runtime/toolchain support policy: [docs/runtime_support_matrix.md](docs/runtime_support_matrix.md)
- Repo structure: [docs/ai/repo-map.md](docs/ai/repo-map.md)
- Server setup and deployment: [apps/server/README.md](apps/server/README.md)
- API surface and contracts: [apps/server/README.md#http-and-websocket-surface](apps/server/README.md#http-and-websocket-surface), [apps/ui/README.md#websocket-contract-boundary](apps/ui/README.md#websocket-contract-boundary), and [docs/operational-runbooks.md](docs/operational-runbooks.md)
- Testing layout and commands: [docs/testing.md](docs/testing.md)
- Operational runbooks: [docs/operational-runbooks.md](docs/operational-runbooks.md)
- Full command reference: [.github/copilot-instructions.md](.github/copilot-instructions.md) § "Commands"

## Local setup

Before the first bootstrap, run `make doctor` if you want a quick prerequisite
check against the runtime policy in
[docs/runtime_support_matrix.md](docs/runtime_support_matrix.md) and the
optional Docker/firmware tooling. Run bare `make` any time you want the current
repo command menu.

### Docker path

Use [README.md#docker-quick-product-check](README.md#docker-quick-product-check)
for a production-style container quick check, or
[README.md#docker-dev-mode-source-mounted-hot-reload](README.md#docker-dev-mode-source-mounted-hot-reload)
for the source-mounted backend-reload + Vite dev-server flow.

### Native backend path

Start with
[README.md#native-python--vite-recommended-for-backend-or-ui-iteration](README.md#native-python--vite-recommended-for-backend-or-ui-iteration)
for the native bootstrap commands.

If you're iterating on the dashboard itself, use
[apps/ui/README.md](apps/ui/README.md) for the frontend dev-server, build, and
contract-sync workflow after that initial bootstrap. In the native setup, the
recommended live-dev path is `vibesensor-server --reload --config
apps/server/config.dev.yaml` plus `npm --prefix apps/ui run dev`, then open
`http://127.0.0.1:5173`.

If you want the browser to open automatically on local desktop workflows, use
`npm --prefix apps/ui run dev:open` instead of `npm --prefix apps/ui run dev`.

If you prefer the source-mounted Docker workflow instead of the native path,
run `make dev`.

## Hooks and local safeguards

`make setup` enables the versioned repo hooks automatically. If you skipped that
bootstrap path or want to re-enable them manually, run:

```bash
git config core.hooksPath .githooks
```

Current hook behavior:

- Hooks are safe to enable.
- The privacy guard scans staged and pushed additions for high-confidence secret
  material and sensitive local-only files.
- Hooks prefer `.venv/bin/python` after `make setup`, then fall back to `python3`
  or `python` for bootstrap-only checkouts.
- If a hook blocks you unexpectedly, use the commands below directly and then investigate instead of guessing.

## Validation workflow

Use `make format` as the only supported Python formatter for backend and tooling
files. Do not run competing Python formatters in this repo.

Use `make test-changed` as a heuristic shortcut for the files changed on your
current branch when you want a fast first pass. It is not a replacement for the
broader tiers below before merge.

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
| Docker dev stack | `make dev` |
| Python formatting | `make format` |
| Fast backend tests | `make test` |
| UI lint | `make ui-lint` |
| Changed-file heuristic | `make test-changed` |
| Non-Docker CI subset | `make test-ci-lite` |
| Full local CI runner | `make test-all` |
| Coverage view | `make coverage` |

## CI jobs and local reproduction

The blocking jobs live in
[.github/workflows/ci.yml](.github/workflows/ci.yml). Use the command list in
[.github/copilot-instructions.md](.github/copilot-instructions.md) §
"Commands" plus [docs/testing.md](docs/testing.md) when you need the matching
local reproduction flow.

Backend checks are split by concern. `backend-lint` covers formatting and
linting, `repo-hygiene` covers repository policy checks,
`backend-static-guards` covers architecture/static guardrails,
`backend-preflight` covers config preflight, `docs-lint` covers documentation
drift and local markdown links, and `backend-contract-drift` covers generated
contract sync. Use those workflow job names when matching a CI failure to a
local reproduction command.

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

1. **Built-in defaults** (`vibesensor.app.config_defaults.DEFAULT_CONFIG`) — always present, never edited
2. **`config.yaml`** — local overrides (gitignored; mostly empty by default)
3. **Environment variables** — override individual keys at runtime

Preset files ship with the repo for common environments:

| File | Purpose |
|---|---|
| `config.dev.yaml` | Native-dev overrides (port 8000, no GPS, relative paths) |
| `config.docker.yaml` | Docker-compose overrides |
| `config.pi.yaml` | Raspberry Pi deployment overlay copied to `/etc/vibesensor/config.yaml` by install/image flows |

**Quick start for local dev:**

```bash
cp apps/server/config.dev.yaml apps/server/config.yaml
```

Then edit `config.yaml` as needed. The file is gitignored, so your local changes won't affect others.

Use [docs/configuration_reference.md](docs/configuration_reference.md) for the
full key-by-key runtime config reference.

## API contract sync

The contract-sync flow lives in
[apps/ui/README.md#contract-sync](apps/ui/README.md#contract-sync). Use that
section for what `make sync-contracts` regenerates (including
the locally generated derivative UI artifacts) and what to do when CI reports
contract drift.

For frontend runtime validation policy, treat generated HTTP/WS TypeScript types
as compile-time contracts only. At owned server-controlled runtime boundaries,
parse once, validate once, and only then hand typed data to features or
presenters. Use the Valibot patterns documented in
[apps/ui/README.md#http-runtime-boundary-validation](apps/ui/README.md#http-runtime-boundary-validation)
unless a hot-path custom validator is explicitly justified.

## Common failure cases

- Privacy hook failure: remove the secret material or replace it with a documented placeholder, then rerun the commit or push.
- Port confusion: production-style access is usually `http://127.0.0.1`, while native dev often uses `http://127.0.0.1:8000`.
- UI contract drift: follow [apps/ui/README.md#contract-sync](apps/ui/README.md#contract-sync) for the authoritative HTTP/WS/constants sync flow and rerun `make sync-contracts`.
- Slow or failing end-to-end runs: check Docker status and the operational runbook before debugging application logic.

### Developer setup troubleshooting

- `make doctor` fails on Python or Node: switch to the versions required by
  [docs/runtime_support_matrix.md](docs/runtime_support_matrix.md). For native
  dev and local CI reproduction, that means matching
  [.python-version](.python-version) and [.nvmrc](.nvmrc), then rerun
  `make doctor` before bootstrapping. A doctor `WARN` on Docker or PlatformIO
  only means those optional workflow paths are unavailable; the native Python +
  Vite path can still be usable.
- `make lint` fails on runtime policy drift: treat
  [docs/runtime_support_matrix.md](docs/runtime_support_matrix.md) as the
  runtime-policy coverage contract and update it in the same change as the
  referenced anchors named by the failure (`.python-version`, `.nvmrc`,
  `apps/server/pyproject.toml`, GitHub Actions setup/workflow files,
  Dockerfiles, or Pi install/image scripts). Then rerun `make lint`.
- `vibesensor-server`, `vibesensor-config-preflight`, or other `vibesensor-*`
  commands are missing after `pip install -e`: activate the same environment you
  installed into before running repo commands. If you use a local `.venv`, run
  `source .venv/bin/activate` first; otherwise, make sure the installing
  interpreter's script directory is on your `PATH` and rerun `make setup` or
  `.venv/bin/python -m pip install -e "./apps/server[dev]"`.
- Backend bootstrap looks half-installed or editable installs behave strangely:
  avoid mixing global and virtualenv installs. Recreate the environment you
  intend to use, then rerun either `make setup` or the native bootstrap flow in
  [README.md#native-python--vite-recommended-for-backend-or-ui-iteration](README.md#native-python--vite-recommended-for-backend-or-ui-iteration).
- `npm --prefix apps/ui ci` or `npm --prefix apps/ui run dev` fails right after a
  Node version switch: confirm `node --version` matches the runtime support
  matrix (native dev uses `.nvmrc`), delete `apps/ui/node_modules`, and rerun
  `npm --prefix apps/ui ci` instead of `npm install`.
- `docker compose` fails before the app starts: check `docker info` and
  `docker compose version` before debugging the repo itself. If the daemon is
  not reachable or your user lacks Docker permissions, fix that first and then
  retry the commands from [README.md#docker-dev-mode-source-mounted-hot-reload](README.md#docker-dev-mode-source-mounted-hot-reload).
- The Vite UI loads but `/api` or `/ws` requests fail: keep
  `vibesensor-server --reload --config apps/server/config.dev.yaml` running on
  `:8000`, then run `npm --prefix apps/ui run dev` and open
  `http://127.0.0.1:5173`. The backend listener on `http://127.0.0.1:8000` is
  the API server, not the Vite dev server.
