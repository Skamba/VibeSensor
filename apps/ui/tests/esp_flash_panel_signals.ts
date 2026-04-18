import assert from "node:assert/strict";

import { options } from "preact";

import { setUiLanguage } from "../src/app/ui_i18n";
import { signal } from "../src/app/ui_signals";
import type {
  EspFlashPanelActionHandlers,
  EspFlashPanelRenderModel,
  EspFlashPanelView,
} from "../src/app/views/esp_flash_panel";
import { mountSignalView } from "./dom_render_test_support";

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runEspFlashPanelSignalMemoTest(): Promise<void> {
  const previousDiffed = options.diffed;
  const previousLanguage = "en";
  let panelRenderCount = 0;
  let readinessRenderCount = 0;
  let journeyRenderCount = 0;
  let logRenderCount = 0;
  let historyRenderCount = 0;
  options.diffed = (vnode) => {
    if (typeof vnode.type === "function" && vnode.type.name === "EspFlashPanel") {
      panelRenderCount += 1;
    }
    if (typeof vnode.type === "function" && vnode.type.displayName === "Memo(EspFlashReadinessSection)") {
      readinessRenderCount += 1;
    }
    if (typeof vnode.type === "function" && vnode.type.displayName === "Memo(EspFlashJourneySection)") {
      journeyRenderCount += 1;
    }
    if (typeof vnode.type === "function" && vnode.type.displayName === "Memo(EspFlashLogContent)") {
      logRenderCount += 1;
    }
    if (typeof vnode.type === "function" && vnode.type.displayName === "Memo(EspFlashHistoryContent)") {
      historyRenderCount += 1;
    }
    previousDiffed?.(vnode);
  };

  const harness = await mountSignalView(
    async () => {
      const { mountEspFlashPanel } = await import("../src/app/views/esp_flash_panel");
      return mountEspFlashPanel;
    },
    () => ({
      actions: signal<EspFlashPanelActionHandlers | null>(null),
      model: signal(null),
    } satisfies EspFlashPanelView),
  );

  try {
    await harness.flush();
    assert.equal(panelRenderCount, 1);

    const panelModel = signal<EspFlashPanelRenderModel>({
      cancelButtonDisabled: true,
      cancelButtonHidden: true,
      history: {
        attempts: [{
          badge: { text: "Done", variant: "ok" },
          errorText: null,
          metaText: "latest flash",
          portText: "/dev/ttyUSB0",
        }],
        emptyState: null,
      },
      journey: {
        stages: [{
          current: true,
          detailText: "Build firmware",
          markerText: "1",
          phase: "build",
          state: "active",
          stateText: "Running",
          titleText: "Build",
        }],
        terminalNoteText: null,
      },
      log: {
        emptyState: null,
        text: "first line",
      },
      portOptions: [{ labelText: "Auto-detect", value: "__auto__" }],
      portSelectDisabled: false,
      readiness: {
        errorText: null,
        rows: [{ labelText: "Board", valueText: "Ready" }],
        summaryText: "Ready to flash",
      },
      refreshPortsDisabled: false,
      selectedPortValue: "__auto__",
      startButtonDisabled: false,
      startButtonHidden: false,
      startButtonLabelText: "Flash latest",
      startSummary: {
        items: [],
        stateLabel: "Ready",
        stateVariant: "ok",
        summary: "Can start now",
        title: "Summary",
      },
      statusBanner: {
        text: "Idle",
        variant: "muted",
      },
    });
    harness.view.model.value = panelModel;
    await harness.flush();

    assert.equal(panelRenderCount, 1);
    assert.equal(readinessRenderCount, 1);
    assert.equal(journeyRenderCount, 1);
    assert.equal(logRenderCount, 1);
    assert.equal(historyRenderCount, 1);
    assert.match(requireElement(harness.host, "#espFlashReadinessPanel").textContent ?? "", /Ready to flash/);
    assert.match(requireElement(harness.host, "#espFlashLogPanel").textContent ?? "", /first line/);
    assert.match(requireElement(harness.host, "#espFlashHistoryPanel").textContent ?? "", /latest flash/);

    const readinessBaseline = readinessRenderCount;
    const journeyBaseline = journeyRenderCount;
    const logBaseline = logRenderCount;
    const historyBaseline = historyRenderCount;
    panelModel.value = {
      ...panelModel.value,
      log: {
        ...panelModel.value.log,
        text: "first line\nsecond line",
      },
    };
    await harness.flush();

    assert.equal(panelRenderCount, 1);
    assert.equal(readinessRenderCount, readinessBaseline);
    assert.equal(journeyRenderCount, journeyBaseline);
    assert.equal(logRenderCount, logBaseline);
    assert.equal(historyRenderCount, historyBaseline);

    const parentReadinessBaseline = readinessRenderCount;
    const parentJourneyBaseline = journeyRenderCount;
    const parentLogBaseline = logRenderCount;
    const parentHistoryBaseline = historyRenderCount;
    setUiLanguage("de");
    await harness.flush();

    assert.equal(panelRenderCount, 1);
    assert.equal(readinessRenderCount, parentReadinessBaseline);
    assert.equal(journeyRenderCount, parentJourneyBaseline);
    assert.equal(logRenderCount, parentLogBaseline);
    assert.equal(historyRenderCount, parentHistoryBaseline);
  } finally {
    setUiLanguage(previousLanguage);
    options.diffed = previousDiffed;
    harness.cleanup();
  }
}

await runEspFlashPanelSignalMemoTest();
console.log("PASS esp flash memoized signal sections avoid parent rerender");
