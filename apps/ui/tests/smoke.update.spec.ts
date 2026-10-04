import { expect, test, type Page } from "@playwright/test";

import type {
  HealthStatusPayload,
  UpdateCancelPayload,
  UpdateStartPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/api/types";
import {
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
} from "./maintenance_payload_test_support";
import {
  bootLiveDashboard,
  fulfillJson,
  installCommonRoutes,
  openInternetTab,
  openUpdateTab,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

type UpdateServer = {
  status: UpdateStatusPayload;
  starts: UpdateStartRequestPayload[];
  cancels: number;
  startDelayMs?: number;
  internet?: UsbInternetStatusPayload;
  health?: HealthStatusPayload;
};

const USABLE_USB_INTERNET: UsbInternetStatusPayload = {
  detected: true,
  usable: true,
  interface_name: "usb0",
  connection_name: "Pixel tether",
  driver: "rndis_host",
  ipv4_addresses: ["192.168.42.17/24"],
  gateway: "192.168.42.129",
  has_default_route: true,
  diagnostic: "USB uplink is ready.",
};

async function bootWithUpdateServer(
  page: Page,
  server: UpdateServer,
): Promise<void> {
  await installCommonRoutes(page);
  await page.route("**/api/update/internet-status", async (route) => {
    await fulfillJson(route, server.internet ?? USABLE_USB_INTERNET);
  });
  await page.route("**/api/health", async (route) => {
    await fulfillJson(route, server.health ?? createHealthyUpdateStatus());
  });
  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, server.status);
  });
  await page.route("**/api/update/start", async (route) => {
    await new Promise((resolve) =>
      setTimeout(resolve, server.startDelayMs ?? 0),
    );
    const body = route.request().postDataJSON() as UpdateStartRequestPayload;
    server.starts.push(body);
    server.status = createIdleUpdateStatus({
      state: "running",
      phase: "downloading",
      transport: body.transport,
      ssid: body.ssid ?? null,
      started_at: Date.now() / 1000,
      phase_started_at: Date.now() / 1000,
      log_tail: ["Downloading vibesensor-2.0.0.whl"],
    });
    await fulfillJson<UpdateStartPayload>(route, {
      status: "started",
      transport: body.transport,
      ssid: body.ssid ?? null,
    });
  });
  await page.route("**/api/update/cancel", async (route) => {
    server.cancels += 1;
    server.status = createIdleUpdateStatus({
      state: "failed",
      phase: "done",
      issues: [
        { phase: "downloading", message: "Cancelled by user", detail: "" },
      ],
    });
    await fulfillJson<UpdateCancelPayload>(route, { cancelled: true });
  });
  await bootLiveDashboard(page, { installRoutes: false });
}

test("journey: Internet tab shows a usable USB uplink and the update runs over it", async ({
  page,
}) => {
  const server: UpdateServer = {
    status: createIdleUpdateStatus(),
    starts: [],
    cancels: 0,
  };
  await bootWithUpdateServer(page, server);
  await openInternetTab(page);

  const internetStatus = page.locator("#internetStatusPanel");
  await expect(internetStatus).toContainText("Usable");
  await expect(internetStatus).toContainText("usb0");
  await expect(internetStatus).toContainText("192.168.42.17/24");

  await page.locator("#updateTransportChoiceUsb").click();
  await expect(page.locator("#updateWifiFields")).toBeHidden();
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "USB internet is ready on usb0.",
  );

  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
  await page.locator("#updateStartBtn").click();
  await expect
    .poll(() => server.starts)
    .toEqual([{ transport: "usb_internet", password: "" }]);
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "Downloading update...",
  );
  await expect(page.locator("#updateCancelBtn")).toBeVisible();

  await page.locator("#updateCancelBtn").click();
  await expect.poll(() => server.cancels).toBe(1);
  await expect(page.locator("#updateStartBtn")).toHaveText("Retry Update");
});

