import { describe, expect, test } from "vitest";
import { effect } from "../src/app/ui_signals";
import { createApiLoader } from "../src/app/features/api_loader";

describe("createApiLoader", () => {
  test("runs lifecycle hooks and toggles loading on success", async () => {
    const events: string[] = [];
    const loader = createApiLoader({
      beforeLoad: () => {
        events.push("before");
      },
      load: async () => {
        events.push("load");
        return "ready";
      },
      apply: (value) => {
        events.push(`apply:${value}`);
      },
    });
    const loadingStates: boolean[] = [];
    const dispose = effect(() => {
      loadingStates.push(loader.loading.value);
    });

    expect(loadingStates).toEqual([false]);
    await expect(loader.load()).resolves.toBe("ready");
    expect(events).toEqual(["before", "load", "apply:ready"]);
    expect(loadingStates).toEqual([false, true, false]);

    dispose();
  });

  test("rethrows and calls onError when the load fails", async () => {
    const events: string[] = [];
    const loader = createApiLoader({
      load: async () => {
        throw new Error("offline");
      },
      apply: () => {
        events.push("apply");
      },
      onError: (error) => {
        events.push(error instanceof Error ? error.message : String(error));
      },
    });

    await expect(loader.load()).rejects.toThrow("offline");
    expect(events).toEqual(["offline"]);
    expect(loader.loading.value).toBe(false);
  });

  test("can swallow a handled load failure when the caller opts in", async () => {
    const events: string[] = [];
    const loader = createApiLoader({
      load: async () => {
        throw new Error("offline");
      },
      apply: () => {
        events.push("apply");
      },
      onError: (error) => {
        events.push(error instanceof Error ? error.message : String(error));
      },
      swallowError: true,
    });

    await expect(loader.load()).resolves.toBeNull();
    expect(events).toEqual(["offline"]);
    expect(loader.loading.value).toBe(false);
  });
});
