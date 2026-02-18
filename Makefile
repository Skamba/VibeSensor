.PHONY: ai-check ai-test ai-smoke ai-pack ai\:check ai\:test ai\:smoke ai\:pack

ai-check:
	@scripts/ai/task ai:check

ai-test:
	@scripts/ai/task ai:test

ai-smoke:
	@scripts/ai/task ai:smoke

ai-pack:
	@scripts/ai/task ai:pack

ai\:check: ai-check
ai\:test: ai-test
ai\:smoke: ai-smoke
ai\:pack: ai-pack
