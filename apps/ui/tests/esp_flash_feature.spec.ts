import { expect, test } from "@playwright/test";

import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import { createUpdateFeature } from "../src/app/features/update_feature";
import type { UiDomElements } from "../src/app/ui_dom_registry";
import {
  createDeferred,
  flushAsyncWork,
  installTimerHarness,
  installWindowGlobal,
  jsonResponse,
} from "./async_test_helpers";
import type { TimerHarness } from "./async_test_helpers";

type ClickListener = (() => void) | null;

function pendingPollDelays(timers: TimerHarness): number[] {
  return timers.pendingDelays().filter((delay) => delay !== 10_000);
}

function installFetchMock(
  handler: (url: URL, method: string) => Promise<Response> | Response,
): () => void {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (input: string | URL | RequestInfo, init?: RequestInit) => {
    const requestUrl =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const requestMethod = init?.method ?? (input instanceof Request ? input.method : "GET");
    return handler(new URL(requestUrl, "http://vibesensor.test"), requestMethod);
  }) as typeof fetch;

  return () => {
    globalThis.fetch = originalFetch;
  };
}

function createButton(): HTMLButtonElement {
  let onClick: ClickListener = null;

  return {
    disabled: false,
    hidden: false,
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      if (type !== "click") return;
      onClick = () => {
        const event = new Event("click");
        if (typeof listener === "function") {
          listener(event);
          return;
        }
        listener.handleEvent(event);
      };
    },
    click() {
      onClick?.();
    },
    querySelector() {
      return null;
    },
  } as unknown as HTMLButtonElement;
}

function createSelect(value: string): HTMLSelectElement {
  return {
    value,
    disabled: false,
    innerHTML: "",
  } as unknown as HTMLSelectElement;
}

function createInput(value = "", type = "text"): HTMLInputElement {
  return {
    value,
    type,
    disabled: false,
    focus() {},
  } as unknown as HTMLInputElement;
}

function createPanel(): HTMLElement {
  let textContent = "";
  let innerHTML = "";
  return {
    get textContent() {
      return textContent;
    },
    set textContent(value: string | null) {
      textContent = value ?? "";
      innerHTML = textContent;
    },
    get innerHTML() {
      return innerHTML;
    },
    set innerHTML(value: string) {
      innerHTML = value;
      textContent = value;
    },
    className: "",
    scrollTop: 0,
    scrollHeight: 0,
  } as unknown as HTMLElement;
}

function createDeps() {
  const espFlashPortSelect = createSelect("__auto__");
  const espFlashRefreshPortsBtn = createButton();
  const espFlashStartBtn = createButton();
  const espFlashCancelBtn = createButton();
  const espFlashStatusBanner = createPanel();
  const espFlashReadinessPanel = createPanel();
  const espFlashLogPanel = createPanel();
  const espFlashHistoryPanel = createPanel();

  const els = {
    menuButtons: [],
    views: [],
    settingsTabs: [],
    settingsTabPanels: [],
    espFlashPortSelect,
    espFlashRefreshPortsBtn,
    espFlashStartBtn,
    espFlashCancelBtn,
    espFlashStatusBanner,
    espFlashReadinessPanel,
    espFlashLogPanel,
    espFlashHistoryPanel,
  } as unknown as UiDomElements;

  return {
    els,
    espFlashStartBtn,
    espFlashCancelBtn,
    espFlashReadinessPanel,
    t: (key: string) => key,
    escapeHtml: (value: unknown) => String(value ?? ""),
    showError: () => {},
  };
}

async function expectDelays(readDelays: () => number[], expected: number[]): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = readDelays();
    if (actual.length === expected.length && actual.every((delay, index) => delay === expected[index])) {
      expect(actual).toEqual(expected);
      return;
    }
    await flushAsyncWork(1);
  }
  expect(readDelays()).toEqual(expected);
}

async function expectPollDelays(timers: TimerHarness, expected: number[]): Promise<void> {
  await expectDelays(() => pendingPollDelays(timers), expected);
}

async function expectTimerDelays(timers: TimerHarness, expected: number[]): Promise<void> {
  await expectDelays(() => timers.pendingDelays(), expected);
}

function createIdleUpdateStatus() {
  return {
    state: "idle",
    phase: "idle",
    ssid: null,
    started_at: null,
    phase_started_at: null,
    phase_elapsed_s: null,
    finished_at: null,
    last_success_at: null,
    issues: [],
    log_tail: [],
    runtime: null,
  };
}

