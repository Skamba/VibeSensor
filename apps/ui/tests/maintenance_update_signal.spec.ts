import assert from "node:assert/strict";
import { test } from "vitest";

import type { UpdateStartRequestPayload } from "../src/api/types";
import { flushAsyncWork } from "./async_test_helpers";
import {
  createUpdateFeatureHarness,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";
import {
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUsbInternetStatus,
} from "./maintenance_payload_test_support";
import {
  buildUpdateHandlers,
  makeUpdateStartPayload,
} from "./msw/handlers/maintenance";
import { createUiMswTestScope } from "./msw/node";

function assertContains(
  text: string | null | undefined,
  expected: string,
): void {
  assert.ok(
    (text ?? "").includes(expected),
    `Expected ${JSON.stringify(text ?? "")} to contain ${JSON.stringify(expected)}`,
  );
}

function elementText(element: Element): string {
  return element.textContent ?? "";
}

function stageTexts(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll("li"), elementText);
}

function requireStageText(root: ParentNode, title: string): string {
  const stageText = stageTexts(root).find((text) => text.includes(title));
  assert.ok(stageText, `Expected a stage containing ${JSON.stringify(title)}`);
  return stageText;
}

async function withMaintenanceScope(
  run: (scope: ReturnType<typeof createUiMswTestScope>) => Promise<void>,
) {
  const restoreDomGlobals = installMaintenanceFeatureGlobals();
  const scope = createUiMswTestScope();

  try {
    await run(scope);
  } finally {
    scope.close();
    restoreDomGlobals();
  }
}

test("update sends Wi-Fi credentials and clears the password after start", async () => {
  await withMaintenanceScope(async (scope) => {
    const startRequests: UpdateStartRequestPayload[] = [];
    let statusRequests = 0;
    scope.server.use(
      ...buildUpdateHandlers({
        health: createHealthyUpdateStatus(),
        internet: createUsbInternetStatus(),
        start: makeUpdateStartPayload({
          transport: "wifi",
          ssid: "MyWiFi",
        }),
        startRequests,
        status: () => {
          statusRequests += 1;
          return createIdleUpdateStatus();
        },
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      const initialStatusRequests = statusRequests;
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(
        new Event("input", { bubbles: true }),
      );
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input", { bubbles: true }));
      await flushAsyncWork();

      deps.updateStartBtn.click();
      await flushAsyncWork();

      assert.equal(statusRequests, initialStatusRequests + 1);
      assert.equal(deps.updatePasswordInput.value, "");
      assert.deepEqual(startRequests, [
        {
          transport: "wifi",
          ssid: "MyWiFi",
          password: "secret",
        },
      ]);
    } finally {
      feature.dispose();
    }
  });
});

test("update uses USB internet when the user selects USB transport", async () => {
  await withMaintenanceScope(async (scope) => {
    const startRequests: UpdateStartRequestPayload[] = [];
    scope.server.use(
      ...buildUpdateHandlers({
        health: createHealthyUpdateStatus(),
        internet: createUsbInternetStatus({
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
        start: makeUpdateStartPayload({
          transport: "usb_internet",
          ssid: null,
        }),
        startRequests,
        status: createIdleUpdateStatus(),
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;

      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(
        new Event("input", { bubbles: true }),
      );
      await flushAsyncWork();
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      deps.updateTransportUsbRadio.dispatchEvent(
        new Event("change", { bubbles: true }),
      );
      await flushAsyncWork();

      assert.equal(deps.updateTransportOptions.hidden, false);
      assert.equal(deps.updateWifiFields.hidden, true);
      assert.equal(deps.updateStartBtn.disabled, false);
      assertContains(
        elementText(deps.updateReadinessSummary),
        "USB internet ready on usb0.",
      );
      assert.equal(
        deps.updateDetailsCaption.textContent,
        "USB internet details",
      );
      assert.equal(
        deps.updateTransportNote.textContent,
        "USB internet will be used for update checks.",
      );
      assert.equal(
        deps.updateUsbTransportSummary.textContent,
        "USB interface usb0",
      );
      assert.equal(deps.updateTransportWifiRadio.checked, false);
      assert.equal(deps.updateTransportUsbRadio.checked, true);
      assert.equal(deps.updateTransportUsbRadio.disabled, false);
      assertContains(elementText(deps.internetStatusPanel), "usb0");

      deps.updateStartBtn.click();
      await flushAsyncWork();

      assert.deepEqual(startRequests, [
        {
          transport: "usb_internet",
          password: "",
        },
      ]);
    } finally {
      feature.dispose();
    }
  });
});

test("update shows recovery details for a failed update", async () => {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
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

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      await flushAsyncWork();
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input", { bubbles: true }));
      await flushAsyncWork();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(
        elementText(deps.updateReadinessSummary),
        "Update recovery",
      );
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Restore network connection",
      );
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Reconnect Wi-Fi or use USB internet.",
      );
      assert.equal(deps.updateStartBtn.textContent, "Retry update");
      assertContains(elementText(deps.els.updateStatusPanel), "Update issues");
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Latest update attempt",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Update log failed",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Hotspot restart timed out",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "NetworkManager is still reconnecting to the uplink.",
      );
      const stoppedStage = requireStageText(
        deps.els.updateStatusPanel,
        "Restoring hotspot",
      );
      assertContains(stoppedStage, "Needs attention");
    } finally {
      feature.dispose();
    }
  });
});
