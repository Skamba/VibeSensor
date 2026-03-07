import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, normalizePathname, requestPath } from "./smoke.helpers";

test("settings esp flash tab renders lifecycle state and live logs", async ({ page }) => {
  let statusState: "idle" | "running" | "success" = "idle";
  let logCursor = 0;
  const logs = ["build ok", "erase ok", "upload ok"];
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const url = new URL(route.request().url());
      const path = normalizePathname(url.pathname);
      if (path === "/api/settings/esp-flash/ports") {
        await fulfillJson(route, { ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
        return;
      }
      if (path === "/api/settings/esp-flash/start") {
        statusState = "running";
        logCursor = 0;
        await fulfillJson(route, { status: "started", job_id: 1 });
        return;
      }
      if (path === "/api/settings/esp-flash/status") {
        if (statusState === "running" && logCursor >= logs.length) statusState = "success";
        await fulfillJson(route, { state: statusState, phase: statusState === "running" ? "flashing" : "done", job_id: 1, selected_port: "/dev/ttyUSB0", auto_detect: false, started_at: 1, finished_at: statusState === "running" ? null : 2, last_success_at: statusState === "success" ? 2 : null, exit_code: statusState === "success" ? 0 : null, error: null, log_count: logCursor });
        return;
      }
      if (path === "/api/settings/esp-flash/logs") {
        const after = Number(url.searchParams.get("after") || "0");
        if (after === 0) logCursor = Math.min(logs.length, logCursor + 2); else logCursor = logs.length;
        await fulfillJson(route, { from_index: after, next_index: logCursor, lines: logs.slice(after, logCursor) });
        return;
      }
      if (path === "/api/settings/esp-flash/history") {
        await fulfillJson(route, { attempts: statusState === "success" ? [{ job_id: 1, state: "success", selected_port: "/dev/ttyUSB0", auto_detect: false, started_at: 1, finished_at: 2, exit_code: 0, error: null }] : [] });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="espFlashTab"]').click();
  await page.locator("#espFlashStartBtn").click();
  statusState = "running";
  logCursor = 2;
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Running");
  await expect(page.locator("#espFlashLogPanel")).toContainText("erase ok");
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Success");
  await expect(page.locator("#espFlashHistoryPanel")).toContainText("/dev/ttyUSB0");
});

test("settings esp flash status falls back to idle when API omits state", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/esp-flash/ports") {
        await fulfillJson(route, { ports: [] });
        return;
      }
      if (path === "/api/settings/esp-flash/status") {
        await fulfillJson(route, { log_count: 0, error: null });
        return;
      }
      if (path === "/api/settings/esp-flash/history") {
        await fulfillJson(route, { attempts: [] });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="espFlashTab"]').click();
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Idle");
});