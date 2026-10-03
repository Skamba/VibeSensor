import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openEspFlashTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 25_000 });

type FlashServer = {
  ports: Array<{ port: string; description: string }>;
  status: Record<string, unknown>;
  logs: string[];
  attempts: Array<Record<string, unknown>>;
  starts: Array<Record<string, unknown>>;
  cancels: number;
  /** Delay before answering start/cancel, to exercise in-flight guards. */
  actionDelayMs: number;
};

function idleStatus(): Record<string, unknown> {
  return {
    auto_detect: true,
    error: null,
    exit_code: null,
    finished_at: null,
    job_id: null,
    last_success_at: null,
    log_count: 0,
    phase: "idle",
    selected_port: null,
    started_at: null,
    state: "idle",
  };
}

function createServer(): FlashServer {
  return {
    ports: [],
    status: idleStatus(),
    logs: [],
    attempts: [],
    starts: [],
    cancels: 0,
    actionDelayMs: 0,
  };
}

async function bootWithFlashServer(page: Page, server: FlashServer) {
  await bootLiveDashboard(page, {
    espFlashHandler: async (route: Route) => {
      const path = requestPath(route);
      if (path === "/api/esp-flash/ports") {
        await fulfillJson(route, { ports: server.ports });
        return;
      }
      if (path === "/api/esp-flash/status") {
        await fulfillJson(route, server.status);
        return;
      }
      if (path === "/api/esp-flash/logs") {
        const after = Number(
          new URL(route.request().url()).searchParams.get("after"),
        );
        await fulfillJson(route, {
          from_index: after,
          lines: server.logs.slice(after),
          next_index: server.logs.length,
        });
        return;
      }
      if (path === "/api/esp-flash/history") {
        await fulfillJson(route, { attempts: server.attempts });
        return;
      }
      if (path === "/api/esp-flash/start") {
        await new Promise((resolve) =>
          setTimeout(resolve, server.actionDelayMs),
        );
        const body = route.request().postDataJSON() as Record<string, unknown>;
        server.starts.push(body);
        server.logs = ["Building firmware...", "Writing at 0x00010000 (50 %)"];
        server.status = {
          ...idleStatus(),
          auto_detect: body.auto_detect,
          job_id: 7,
          log_count: server.logs.length,
          phase: "flashing",
          selected_port: body.port,
          started_at: 1_700_000_000,
          state: "running",
        };
        await fulfillJson(route, { job_id: 7, status: "running" });
        return;
      }
      if (path === "/api/esp-flash/cancel") {
        server.cancels += 1;
        await new Promise((resolve) =>
          setTimeout(resolve, server.actionDelayMs),
        );
        server.status = {
          ...server.status,
          phase: "cancelled",
          state: "cancelled",
          finished_at: 1_700_000_010,
        };
        await fulfillJson(route, { cancelled: true });
        return;
      }
      await fulfillJson(route, {});
    },
  });
}

test("journey: ESP flash detects a board, flashes it, and records the attempt", async ({
  page,
}) => {
  const server = createServer();
  await bootWithFlashServer(page, server);
  await openEspFlashTab(page);

  const startButton = page.locator("#espFlashStartBtn");
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Idle");
  await expect(page.locator("#espFlashHistoryPanel")).toContainText(
    "No recent flash attempts",
  );
  await expect(page.locator("#espFlashStartSummary")).toContainText(
    "Connect the ESP board over USB and refresh the port list.",
  );
  await expect(startButton).toBeDisabled();

  server.ports = [{ port: "/dev/ttyUSB0", description: "CP2102 USB to UART" }];
  await page.locator("#espFlashRefreshPortsBtn").click();
  const portSelect = page.locator("#espFlashPortSelect");
  await expect(portSelect.locator("option")).toHaveCount(2);
  await expect(startButton).toBeEnabled();
  await expect(startButton).toHaveText("Flash latest");
  await portSelect.selectOption("/dev/ttyUSB0");

  await startButton.click();
  await expect
    .poll(() => server.starts)
    .toEqual([{ port: "/dev/ttyUSB0", auto_detect: false }]);
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Running");
  await expect(page.locator("#espFlashLogPanel")).toContainText(
    "Writing at 0x00010000 (50 %)",
  );
  await expect(page.locator("#espFlashCancelBtn")).toBeVisible();
  await expect(portSelect).toBeDisabled();

  // The job finishes; polling picks up the final state and history.
  server.logs = [...server.logs, "Hard resetting via RTS pin..."];
  server.status = {
    ...server.status,
    log_count: server.logs.length,
    phase: "done",
    state: "success",
    exit_code: 0,
    finished_at: 1_700_000_030,
    last_success_at: 1_700_000_030,
  };
  server.attempts = [
    {
      auto_detect: false,
      error: null,
      exit_code: 0,
      finished_at: 1_700_000_030,
      job_id: 7,
      selected_port: "/dev/ttyUSB0",
      started_at: 1_700_000_000,
      state: "success",
    },
  ];
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Success", {
    timeout: 10_000,
  });
  await expect(page.locator("#espFlashLogPanel")).toContainText(
    "Hard resetting via RTS pin...",
  );
  await expect(page.locator("#espFlashHistoryPanel")).toContainText(
    "/dev/ttyUSB0",
  );
  await expect(page.locator("#espFlashCancelBtn")).toBeHidden();
});

test("journey: ESP flash cancels a running job and offers a retry", async ({
  page,
}) => {
  const server = createServer();
  server.ports = [{ port: "/dev/ttyACM0", description: "USB JTAG" }];
  await bootWithFlashServer(page, server);
  await openEspFlashTab(page);

  await page.locator("#espFlashStartBtn").click();
  await expect
    .poll(() => server.starts)
    .toEqual([{ port: null, auto_detect: true }]);
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Running");

  await page.locator("#espFlashCancelBtn").click();
  await expect.poll(() => server.cancels).toBe(1);
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Cancelled");
  await expect(page.locator("#espFlashStartBtn")).toHaveText("Retry flash");
  await expect(page.locator("#espFlashReadinessPanel")).toContainText(
    "The last flash was cancelled.",
  );
});

test("journey: ESP flash ignores repeated start and cancel clicks while a request is in flight", async ({
  page,
}) => {
  const server = createServer();
  server.ports = [{ port: "/dev/ttyACM0", description: "USB JTAG" }];
  server.actionDelayMs = 400;
  const startRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/esp-flash/start")) {
      startRequests.push(request.method());
    }
  });
  await bootWithFlashServer(page, server);
  await openEspFlashTab(page);

  await page.locator("#espFlashStartBtn").dblclick();
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Running");
  expect(startRequests).toEqual(["POST"]);

  await page.locator("#espFlashCancelBtn").dblclick();
  await expect(page.locator("#espFlashStatusBanner")).toHaveText("Cancelled");
  expect(server.cancels).toBe(1);
});
