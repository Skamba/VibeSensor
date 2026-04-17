import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, normalizePathname, requestPath } from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

test("settings esp flash tab renders lifecycle state and live logs", async ({ page }) => {
  let statusState: "idle" | "running" | "success" = "idle";
  let logCursor = 0;
  const logs = Array.from(
    { length: 18 },
    (_, index) => `flash line ${index}: ${"output ".repeat(12)}`,
  );
  await installCommonRoutes(page, {
    espFlashHandler: async (route) => {
      const url = new URL(route.request().url());
      const path = normalizePathname(url.pathname);
      if (path === "/api/esp-flash/ports") {
        await fulfillJson(route, { ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
        return;
      }
      if (path === "/api/esp-flash/start") {
        statusState = "running";
        logCursor = 0;
        await fulfillJson(route, { status: "started", job_id: 1 });
        return;
      }
      if (path === "/api/esp-flash/status") {
        if (statusState === "running" && logCursor >= logs.length) statusState = "success";
        await fulfillJson(route, { state: statusState, phase: statusState === "running" ? "flashing" : "done", job_id: 1, selected_port: "/dev/ttyUSB0", auto_detect: false, started_at: 1, finished_at: statusState === "running" ? null : 2, last_success_at: statusState === "success" ? 2 : null, exit_code: statusState === "success" ? 0 : null, error: null, log_count: logCursor });
        return;
      }
      if (path === "/api/esp-flash/logs") {
        const after = Number(url.searchParams.get("after") || "0");
        if (after === 0) logCursor = Math.min(logs.length, logCursor + 2); else logCursor = logs.length;
        await fulfillJson(route, { from_index: after, next_index: logCursor, lines: logs.slice(after, logCursor) });
        return;
      }
      if (path === "/api/esp-flash/history") {
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
  await expect(page.locator("#espFlashPortSelect option")).toHaveCount(2);
  await expect(page.locator("#espFlashPortSelect option").first()).toHaveText(
    "Auto-detect",
  );
  await expect(page.locator("#espFlashPortSelect option").nth(1)).toHaveText(
    "/dev/ttyUSB0 — USB UART",
  );
  await expect(page.locator("#espFlashStartBtn")).toBeEnabled();
  await expect(page.locator("#espFlashCancelBtn")).toBeHidden();
  await expect(page.locator("#espFlashStartSummary")).toContainText(
    "A flash target is ready and the job can start.",
  );
  await expect(page.locator("#espFlashStartSummary")).toContainText(
    "/dev/ttyUSB0 — USB UART detected and ready for flashing.",
  );
  await expect(page.locator("#espFlashReadinessPanel")).toContainText(
    "Detected ports",
  );
  await expect(page.locator("#espFlashTab")).not.toContainText(
    "Current readiness",
  );
  await expect(page.locator("#espFlashTab")).toContainText("What happens next");
  await page.locator("#espFlashLogPanel").evaluate((panel) => {
    if (!(panel instanceof HTMLElement)) {
      return;
    }
    panel.style.height = "48px";
    panel.style.overflowY = "auto";
    panel.scrollTop = 0;
  });
  await page.locator("#espFlashStartBtn").click();
  statusState = "running";
  logCursor = 2;
  const pairedLayout = await page.evaluate(() => {
    const journeyCard = document.querySelector("#espFlashJourneyPanel")?.closest(".maintenance-card");
    const logCard = document.querySelector("#espFlashLogPanel")?.closest(".maintenance-card");
    const readinessCard = document.querySelector("#espFlashReadinessPanel")?.closest(".maintenance-card");
    const summaryCard = document.querySelector("#espFlashStartSummary")?.closest(".maintenance-card");
    if (!(journeyCard instanceof HTMLElement) || !(logCard instanceof HTMLElement)) {
      return null;
    }
    const journeyRect = journeyCard.getBoundingClientRect();
    const logRect = logCard.getBoundingClientRect();
    return {
      topDelta: Math.abs(journeyRect.top - logRect.top),
      leftDelta: logRect.left - journeyRect.left,
      readinessGrouped:
        readinessCard instanceof HTMLElement &&
        summaryCard instanceof HTMLElement &&
        readinessCard === summaryCard,
    };
  });
  expect(pairedLayout).not.toBeNull();
  expect(pairedLayout?.topDelta ?? 999).toBeLessThan(8);
  expect(pairedLayout?.leftDelta ?? 0).toBeGreaterThan(40);
  expect(pairedLayout?.readinessGrouped).toBe(true);
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Running");
  await expect(page.locator("#espFlashStartBtn")).toBeHidden();
  await expect(page.locator("#espFlashCancelBtn")).toBeVisible();
  await expect(page.locator("#espFlashReadinessPanel")).toContainText("/dev/ttyUSB0");
  await expect(page.locator("#espFlashReadinessPanel")).not.toContainText("Expected stages");
  await expect(page.locator("#espFlashJourneyPanel")).toContainText("Write firmware");
  await expect(page.locator('#espFlashJourneyPanel .maintenance-stage[aria-current="step"]')).toHaveAttribute("data-stage-phase", "flashing");
  await expect(page.locator('#espFlashJourneyPanel .maintenance-stage[data-stage-state="done"]')).toHaveCount(3);
  await expect(page.locator('#espFlashJourneyPanel .maintenance-stage[data-stage-phase="validating"] .maintenance-stage__marker')).toHaveText("✓");
  await expect(page.locator("#espFlashLogPanel")).toContainText("flash line 17");
  await expect.poll(async () =>
    page.locator("#espFlashLogPanel").evaluate((panel) => {
      if (!(panel instanceof HTMLElement)) {
        return false;
      }
      const maxScrollTop = panel.scrollHeight - panel.clientHeight;
      return maxScrollTop > 0 && panel.scrollTop >= maxScrollTop - 1;
    })).toBe(true);
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Success");
  await expect(page.locator('#espFlashJourneyPanel .maintenance-stage[data-stage-state="done"]')).toHaveCount(5);
  await expect(page.locator("#espFlashHistoryPanel")).toContainText("/dev/ttyUSB0");
});

test("settings esp flash status falls back to idle when API omits state", async ({ page }) => {
  await installCommonRoutes(page, {
    espFlashHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/esp-flash/ports") {
        await fulfillJson(route, { ports: [] });
        return;
      }
      if (path === "/api/esp-flash/status") {
        await fulfillJson(route, { log_count: 0, error: null });
        return;
      }
      if (path === "/api/esp-flash/history") {
        await fulfillJson(route, { attempts: [] });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="espFlashTab"]').click();
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Idle");
  await expect(page.locator("#espFlashStartBtn")).toBeDisabled();
  await expect(page.locator("#espFlashCancelBtn")).toBeHidden();
  await expect(page.locator("#espFlashStartSummary")).toContainText(
    "Connect the board and clear the blocked item before flashing.",
  );
  await expect(page.locator("#espFlashStartSummary")).toContainText(
    "Connect the ESP board over USB and refresh the port list.",
  );
  await expect(page.locator("#espFlashReadinessPanel")).toContainText("No serial device is detected yet");
  await expect(page.locator("#espFlashTab")).not.toContainText("Current readiness");
  await expect(page.locator("#espFlashJourneyPanel")).toContainText("Validate board and bundle");
  await expect(page.locator("#espFlashTab")).toContainText("What happens next");
  await expect(page.locator("#espFlashLogPanel")).toContainText("No active flash log");
  await expect(page.locator("#espFlashHistoryPanel")).toContainText("No recent flash attempts");
  await expect(page.locator("#espFlashTab")).toContainText("Starting a flash builds the latest firmware");
});

test("settings esp flash failure shows retry guidance, retained failed stage, and fallback attempt history", async ({ page }) => {
  await installCommonRoutes(page, {
    espFlashHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/esp-flash/ports") {
        await fulfillJson(route, {
          ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }],
        });
        return;
      }
      if (path === "/api/esp-flash/status") {
        await fulfillJson(route, {
          state: "failed",
          phase: "flashing",
          selected_port: "/dev/ttyUSB0",
          auto_detect: false,
          started_at: 1,
          finished_at: 2,
          last_success_at: null,
          exit_code: 2,
          error: "serial port disconnected",
          log_count: 0,
        });
        return;
      }
      if (path === "/api/esp-flash/history") {
        await fulfillJson(route, { attempts: [] });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="espFlashTab"]').click();
  await expect(page.locator("#espFlashStartBtn")).toHaveText("Retry flash");
  await expect(page.locator("#espFlashStartBtn")).toBeEnabled();
  await expect(page.locator("#espFlashStartSummary")).toContainText("Recovery guidance");
  await expect(page.locator("#espFlashStartSummary")).toContainText("Failed step");
  await expect(page.locator("#espFlashStartSummary")).toContainText("Write firmware");
  await expect(page.locator("#espFlashStartSummary")).toContainText("Reconnect and retry the upload");
  await expect(page.locator("#espFlashStartSummary")).toContainText("serial port disconnected");
  await expect(page.locator('#espFlashJourneyPanel .maintenance-stage[data-stage-phase="flashing"]')).toHaveAttribute(
    "data-stage-state",
    "attention",
  );
  await expect(page.locator("#espFlashLogPanel")).toContainText("No failure log was captured");
  await expect(page.locator("#espFlashHistoryPanel")).toContainText("/dev/ttyUSB0");
  await expect(page.locator("#espFlashHistoryPanel")).toContainText("serial port disconnected");
});
