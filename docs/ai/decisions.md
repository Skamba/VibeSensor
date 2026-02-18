# AI-Facing Decisions

## D1: Offline-first hotspot boot
- Decision: hotspot provisioning must not depend on internet connectivity.
- Rationale: first boot often has no uplink; runtime apt/network fetches are brittle.
- Implication: required packages are baked into image build stage.

## D2: Canonical vibration severity metric
- Decision: use `vibration_strength_db` as single severity metric.
- Rationale: stable, normalized representation for UI/reports.
- Implication: avoid introducing threshold checks against raw g-values.

## D3: Default CI validation mode
- Decision: default suite is simulator E2E smoke + WS smoke.
- Rationale: lower runtime, catches integration regressions early.
- Implication: extended unit-heavy pytest runs are opt-in for deep investigations.

## D4: Deterministic image outputs
- Decision: custom pi-gen stage must export uniquely suffixed artifact and self-validate rootfs contents.
- Rationale: avoid flashing ambiguous stock images.
- Implication: build wrapper performs mount-based post-build assertions.

## D5: Low-noise automation
- Decision: AI tooling writes verbose logs to `artifacts/ai/logs/` and prints short summaries.
- Rationale: reduce token usage and avoid noisy prompt context.
