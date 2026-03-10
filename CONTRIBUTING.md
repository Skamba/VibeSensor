# Contributing

Use this file as the human-facing source of truth for day-to-day development workflow. Detailed architecture and area-specific rules still live in the focused docs it links to.

## Choose your setup path

- UI-only or quick product checks: use Docker with the simulator.
- Backend logic, tests, or type work: use native Python plus the simulator.
- Firmware work: use the ESP README and PlatformIO toolchain.
- Pi image or deployment-path work: use the server and pi-image READMEs before touching infra.

Primary references:

- Repo structure: [docs/ai/repo-map.md](docs/ai/repo-map.md)
- Server setup and deployment: [apps/server/README.md](apps/server/README.md)
- Testing layout and commands: [docs/testing.md](docs/testing.md)
- Operational runbooks: [docs/operational-runbooks.md](docs/operational-runbooks.md)

## Local setup

### Docker path

```bash
docker compose up --build
python3 -m pip install -e "./apps/server[dev]"
vibesensor-sim --count 5 --server-host 127.0.0.1
```

### Native backend path

```bash
python3 -m pip install -e "./apps/server[dev]"
cd apps/ui && npm ci
vibesensor-server --config apps/server/config.dev.yaml
```

In another terminal:

```bash
cd apps/ui && npm run dev
vibesensor-sim --count 5 --server-host 127.0.0.1 --no-auto-server
```

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

Two tiers: use `make test` during iteration, `make test-all` before pushing.

| Goal | Command |
|---|---|
| Backend lint | `make lint` |
| Backend typing | `make typecheck-backend` |
| Frontend typing | `make ui-typecheck` |
| Fast backend tests | `make test` |
| Focused backend tests | `pytest -q apps/server/tests/<area>/` |
| Coverage view | `make coverage` |
| Full CI-parity suite | `make test-all` |
| Docs lint | `make docs-lint` |
| Sync frontend contracts | `make sync-contracts` |

Useful focused examples:

```bash
pytest -q apps/server/tests/update/
pytest -q apps/server/tests/regression/runtime/
```

## CI jobs and local reproduction

The main CI pipeline is split into these job groups:

- `backend-quality`
- `backend-typecheck`
- `frontend-typecheck`
- `ui-smoke`
- `release-smoke`
- `backend-tests`
- `e2e`

`backend-quality` now includes docs lint, so documentation drift and broken local markdown links fail PR validation early.

Reproduce them locally with:

```bash
python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests
python3 tools/tests/run_ci_parallel.py --job frontend-typecheck --job ui-smoke
python3 tools/tests/run_ci_parallel.py --job release-smoke
python3 tools/tests/run_e2e_parallel.py --shards 3 --fast-e2e
```

Use `release-smoke` when you need confidence in the packaged wheel and bundled
static assets. Use `e2e` when you need confidence in the Docker/runtime path.
They cover different delivery contracts and neither replaces the other.

When a single shard fails in CI, run the corresponding focused suite locally first instead of rerunning everything.

## Pull requests and merge expectations

- Work on a branch, not directly on `main`.
- Keep docs in sync with meaningful code changes.
- Before asking for merge, run the relevant local validation plus the smallest broader suite that matches your change.
- After opening or updating a PR, monitor checks until they are green:

```bash
python3 tools/ci/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor
```

- Do not merge until required checks are green.

## Documentation expectations

When you change ownership boundaries, commands, or workflows, update the matching docs in the same change set. Common touchpoints are:

- [README.md](README.md)
- [apps/server/README.md](apps/server/README.md)
- [docs/testing.md](docs/testing.md)
- [docs/ai/repo-map.md](docs/ai/repo-map.md)
- [docs/operational-runbooks.md](docs/operational-runbooks.md)

## Configuration

The backend uses a layered config system. Values are merged in this order (later wins):

1. **Built-in defaults** (`vibesensor.config.DEFAULT_CONFIG`) — always present, never edited
2. **`config.yaml`** — local overrides (gitignored; mostly empty by default)
3. **Environment variables** — override individual keys at runtime

Preset files ship with the repo for common environments:

| File | Purpose |
|---|---|
| `config.example.yaml` | Canonical reference listing every key with its default |
| `config.dev.yaml` | Native-dev overrides (port 8000, no GPS, relative paths) |
| `config.docker.yaml` | Docker-compose overrides |

**Quick start for local dev:**

```bash
cp apps/server/config.dev.yaml apps/server/config.yaml
```

Then edit `config.yaml` as needed. The file is gitignored, so your local changes won't affect others.

## API contract sync

Frontend TypeScript types are generated from the backend's OpenAPI schema. When you change backend API models (Pydantic models in `api_models.py`, route signatures), the frontend contracts must be regenerated.

The sync runs automatically via `pretypecheck` and `prebuild` npm scripts, so `npm run build` and `npm run typecheck` always use fresh types. To run it manually:

```bash
cd apps/ui && npm run sync:contracts
```

If CI fails with a contract-check error, run the command above and commit the result.

## Common failure cases

- Hook warning about missing `privacy_guard.py`: this is non-blocking; run the documented validation commands directly.
- Port confusion: production-style access is usually `http://127.0.0.1`, while native dev often uses `http://127.0.0.1:8000`.
- UI contract drift: run `cd apps/ui && npm run sync:contracts` to regenerate both shared TS constants and generated HTTP API types.
- Slow or failing end-to-end runs: check Docker status and the operational runbook before debugging application logic.