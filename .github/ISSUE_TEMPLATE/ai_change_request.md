---
name: AI change request
about: Minimal request format for low-context AI implementation
title: "[AI] <short goal>"
labels: ["ai-request"]
assignees: []
---

## Goal
<!-- One paragraph -->

## Constraints
<!-- Non-negotiables, compatibility, scope limits -->

## Affected Area
<!-- Pick from docs/ai/map.md -->

## Files to Touch (expected, <=10)
- 

## Validations to Run (narrow)
```bash
# example
scripts/ai/task ai:check
scripts/ai/task ai:test -- pi/tests/test_config.py -k my_case -q
```

## Acceptance Criteria
- [ ]
- [ ]
