import { expect, test } from "@playwright/test";

import {
  flushAsyncWork,
  installTimerHarness,
  jsonResponse,
} from "./async_test_helpers";
import {
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUpdateFeatureHarness,
  createUsbInternetStatus,
  expectTimerDelays,
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

test.describe("createUpdateFeature transport", () => {
  test("start replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    let startBody = "";
    const restoreFetch = installFeatureFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        startBody = body;
        return jsonResponse({
          status: "started",
          transport: "wifi",
          ssid: "MyWiFi",
        });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const { deps, feature } = createUpdateFeatureHarness();

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(new Event("input"));
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input"));

      deps.updateStartBtn.click();
      await expectTimerDelays(timers, [10_000]);
      expect(deps.updatePasswordInput.value).toBe("");
      expect(JSON.parse(startBody)).toEqual({
        transport: "wifi",
        ssid: "MyWiFi",
        password: "secret",
      });
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("usable USB internet shows the USB option and starts with the USB transport payload", async () => {
    let startBody = "";
    const restoreFetch = installFeatureFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        startBody = body;
        return jsonResponse({
          status: "started",
          transport: "usb_internet",
          ssid: null,
        });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(
          createUsbInternetStatus({
            detected: true,
            usable: true,
            interface_name: "usb0",
            connection_name: "iPhone USB",
            driver: "ipheth",
            ipv4_addresses: ["172.20.10.2/28"],
            gateway: "172.20.10.1",
            has_default_route: true,
            diagnostic: "USB internet is ready on 'usb0'.",
          }),
        );
      }
      return jsonResponse({});
    });

    try {
      const { deps, feature } = createUpdateFeatureHarness();
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;

      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(new Event("input"));
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      deps.updateTransportUsbRadio.dispatchEvent(new Event("change"));

      expect(deps.updateTransportOptions.hidden).toBe(false);
      expect(deps.updateWifiFields.hidden).toBe(true);
      expect(deps.updateStartBtn.disabled).toBe(false);
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.connection_usb_ready",
      );
      expect(deps.updateDetailsCaption.textContent).toBe(
        "settings.update.details_caption_usb",
      );
      expect(deps.updateTransportNote.textContent).toBe(
        "settings.update.preflight_note_usb",
      );
      expect(deps.updateUsbTransportSummary.textContent).toBe(
        "settings.update.transport.usb_summary_interface",
      );
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-selected"),
      ).toBeNull();
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-state"),
      ).toBeNull();
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-badge"),
      ).toBeNull();
      expect(deps.updateTransportChoiceUsb.getAttribute("data-selected")).toBe(
        "true",
      );
      expect(
        deps.updateTransportChoiceUsb.getAttribute("data-choice-state"),
      ).toBe("active");
      expect(
        deps.updateTransportChoiceUsb.getAttribute("data-choice-badge"),
      ).toBe("settings.update.transport.selected_badge");
      expect(
        deps.updateTransportChoiceUsb.getAttribute("data-disabled"),
      ).toBeNull();
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain(
        "usb0",
      );

      deps.updateStartBtn.click();
      await flushAsyncWork();

      expect(JSON.parse(startBody)).toEqual({
        transport: "usb_internet",
        password: "",
      });
    } finally {
      restoreFetch();
    }
  });
});
