import assert from "node:assert/strict";
import { test } from "vitest";

import { flushAsyncWork } from "./async_test_helpers";
import {
  createEspFlashFeatureHarness,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";
import { createEspFlashPort } from "./maintenance_payload_test_support";
import {
  buildEspFlashHandlers,
  makeEspFlashStatusPayload,
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

function assertCompletedStageCount(
  root: ParentNode,
  expectedCount: number,
): void {
  assert.equal(
    stageTexts(root).filter((text) => text.includes("Complete")).length,
    expectedCount,
  );
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

test("esp flash lets a user choose a serial port before starting", async () => {
  await withMaintenanceScope(async (scope) => {
    const startRequests: Array<{ auto_detect: boolean; port: string | null }> =
      [];
    scope.server.use(
      ...buildEspFlashHandlers({
        ports: {
          ports: [
            createEspFlashPort(),
            createEspFlashPort({
              description: "ESP32 Bootloader",
              pid: 4,
              port: "/dev/ttyUSB1",
              serial_number: "def",
              vid: 3,
            }),
          ],
        },
        startRequests,
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      deps.els.espFlashPortSelect.value = "/dev/ttyUSB1";
      deps.els.espFlashPortSelect.dispatchEvent(
        new Event("change", { bubbles: true }),
      );
      deps.espFlashStartBtn.click();
      await flushAsyncWork();

      assert.deepEqual(startRequests, [
        {
          auto_detect: false,
          port: "/dev/ttyUSB1",
        },
      ]);
    } finally {
      feature.dispose();
    }
  });
});

test("esp flash shows recovery details for a failed flash", async () => {
  await withMaintenanceScope(async (scope) => {
    let status = makeEspFlashStatusPayload({
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      auto_detect: false,
      error: null,
    });
    scope.server.use(
      ...buildEspFlashHandlers({
        ports: { ports: [createEspFlashPort()] },
        status: () => status,
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
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

      const stoppedStage = requireStageText(
        deps.espFlashJourneyPanel,
        "Flashing",
      );
      assertContains(stoppedStage, "Needs attention");
      assertContains(elementText(deps.espFlashStartSummary), "Flash recovery");
      assertContains(
        elementText(deps.espFlashStartSummary),
        "Reconnect the ESP and retry flashing.",
      );
      assert.equal(deps.espFlashStartBtn.textContent, "Retry flash");
      assertContains(
        elementText(deps.els.espFlashLogPanel),
        "Flash log failed",
      );
      assertContains(
        elementText(deps.els.espFlashHistoryPanel),
        "serial port disconnected",
      );
      assertCompletedStageCount(deps.espFlashJourneyPanel, 3);
      assertContains(
        elementText(deps.espFlashReadinessPanel),
        "serial port disconnected",
      );
    } finally {
      feature.dispose();
    }
  });
});
