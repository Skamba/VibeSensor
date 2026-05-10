import { describe, expect, test } from "vitest";

import { createWorkflowGenerationGuard } from "../src/app/features/workflow_generation_guard";

describe("createWorkflowGenerationGuard", () => {
  test("accepts only the latest active generation", () => {
    let active = true;
    const guard = createWorkflowGenerationGuard({ isActive: () => active });

    const first = guard.begin();
    const second = guard.begin();

    expect(guard.isCurrent(first)).toBe(false);
    expect(guard.isCurrent(second)).toBe(true);
    active = false;
    expect(guard.isCurrent(second)).toBe(false);
  });

  test("invalidates in-flight work while preserving latest checks", () => {
    const guard = createWorkflowGenerationGuard();
    const generation = guard.begin();

    expect(guard.isLatest(generation)).toBe(true);

    guard.invalidate();

    expect(guard.isCurrent(generation)).toBe(false);
    expect(guard.isLatest(generation)).toBe(false);
  });
});
