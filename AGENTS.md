# Agent guidance

VibeSensor includes a Python backend, TypeScript/Vite UI, ESP32 firmware, and Raspberry Pi image build. Read [.github/copilot-instructions.md](.github/copilot-instructions.md).

- Canonical repo guidance: `.github/copilot-instructions.md`.
- Path-scoped rules: `.github/instructions/`.
- Navigation fallback: `docs/ai/repo-map.md`; use `rg`, file names, imports, and tests first.
- If your agent already auto-loads the relevant instruction files, do not reopen them just to duplicate context.
- Before editing, identify the touched area, follow the matching validation path, update directly affected docs/guidance, and keep scope to the request plus root-cause fixes.
