import assert from "node:assert/strict";

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

async function runRealtimeLiveOverviewReferenceTest(): Promise<void> {
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

  const harness = await mountSignalView(async () => {
    const { mountRealtimeLiveOverview } = await import("../src/app/views/realtime_live_overview");
    return mountRealtimeLiveOverview;
  });

  try {
    harness.view.bindModel(model);
    harness.view.setSpeedText("43 km/h");
    await harness.flush();

    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "2 / 4");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "68 dB");
    assert.equal(requireElement(harness.host, "#speed").textContent, "43 km/h");
    assert.equal(requireElement(harness.host, "#liveRunHealth").textContent, "Ready");
    assert.match(harness.host.textContent ?? "", /No sensors/i);

    connectedSensorsText.value = "4 / 4";
    strongestSignalText.value = "82 dB";
    activeCarText.value = "Choose a car";
    activeCarWarning.value = true;
    recordingStateText.value = "Recording";
    dataFreshnessText.value = "Live";
    runHealthText.value = "Recording";
    runHealthVariant.value = "warn";
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

    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "4 / 4");
    assert.equal(requireElement(harness.host, "#liveRecordingState [data-value]").textContent, "Recording");
    assert.equal(requireElement(harness.host, "#liveDataFreshness [data-value]").textContent, "Live");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "82 dB");
    assert.equal(requireElement(harness.host, "#liveRunHealth").textContent, "Recording");
    assert.equal(requireElement(harness.host, "#liveRunHealth").getAttribute("data-variant"), "warn");
    assert.match(
      requireElement(harness.host, "#liveActiveCar [data-value]").textContent ?? "",
      /Choose a car/,
    );
    assert.equal(
      requireElement(harness.host, "#liveActiveCar [data-value]").getAttribute("data-variant"),
      "warn",
    );
    assert.equal(harness.host.querySelectorAll(".live-sensor-card--strongest").length, 1);
    assert.match(harness.host.textContent ?? "", /Front Left/);
    assert.doesNotMatch(harness.host.textContent ?? "", /No sensors/i);
  } finally {
    harness.cleanup();
  }
}

async function runSettingsShellReferenceTest(): Promise<void> {
  const harness = await mountSignalView(async () => {
    const { mountSettingsShell } = await import("../src/app/views/settings_shell");
    return mountSettingsShell;
  });

  try {
    const observedTabs: string[] = [];
    const dispose = harness.view.subscribeActiveTabChanges((tabId) => {
      observedTabs.push(tabId);
    });

    assert.equal(harness.view.getActiveTabId(), "carTab");
    assert.deepEqual(observedTabs, []);

    harness.view.activateTab("analysisTab");
    await harness.flush();

    assert.deepEqual(observedTabs, ["analysisTab"]);
    assert.equal(harness.view.getActiveTabId(), "analysisTab");
    assert.equal(
      requireElement(harness.host, '[data-settings-tab="analysisTab"]').getAttribute("aria-selected"),
      "true",
    );
    assert.equal(requireElement(harness.host, "#analysisTab").hidden, false);
    assert.equal(requireElement(harness.host, "#carTab").hidden, true);

    harness.view.activateTab("analysisTab");
    await harness.flush();
    assert.deepEqual(observedTabs, ["analysisTab"]);

    dispose();
    harness.view.activateTab("speedSourceTab");
    await harness.flush();
    assert.deepEqual(observedTabs, ["analysisTab"]);
  } finally {
    harness.cleanup();
  }
}

const referenceTests = [
  {
    name: "realtime live overview computed-driven output",
    run: runRealtimeLiveOverviewReferenceTest,
  },
  {
    name: "settings shell effect-backed subscription seam",
    run: runSettingsShellReferenceTest,
  },
];

for (const referenceTest of referenceTests) {
  await referenceTest.run();
  console.log(`PASS ${referenceTest.name}`);
}
