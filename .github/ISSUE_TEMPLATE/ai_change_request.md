---
name: AI change request
about: AI request format for repository-default implementation
title: "[AI] <short goal>"
labels: ["ai-request"]
assignees: []
---

## Goal
<!-- One paragraph -->

## Constraints
<!-- Non-negotiables, UX/performance/safety/scope limits. Backward compatibility is optional and never required. -->

## Affected Area
<!-- Pick from docs/ai/repo-map.md -->

## Files to Touch (expected)
- 

## Validations to Run
```bash
# example
make lint
make typecheck-backend
pytest -q apps/server/tests/app/test_config.py -k my_case
make test-all
# (optional faster CI-parity subset)
./.venv/bin/python tools/tests/run_ci_parallel.py --job backend-preflight --job backend-tests-1
```

## Acceptance Criteria
- [ ]
- [ ]
