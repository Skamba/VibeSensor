# Documentation Index

Every documentation file in the repository, its scope, intended audience, and authority level.

**Authority levels:**
- **Source of truth** — canonical reference for its topic; other files should defer to it.
- **Pointer** — routes to the source of truth; contains no unique content.
- **Supplementary** — adds context but defers to the source of truth on conflicts.

## AI Guidance

| File | Scope | Audience | Authority |
|------|-------|----------|-----------|
| `.github/copilot-instructions.md` | High-level orientation, behavioral rules, common commands | AI | Source of truth for AI behavioral rules |
| `docs/ai/repo-map.md` | Detailed file layout, entry points, module ownership | AI + human | Source of truth for repo structure and file ownership |
| `.github/instructions/general.instructions.md` | Shared workflow, validation, execution guardrails | AI | Source of truth for agent execution rules |
| `.github/instructions/backend.instructions.md` | Backend-specific behavioral rules and deltas | AI | Source of truth for backend coding rules |
| `.github/instructions/frontend.instructions.md` | Frontend-specific rules | AI | Source of truth for frontend coding rules |
| `.github/instructions/tests.instructions.md` | Test-specific conventions and commands | AI | Source of truth for test conventions |
| `AGENTS.md` | Agent guidance router | AI | Pointer → `.github/copilot-instructions.md` |
| `docs/ai/chunk*.md` | Task planning context for multi-step AI work | AI | Supplementary |

## Architecture & Design

| File | Scope | Audience | Authority |
|------|-------|----------|-----------|
| `docs/domain-model.md` | Domain object graph, modeling rules, adapter inventory | Both | Source of truth for domain model |
| `docs/analysis_pipeline.md` | Post-stop diagnostics pipeline: steps, modules, data flow | Both | Source of truth for analysis pipeline |
| `docs/report_pipeline.md` | Report generation flow from analysis to PDF | Both | Source of truth for report pipeline |
| `docs/design_language.md` | Visual design decisions (report layout, UI) | Both | Source of truth for design choices |
| `docs/metrics.md` | Vibration metrics definitions and units | Both | Source of truth for metric definitions |
| `docs/metrics_to_report_mapping.md` | How metrics map to report sections | Both | Source of truth for metric→report mapping |
| `docs/protocol.md` | UDP/WebSocket protocol between ESP32 and server | Both | Source of truth for wire protocol |

## Infrastructure & Operations

| File | Scope | Audience | Authority |
|------|-------|----------|-----------|
| `docs/operational-runbooks.md` | Troubleshooting and operational procedures | Human | Source of truth for ops procedures |
| `docs/history_db_schema.md` | SQLite history database schema | Both | Source of truth for DB schema |
| `docs/run_schema_v2.md` | Run data persistence schema v2 | Both | Source of truth for run schema |
| `docs/intake_buffering.md` | Sample intake and buffering strategy | Both | Source of truth for intake design |
| `docs/time_alignment.md` | Multi-sensor time alignment approach | Both | Source of truth for time alignment |
| `docs/multithreading_performance.md` | Threading model and performance considerations | Both | Source of truth for threading design |
| `docs/ssh-root-cause.md` | SSH connectivity root-cause analysis | Human | Supplementary |

## Testing

| File | Scope | Audience | Authority |
|------|-------|----------|-----------|
| `docs/testing.md` | Test layout, commands, CI parity, conventions | Both | Source of truth for testing |

## READMEs (setup and orientation)

| File | Scope | Audience | Authority |
|------|-------|----------|-----------|
| `README.md` | Project overview and quickstart | Human | Source of truth for project intro |
| `CONTRIBUTING.md` | Development workflow and setup paths | Human | Source of truth for contributor workflow |
| `CHANGELOG.md` | Release history | Human | Source of truth for changelog |
| `apps/server/README.md` | Backend setup, deployment, CLI | Human | Source of truth for server setup |
| `apps/ui/README.md` | Frontend setup and build | Human | Source of truth for UI setup |
| `firmware/esp/README.md` | ESP32 firmware setup and flashing | Human | Source of truth for firmware |
| `firmware/esp/HARDENING.md` | Firmware security hardening notes | Human | Supplementary |
| `hardware/README.md` | Hardware components and wiring | Human | Source of truth for hardware |
| `infra/ci/README.md` | CI pipeline overview | Human | Source of truth for CI |
| `infra/pi-image/pi-gen/README.md` | Raspberry Pi image build | Human | Source of truth for Pi image |

## Data & reference

| File | Scope | Audience | Authority |
|------|-------|----------|-----------|
| `apps/server/data/CAR_VARIANT_SOURCES.md` | Car variant data sourcing notes | Human | Supplementary |

## Topic → source-of-truth quick reference

| Topic | Authoritative file |
|-------|-------------------|
| Repo structure / file ownership | `docs/ai/repo-map.md` |
| Domain model | `docs/domain-model.md` |
| Analysis pipeline | `docs/analysis_pipeline.md` |
| Report pipeline | `docs/report_pipeline.md` |
| Metrics & units | `docs/metrics.md` |
| Wire protocol | `docs/protocol.md` |
| DB schema | `docs/history_db_schema.md` |
| Testing conventions | `docs/testing.md` |
| AI behavioral rules | `.github/copilot-instructions.md` |
| Backend coding rules | `.github/instructions/backend.instructions.md` |
| Frontend coding rules | `.github/instructions/frontend.instructions.md` |
| Contributor workflow | `CONTRIBUTING.md` |
| Server setup | `apps/server/README.md` |
| Design language | `docs/design_language.md` |
