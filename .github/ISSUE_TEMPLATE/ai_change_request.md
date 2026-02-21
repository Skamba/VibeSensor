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
<!-- Pick from docs/ai/map.md -->

## Files to Touch (expected)
- 

## Validations to Run
```bash
# example
scripts/ai/task ai:check
scripts/ai/task ai:test -- pi/tests/test_config.py -k my_case -q
make test-all
```

## Acceptance Criteria
- [ ]
- [ ]
