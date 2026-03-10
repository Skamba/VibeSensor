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
pytest -q apps/server/tests/config/test_config.py -k my_case
make test-all
# (optional faster CI-parity subset)
python3 tools/tests/run_ci_parallel.py --job preflight --job tests
```

## Acceptance Criteria
- [ ]
- [ ]