function createHealthyUpdateStatus() {
  return {
    status: "ok",
    processing_state: "idle",
    processing_failures: 0,
    degradation_reasons: [],
    data_loss: {
      affected_clients: 0,
      tracked_clients: 0,
      frames_dropped: 0,
      queue_overflow_drops: 0,
      server_queue_drops: 0,
      parse_errors: 0,
    },
    persistence: {
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      write_error: null,
      analysis_active_run_id: null,
      analysis_started_at: null,
      analysis_elapsed_s: null,
    },
  };
}

function createUpdateDeps() {
  const updateSsidInput = createInput("MyWiFi");
  const updatePasswordInput = createInput("secret", "password");
  const updateTogglePasswordBtn = createButton();
  const updateStartBtn = createButton();
  const updateCancelBtn = createButton();
  const updateStatusPanel = createPanel();

  const els = {
    menuButtons: [],
    views: [],
    settingsTabs: [],
    settingsTabPanels: [],
    updateSsidInput,
    updatePasswordInput,
    updateTogglePasswordBtn,
    updateStartBtn,
    updateCancelBtn,
    updateStatusPanel,
  } as unknown as UiDomElements;

  return {
    els,
    updatePasswordInput,
    updateStartBtn,
    updateCancelBtn,
    t: (key: string) => key,
    escapeHtml: (value: unknown) => String(value ?? ""),
    showError: () => {},
  };
}

test.beforeEach(() => {
  installWindowGlobal();
});

test.describe("createEspFlashFeature polling", () => {
  test("idle state renders readiness, empty log, and empty history context", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", phase: "idle", selected_port: null, auto_detect: true, last_success_at: null, error: null, log_count: 0 });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.readiness.summary.ready_ports");
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.readiness.one_port");
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.auto_detect");
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.journey_title");
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.phase.validating");
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain("settings.esp_flash.logs_idle_title");
      expect((deps.els.espFlashHistoryPanel as HTMLElement).innerHTML).toContain("settings.esp_flash.history_empty_title");
    } finally {
      restoreFetch();
    }
  });

  test("running state highlights the active stage and marks completed stages done", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "running",
          phase: "flashing",
          selected_port: "/dev/ttyUSB0",
          auto_detect: false,
          last_success_at: null,
          error: null,
          log_count: 0,
        });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      const html = deps.espFlashReadinessPanel.innerHTML;
      expect(html).toMatch(/data-stage-phase="flashing" data-stage-state="active" aria-current="step"/);
      expect(html).toContain("settings.esp_flash.readiness.current_step");
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(html.match(/<span class="maintenance-stage__marker">✓<\/span>/g)).toHaveLength(3);
    } finally {
      restoreFetch();
    }
  });

  test("failed refresh keeps the last running stage marked as stopped here", async () => {
    let status = {
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      auto_detect: false,
      last_success_at: null,
      error: null,
      log_count: 0,
    };
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse(status);
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      status = {
        ...status,
        state: "failed",
        phase: "failed",
        error: "serial port disconnected",
      };
      feature.stopPolling();
      feature.startPolling();
      await flushAsyncWork();

      const html = deps.espFlashReadinessPanel.innerHTML;
      expect(html).toMatch(/data-stage-phase="flashing" data-stage-state="attention"/);
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(html).toContain("serial port disconnected");
    } finally {
      restoreFetch();
    }
  });

  test("start replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/start" && method === "POST") {
        return jsonResponse({ status: "started", job_id: 1 });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashStartBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("cancel replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashCancelBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/status") return deferredStatus.promise;
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();
      expect(pendingPollDelays(timers)).toEqual([]);

      feature.stopPolling();
      deferredStatus.resolve(jsonResponse({ state: "idle", log_count: 0, error: null }));
      await flushAsyncWork();

      expect(pendingPollDelays(timers)).toEqual([]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});

test.describe("createUpdateFeature polling", () => {
  test("idle update status renders readiness instead of clearing the panel", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          runtime: {
            version: "1.2.3",
            commit: "abcdef1234567890",
            static_assets_hash: "feedfacecafebeef",
            assets_verified: true,
          },
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.current_status_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.current_status_summary.ready");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).not.toContain("settings.update.journey_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).not.toContain("settings.update.issues_empty_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.log_empty_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("1.2.3");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.health_card_title");
    } finally {
      restoreFetch();
    }
  });

  test("start replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        return jsonResponse({ status: "started" });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      deps.updateStartBtn.click();
      await expectTimerDelays(timers, [10_000]);
      expect(deps.updatePasswordInput.value).toBe("");
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("cancel replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/update/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      deps.updateCancelBtn.click();
      await expectTimerDelays(timers, [10_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight update poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") return deferredStatus.promise;
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      feature.stopPolling();
      deferredStatus.resolve(jsonResponse(createIdleUpdateStatus()));
      await expectTimerDelays(timers, []);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});