test("journey: a Wi-Fi update sends the credentials and clears the password", async ({
  page,
}) => {
  const server: UpdateServer = {
    status: createIdleUpdateStatus(),
    starts: [],
    cancels: 0,
  };
  await bootWithUpdateServer(page, server);
  await openInternetTab(page);

  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Enter a Wi-Fi SSID to enable Start Update.",
  );
  await page.locator("#updateSsidInput").fill("Workshop Wi-Fi");
  await page.locator("#updatePasswordInput").fill("hunter22");
  await expect(page.locator("#updatePasswordInput")).toHaveAttribute(
    "type",
    "password",
  );
  await page.locator("#updateTogglePasswordBtn").click();
  await expect(page.locator("#updatePasswordInput")).toHaveAttribute(
    "type",
    "text",
  );

  await openUpdateTab(page);
  await page.locator("#updateStartBtn").click();
  await expect
    .poll(() => server.starts)
    .toEqual([
      { transport: "wifi", ssid: "Workshop Wi-Fi", password: "hunter22" },
    ]);
  await openInternetTab(page);
  await expect(page.locator("#updatePasswordInput")).toHaveValue("");
  // Credentials are locked while the update runs.
  await expect(page.locator("#updateSsidInput")).toBeDisabled();
});

test("journey: the last Wi-Fi network is prefilled and a double-clicked start sends one request", async ({
  page,
}) => {
  const server: UpdateServer = {
    status: createIdleUpdateStatus({
      state: "success",
      phase: "done",
      transport: "wifi",
      ssid: "Shop Wi-Fi",
    }),
    starts: [],
    cancels: 0,
    startDelayMs: 400,
  };
  await bootWithUpdateServer(page, server);
  await openInternetTab(page);
  await expect(page.locator("#updateSsidInput")).toHaveValue("Shop Wi-Fi");

  await openUpdateTab(page);
  await page.locator("#updateStartBtn").dblclick();
  await expect(page.locator("#updateCancelBtn")).toBeVisible();
  expect(server.starts).toEqual([
    { transport: "wifi", ssid: "Shop Wi-Fi", password: "" },
  ]);
});

test("journey: retrying a failed Wi-Fi update without an SSID leads back to the SSID field", async ({
  page,
}) => {
  const server: UpdateServer = {
    status: createIdleUpdateStatus({
      state: "failed",
      phase: "connecting_wifi",
      transport: "wifi",
      issues: [
        {
          phase: "connecting_wifi",
          message: "Wrong password",
          detail: "802.1X authentication failed",
        },
      ],
    }),
    starts: [],
    cancels: 0,
    internet: {
      ...USABLE_USB_INTERNET,
      detected: false,
      usable: false,
      interface_name: null,
    },
  };
  await bootWithUpdateServer(page, server);
  await openUpdateTab(page);
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "Wrong password",
  );
  const retry = page.locator("#updateStartBtn");
  await expect(retry).toHaveText("Retry Update");
  await retry.click();
  await expect(page.locator("#updateSsidInput")).toBeFocused();
  await expect(page.locator("#internetTab")).toBeVisible();
  expect(server.starts).toEqual([]);
});

test("journey: an invalid updater status is reported instead of shown", async ({
  page,
}) => {
  const server: UpdateServer = {
    // Deliberately malformed: the UI must reject it at the API boundary.
    status: { state: "exploded" } as unknown as UpdateStatusPayload,
    starts: [],
    cancels: 0,
  };
  await bootWithUpdateServer(page, server);
  await openUpdateTab(page);
  await expect(page.locator("#appErrorBanner")).toBeVisible();
  await expect(page.locator("#updateOverviewPanel")).toBeEmpty();
});

test("journey: an outdated root side explains the reinstall without blocking the update", async ({
  page,
}) => {
  const healthy = createHealthyUpdateStatus();
  const server: UpdateServer = {
    status: createIdleUpdateStatus(),
    starts: [],
    cancels: 0,
    health: {
      ...healthy,
      subsystems: {
        ...healthy.subsystems,
        root_side: { status: "degraded", reason_codes: ["root_side_outdated"] },
      },
      root_side: {
        ...healthy.root_side,
        state: "outdated",
        installed_digest: null,
      },
    },
  };
  await bootWithUpdateServer(page, server);
  await openUpdateTab(page);

  const note = page.locator("#rootSideOutdatedNote");
  await expect(note).toContainText("do not match this app (server-v1.2.3)");
  await expect(note).toContainText(
    "apps/server/scripts/push_root_side.sh pi@10.4.0.1",
  );
  await expect(note).toContainText(
    "sudo apps/server/scripts/install_systemd_units.sh",
  );
  await expect(note.getByRole("link")).toHaveAttribute(
    "href",
    /operational-runbooks\.md#installing-a-releases-root-side$/,
  );
  await expect(page.locator("#updateOverviewPanel")).toContainText(
    "root side: degraded (root_side_outdated)",
  );
  await openInternetTab(page);
  await page.locator("#updateSsidInput").fill("Workshop");
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
});
