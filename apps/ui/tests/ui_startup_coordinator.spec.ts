import { beforeEach, describe, expect, test } from "vitest";
import { UiStartupCoordinator } from "../src/app/runtime/ui_startup_coordinator";
import { flushAsyncWork, installWindowGlobal } from "./async_test_helpers";

type Deferred<T> = {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createCoordinatorHarness() {
  const calls: string[] = [];
  const warnings: Array<{ message: string; error: unknown }> = [];
  const hydrate = createDeferred<void>();
  const refreshLocationOptions = createDeferred<void>();
  const refreshLoggingStatus = createDeferred<void>();
  const primeDashboardState = createDeferred<void>();

  const coordinator = new UiStartupCoordinator({
    shell: {
      start(defaultViewId: string): void {
        calls.push(`shell.start:${defaultViewId}`);
      },
      hydratePersistedPreferences(): Promise<void> {
        calls.push("shell.hydratePersistedPreferences");
        return hydrate.promise;
      },
    },
    features: {
      realtime: {
        refreshLocationOptions(): Promise<void> {
          calls.push("realtime.refreshLocationOptions");
          return refreshLocationOptions.promise;
        },
        refreshLoggingStatus(): Promise<void> {
          calls.push("realtime.refreshLoggingStatus");
          return refreshLoggingStatus.promise;
        },
      },
      secondary: {
        primeDashboardState(): Promise<void> {
          calls.push("secondary.primeDashboardState");
          return primeDashboardState.promise;
        },
      },
    },
    transport: {
      startTransportMode(): void {
        calls.push("transport.startTransportMode");
      },
    },
    defaultViewId: "dashboardView",
    warn(message: string, error: unknown): void {
      warnings.push({ message, error });
    },
  });

  return {
    calls,
    warnings,
    hydrate,
    refreshLocationOptions,
    refreshLoggingStatus,
    primeDashboardState,
    coordinator,
  };
}

function installLocation(search: string): () => void {
  const target = window as Window & typeof globalThis & { location?: Location };
  const previousLocation = target.location;
  target.location = {
    search,
    protocol: "http:",
    host: "localhost",
  } as Location;
  return () => {
    if (previousLocation === undefined) {
      delete target.location;
      return;
    }
    target.location = previousLocation;
  };
}

describe("UiStartupCoordinator", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("runs startup and background activity in the expected order", () => {
    const restoreLocation = installLocation("");
    const harness = createCoordinatorHarness();

    try {
      harness.coordinator.start();

      expect(harness.calls).toEqual([
        "shell.start:dashboardView",
        "shell.hydratePersistedPreferences",
        "realtime.refreshLocationOptions",
        "realtime.refreshLoggingStatus",
        "secondary.primeDashboardState",
        "transport.startTransportMode",
      ]);
    } finally {
      restoreLocation();
    }
  });

  test("async startup failures warn without blocking later startup work", async () => {
    const restoreLocation = installLocation("");
    const harness = createCoordinatorHarness();
    const hydrateError = new Error("hydrate failed");

    try {
      harness.coordinator.start();
      harness.hydrate.reject(hydrateError);
      harness.refreshLocationOptions.resolve();
      harness.refreshLoggingStatus.resolve();
      harness.primeDashboardState.resolve();

      await flushAsyncWork();

      expect(harness.calls).toContain("transport.startTransportMode");
      expect(harness.warnings).toEqual([
        {
          message: "UI startup task failed: hydrate persisted preferences",
          error: hydrateError,
        },
      ]);
    } finally {
      restoreLocation();
    }
  });
});
