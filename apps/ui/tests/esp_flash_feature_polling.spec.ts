import { expect, test } from "@playwright/test";

import { flushAsyncWork, jsonResponse } from "./async_test_helpers";
import {
  createEspFlashFeatureHarness,
  createEspFlashPort,
  installFeatureFetchMock,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";

let restoreDomGlobals = () => undefined;

test.beforeEach(() => {
  restoreDomGlobals = installMaintenanceFeatureGlobals();
});

test.afterEach(() => {
  restoreDomGlobals();
  restoreDomGlobals = () => undefined;
});

test.describe("createEspFlashFeature polling", () => {
  test("idle state renders readiness, empty log, and empty history context", async () => {
    const restoreFetch = installFeatureFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [createEspFlashPort()] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "idle",
          phase: "idle",
          selected_port: null,
          auto_detect: true,
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
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_ready",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.item.connection_ready",
      );
      expect(deps.espFlashStartBtn.disabled).toBe(false);
      expect(deps.espFlashCancelBtn.hidden).toBe(true);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.readiness.summary.ready_ports",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.readiness.one_port",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.auto_detect",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).not.toContain(
        "settings.esp_flash.journey_title",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).not.toContain(
        "settings.esp_flash.phase.validating",
      );
      expect(deps.espFlashJourneyPanel.innerHTML).toContain(
        "settings.esp_flash.phase.validating",
      );
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_idle_title",
      );
      expect(
        (deps.els.espFlashHistoryPanel as HTMLElement).innerHTML,
      ).toContain("settings.esp_flash.history_empty_title");
    } finally {
      restoreFetch();
    }
  });

  test("no detected ports keep the flash action blocked until hardware is present", async () => {
    const restoreFetch = installFeatureFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "idle",
          phase: "idle",
          selected_port: null,
          auto_detect: true,
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
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_blocked",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.item.connection_blocked",
      );
      expect(deps.espFlashStartBtn.disabled).toBe(true);
      expect(deps.espFlashCancelBtn.hidden).toBe(true);
    } finally {
      restoreFetch();
    }
  });

  test("running state highlights the active stage and marks completed stages done", async () => {
    const restoreFetch = installFeatureFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [createEspFlashPort()] });
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
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_running",
      );
      expect(deps.espFlashStartBtn.hidden).toBe(true);
      expect(deps.espFlashCancelBtn.hidden).toBe(false);
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_running_title",
      );
      const html = deps.espFlashJourneyPanel.innerHTML;
      expect(html).toMatch(
        /data-stage-phase="flashing" data-stage-state="active" aria-current="step"/,
      );
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.readiness.current_step",
      );
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(
        html.match(/<span class="maintenance-stage__marker">✓<\/span>/g),
      ).toHaveLength(3);
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
    const restoreFetch = installFeatureFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [createEspFlashPort()] });
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
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
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

      const html = deps.espFlashJourneyPanel.innerHTML;
      expect(html).toMatch(
        /data-stage-phase="flashing" data-stage-state="attention"/,
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.recovery.title",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.recovery.flashing.detail",
      );
      expect(deps.espFlashStartBtn.textContent).toBe(
        "settings.esp_flash.retry",
      );
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_failed_title",
      );
      expect(
        (deps.els.espFlashHistoryPanel as HTMLElement).innerHTML,
      ).toContain("serial port disconnected");
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "serial port disconnected",
      );
    } finally {
      restoreFetch();
    }
  });
});
