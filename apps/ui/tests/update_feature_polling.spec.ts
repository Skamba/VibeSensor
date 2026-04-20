import { expect, test } from "@playwright/test";

import {
  createDeferred,
  flushAsyncWork,
  installTimerHarness,
} from "./async_test_helpers";
import {
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUpdateFeatureHarness,
  createUsbInternetStatus,
  expectTimerDelays,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";
import { buildUpdateHandlers } from "./msw/handlers/maintenance";
import { createUiMswTestServer } from "./msw/node";

let restoreDomGlobals = () => undefined;
const mswServer = createUiMswTestServer(test);

test.beforeEach(() => {
  restoreDomGlobals = installMaintenanceFeatureGlobals();
});

test.afterEach(() => {
  restoreDomGlobals();
  restoreDomGlobals = () => undefined;
});

test.describe("createUpdateFeature polling", () => {
  test("idle update status renders readiness and the expected journey", async () => {
    mswServer.use(...buildUpdateHandlers());

    const { deps, feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    deps.updateSsidInput.value = "MyWiFi";
    deps.updateSsidInput.dispatchEvent(new Event("input"));
    feature.startPolling();
    await flushAsyncWork();

    expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain(
      "settings.update.journey_title",
    );
    expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain(
      "settings.update.phase.validating",
    );
    expect(
      (deps.els.updateStatusPanel as HTMLElement).innerHTML,
    ).not.toContain("settings.update.issues_empty_title");
    expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain(
      "settings.update.log_empty_title",
    );
    expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
      "settings.update.current_status_title",
    );
    expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
      "settings.update.current_status_summary.ready",
    );
    expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
      "1.2.3",
    );
    expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
      "settings.update.health_card_title",
    );
    expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain(
      "settings.internet.card_title",
    );
    expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain(
      "settings.internet.summary.not_detected",
    );
    expect(deps.updateTransportOptions.hidden).toBe(false);
    expect(deps.updateTransportChoiceWifi.getAttribute("data-selected")).toBe(
      "true",
    );
    expect(
      deps.updateTransportChoiceWifi.getAttribute("data-choice-state"),
    ).toBe("active");
    expect(
      deps.updateTransportChoiceWifi.getAttribute("data-choice-badge"),
    ).toBe("settings.update.transport.selected_badge");
    expect(deps.updateTransportChoiceUsb.getAttribute("data-disabled")).toBe(
      "true",
    );
    expect(deps.updateTransportUsbRadio.disabled).toBe(true);
    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.readiness.summary_ready",
    );
    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.readiness.item.connection_wifi_ready",
    );
    expect(deps.updateDetailsCaption.textContent).toBe(
      "settings.update.details_caption_wifi",
    );
    expect(deps.updateStartBtn.disabled).toBe(false);
    expect(deps.updateUsbTransportSummary.textContent).toBe(
      "settings.update.transport.usb_summary_unavailable",
    );
    feature.dispose();
  });

  test("degraded health blocks update start until maintenance issues are resolved", async () => {
    const healthy = createHealthyUpdateStatus();
    mswServer.use(
      ...buildUpdateHandlers({
        health: {
          ...healthy,
          status: "degraded",
          degradation_reasons: ["persistence_write_error"],
          persistence: {
            ...healthy.persistence,
            write_error: "database locked",
          },
        },
      }),
    );

    const { deps, feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    feature.startPolling();
    await flushAsyncWork();

    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.readiness.item.health_blocked",
    );
    expect(deps.updateStartBtn.disabled).toBe(true);
    feature.dispose();
  });

  test("running update state highlights the active journey stage", async () => {
    mswServer.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          state: "running",
          phase: "installing",
          transport: "wifi",
          ssid: "MyWiFi",
        }),
      }),
    );

    const { deps, feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    feature.startPolling();
    await flushAsyncWork();

    const html = (deps.els.updateStatusPanel as HTMLElement).innerHTML;
    expect(html).toContain("settings.update.log_running_title");
    expect(html).toMatch(
      /data-stage-phase="installing" data-stage-state="active" aria-current="step"/,
    );
    expect(html.match(/data-stage-state="done"/g)).toHaveLength(5);
    expect(
      html.match(/<span class="maintenance-stage__marker">✓<\/span>/g),
    ).toHaveLength(5);
    feature.dispose();
  });

  test("persisted Wi-Fi ssid rehydrates the update input after startup", async () => {
    mswServer.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          ssid: "Workshop Wi-Fi",
          updated_at: 123,
          last_success_at: 123,
        }),
      }),
    );

    const { deps, feature } = createUpdateFeatureHarness();
    deps.updateSsidInput.value = "";

    feature.bindUpdateHandlers();
    feature.startPolling();
    await flushAsyncWork();

    expect(deps.updateSsidInput.value).toBe("Workshop Wi-Fi");
    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.readiness.summary_ready",
    );
    expect(deps.updateStartBtn.disabled).toBe(false);
    feature.dispose();
  });

  test("persisted Wi-Fi ssid does not overwrite a user edit already in progress", async () => {
    mswServer.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          ssid: "Workshop Wi-Fi",
          updated_at: 123,
          last_success_at: 123,
        }),
      }),
    );

    const { deps, feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    deps.updateSsidInput.value = "Driver-entered Wi-Fi";
    deps.updateSsidInput.dispatchEvent(new Event("input"));
    feature.startPolling();
    await flushAsyncWork();

    expect(deps.updateSsidInput.value).toBe("Driver-entered Wi-Fi");
    feature.dispose();
  });

  test("failed update state surfaces the failed stage and issue details", async () => {
    mswServer.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          state: "failed",
          phase: "restoring_hotspot",
          transport: "wifi",
          issues: [
            {
              phase: "restoring_hotspot",
              message: "Hotspot restart timed out",
              detail: "NetworkManager is still reconnecting to the uplink.",
            },
          ],
        }),
      }),
    );

    const { deps, feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    deps.updateSsidInput.value = "MyWiFi";
    deps.updateSsidInput.dispatchEvent(new Event("input"));
    feature.startPolling();
    await flushAsyncWork();

    const html = (deps.els.updateStatusPanel as HTMLElement).innerHTML;
    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.recovery.title",
    );
    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.recovery.wifi.title",
    );
    expect(deps.updateReadinessSummary.innerHTML).toContain(
      "settings.update.recovery.wifi.detail",
    );
    expect(deps.updateStartBtn.textContent).toBe("settings.update.retry");
    expect(html).toContain("settings.update.issues");
    expect(html).toContain("settings.update.attempt_title");
    expect(html).toContain("settings.update.log_failed_title");
    expect(html).toContain("Hotspot restart timed out");
    expect(html).toContain(
      "NetworkManager is still reconnecting to the uplink.",
    );
    expect(html).toMatch(
      /data-stage-phase="restoring_hotspot" data-stage-state="attention"/,
    );
    feature.dispose();
  });

  test("cancel replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    mswServer.use(...buildUpdateHandlers());

    const { deps, feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    feature.startPolling();
    await expectTimerDelays(timers, [10_000]);

    deps.updateCancelBtn.click();
    await expectTimerDelays(timers, [10_000]);
    feature.dispose();
    timers.restore();
  });

  test("stopPolling prevents an in-flight update poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<ReturnType<typeof createIdleUpdateStatus>>();
    mswServer.use(
      ...buildUpdateHandlers({
        status: async () => await deferredStatus.promise,
      }),
    );

    const { feature } = createUpdateFeatureHarness();

    feature.bindUpdateHandlers();
    feature.startPolling();
    await expectTimerDelays(timers, [10_000]);

    feature.stopPolling();
    deferredStatus.resolve(createIdleUpdateStatus());
    await expectTimerDelays(timers, []);
    feature.dispose();
    timers.restore();
  });
});
