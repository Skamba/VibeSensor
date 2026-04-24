# Agent guidance

VibeSensor is a mixed Python backend, TypeScript/Vite dashboard, ESP32 firmware, and Raspberry Pi image repository.

Read [.github/copilot-instructions.md](.github/copilot-instructions.md) for the canonical architecture, command, and validation guidance. Use `.github/instructions/` for Copilot path-scoped rules, and use `docs/ai/repo-map.md` for navigation only.

Before changing code:
- Identify the touched area: backend, frontend, firmware, Pi image, tests, docs, or instructions.
- Follow the matching validation path from `.github/copilot-instructions.md`.
- Update docs or AI guidance when the touched behavior changes their facts.
- Keep changes scoped to the request plus direct root-cause fixes and clearly adjacent regressions found during validation.
