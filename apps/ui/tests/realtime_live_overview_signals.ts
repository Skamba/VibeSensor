import assert from "node:assert/strict";

import { options } from "preact";

import { computed, signal } from "../src/app/ui_signals";
import type {
  RealtimeLiveOverviewRenderModel,
  RealtimeLiveOverviewSensorCardModel,
} from "../src/app/views/realtime_live_overview";
import { mountSignalView } from "./dom_render_test_support";

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runRealtimeLiveOverviewSignalProjectionTest(): Promise<void> {
  const connectedSensorsText = signal("2 / 4");
  const activeCarText = signal("Roadster");
  const activeCarWarning = signal(false);
  const recordingStateText = signal("Stopped");
  const dataFreshnessText = signal("Fresh");
  const strongestSignalText = signal("68 dB");
  const runHealthText = signal("Ready");
  const runHealthVariant = signal<RealtimeLiveOverviewRenderModel["runHealth"]["variant"]>("ok");
  const sensorCards = signal<RealtimeLiveOverviewSensorCardModel[]>([]);
  const model = computed<RealtimeLiveOverviewRenderModel>(() => ({
    activeCar: {
      text: activeCarText.value,
      warning: activeCarWarning.value,
    },
    connectedSensorsText: connectedSensorsText.value,
    dataFreshnessText: dataFreshnessText.value,
    recordingStateText: recordingStateText.value,
    runHealth: {
      hidden: false,
      text: runHealthText.value,
      variant: runHealthVariant.value,
    },
    sensorCards: sensorCards.value,
    strongestSignalText: strongestSignalText.value,
  }));
  const previousDiffed = options.diffed;
  let overviewRenderCount = 0;
  options.diffed = (vnode) => {
    if (typeof vnode.type === "function" && vnode.type.name === "RealtimeLiveOverview") {
      overviewRenderCount += 1;
    }
    previousDiffed?.(vnode);
  };

  const harness = await mountSignalView(async () => {
    const { mountRealtimeLiveOverview } = await import("../src/app/views/realtime_live_overview");
    return mountRealtimeLiveOverview;
  });

  try {
    harness.view.bindModel(model);
    harness.view.setSpeedText("43 km/h");
    await harness.flush();

    assert.equal(overviewRenderCount, 1);
    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "2 / 4");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "68 dB");
    assert.equal(requireElement(harness.host, "#speed").textContent, "43 km/h");
    assert.equal(requireElement(harness.host, "#liveRunHealth").textContent, "Ready");

    connectedSensorsText.value = "4 / 4";
    strongestSignalText.value = "82 dB";
    await harness.flush();

    assert.equal(overviewRenderCount, 1);
    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "4 / 4");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "82 dB");

    sensorCards.value = [
      {
        connected: true,
        id: "front-left",
        label: "Front Left",
        statusText: "Online",
        strongest: true,
      },
    ];
    await harness.flush();

    assert.equal(overviewRenderCount, 1);
    assert.equal(harness.host.querySelectorAll(".live-sensor-card--strongest").length, 1);
    assert.match(harness.host.textContent ?? "", /Front Left/);
  } finally {
    options.diffed = previousDiffed;
    harness.cleanup();
  }
}

await runRealtimeLiveOverviewSignalProjectionTest();
console.log("PASS realtime live overview signal projections avoid rerender");
