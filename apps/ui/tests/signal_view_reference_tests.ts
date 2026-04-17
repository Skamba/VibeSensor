import assert from "node:assert/strict";

import { computed, effect, effectOnChange, signal, useSignalProperties } from "../src/app/ui_signals";
import type {
  RealtimeLiveOverviewBridge,
  RealtimeLiveOverviewRenderModel,
  RealtimeLiveOverviewSensorCardModel,
} from "../src/app/views/realtime_live_overview";
import { mountSignalView } from "./dom_render_test_support";

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runDirectSignalBindingReferenceTest(): Promise<void> {
  const buttonText = signal("Idle");
  const variant = signal("muted");
  const disabled = signal(true);
  let renderCount = 0;

  const harness = await mountSignalView(async () => {
    const { h, render } = await import("preact");
    return (host) => {
      function SignalButton() {
        renderCount += 1;
        return h(
          "button",
          {
            "data-variant": variant,
            disabled,
            id: "signalBindingButton",
            type: "button",
          },
          buttonText,
        );
      }

      render(h(SignalButton, {}), host);
      return {};
    };
  });

  try {
    await harness.flush();

    const button = requireElement<HTMLButtonElement>(harness.host, "#signalBindingButton");
    assert.equal(renderCount, 1);
    assert.equal(button.textContent, "Idle");
    assert.equal(button.getAttribute("data-variant"), "muted");
    assert.equal(button.disabled, true);

    buttonText.value = "Running";
    variant.value = "warn";
    disabled.value = false;
    await harness.flush();

    assert.equal(renderCount, 1);
    assert.equal(button.textContent, "Running");
    assert.equal(button.getAttribute("data-variant"), "warn");
    assert.equal(button.disabled, false);
  } finally {
    harness.cleanup();
  }
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
  const reboundConnectedSensorsText = signal("1 / 1");
  const reboundActiveCarText = signal("Support Van");
  const reboundActiveCarWarning = signal(false);
  const reboundRecordingStateText = signal("Paused");
  const reboundDataFreshnessText = signal("Buffered");
  const reboundStrongestSignalText = signal("54 dB");
  const reboundRunHealthText = signal("Paused");
  const reboundRunHealthVariant = signal<RealtimeLiveOverviewRenderModel["runHealth"]["variant"]>("muted");
  const reboundSensorCards = signal<RealtimeLiveOverviewSensorCardModel[]>([
    {
      connected: true,
      id: "rear-right",
      label: "Rear Right",
      statusText: "Online",
      strongest: false,
    },
  ]);

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
  const reboundModel = computed<RealtimeLiveOverviewRenderModel>(() => ({
    activeCar: {
      text: reboundActiveCarText.value,
      warning: reboundActiveCarWarning.value,
    },
    connectedSensorsText: reboundConnectedSensorsText.value,
    dataFreshnessText: reboundDataFreshnessText.value,
    recordingStateText: reboundRecordingStateText.value,
    runHealth: {
      hidden: false,
      text: reboundRunHealthText.value,
      variant: reboundRunHealthVariant.value,
    },
    sensorCards: reboundSensorCards.value,
    strongestSignalText: reboundStrongestSignalText.value,
  }));
  const harness = await mountSignalView(async () => {
    const { mountRealtimeLiveOverview } = await import("../src/app/views/realtime_live_overview");
    return mountRealtimeLiveOverview;
  }, (): RealtimeLiveOverviewBridge => ({
    model: signal(null),
    speedText: signal("--"),
  }));

  try {
    harness.view.model.value = model;
    harness.view.speedText.value = "43 km/h";
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

    harness.view.model.value = reboundModel;
    await harness.flush();

    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "1 / 1");
    assert.equal(requireElement(harness.host, "#liveRecordingState [data-value]").textContent, "Paused");
    assert.equal(requireElement(harness.host, "#liveDataFreshness [data-value]").textContent, "Buffered");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "54 dB");
    assert.equal(requireElement(harness.host, "#liveRunHealth").textContent, "Paused");
    assert.match(requireElement(harness.host, "#liveActiveCar [data-value]").textContent ?? "", /Support Van/);
    assert.match(harness.host.textContent ?? "", /Rear Right/);
    assert.doesNotMatch(harness.host.textContent ?? "", /Front Left/);

    connectedSensorsText.value = "9 / 9";
    strongestSignalText.value = "99 dB";
    await harness.flush();

    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "1 / 1");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "54 dB");

    reboundConnectedSensorsText.value = "2 / 2";
    reboundStrongestSignalText.value = "61 dB";
    await harness.flush();

    assert.equal(requireElement(harness.host, "#liveConnectedSensors [data-value]").textContent, "2 / 2");
    assert.equal(requireElement(harness.host, "#liveStrongestSignal [data-value]").textContent, "61 dB");
  } finally {
    harness.cleanup();
  }
}

async function runEffectOnChangeReferenceTest(): Promise<void> {
  const source = signal("idle");
  const observed: Array<[string, string]> = [];
  const dispose = effectOnChange(source, (value, previousValue) => {
    observed.push([previousValue, value]);
  });

  try {
    source.value = "idle";
    source.value = "running";
    source.value = "running";
    source.value = "done";

    assert.deepEqual(observed, [
      ["idle", "running"],
      ["running", "done"],
    ]);
  } finally {
    dispose();
  }
}

async function runSignalPropertiesHelperReferenceTest(): Promise<void> {
  const badgeText = signal("Idle");
  const hidden = signal(true);
  const tone = signal<"muted" | "ok">("muted");
  const model = computed(() => ({
    hidden: hidden.value,
    text: badgeText.value,
    tone: tone.value,
  }));
  let renderCount = 0;

  const harness = await mountSignalView(async () => {
    const { h, render } = await import("preact");
    return (host) => {
      function SignalPropertiesView() {
        renderCount += 1;
        const { hidden, text, tone } = useSignalProperties(model, ["hidden", "text", "tone"] as const);
        return h(
          "div",
          {},
          h(
            "span",
            {
              "data-variant": tone,
              hidden,
              id: "signalPropertiesBadge",
            },
            text,
          ),
        );
      }

      render(h(SignalPropertiesView, {}), host);
      return {};
    };
  });

  try {
    await harness.flush();

    const badge = requireElement<HTMLElement>(harness.host, "#signalPropertiesBadge");
    assert.equal(renderCount, 1);
    assert.equal(badge.textContent, "Idle");
    assert.equal(badge.getAttribute("data-variant"), "muted");
    assert.equal(badge.hidden, true);

    badgeText.value = "Ready";
    hidden.value = false;
    tone.value = "ok";
    await harness.flush();

    assert.equal(renderCount, 1);
    assert.equal(badge.textContent, "Ready");
    assert.equal(badge.getAttribute("data-variant"), "ok");
    assert.equal(badge.hidden, false);
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
    const shellView = harness.view.view;
    let initialized = false;
    const dispose = effect(() => {
      const tabId = shellView.activeTabId.value;
      if (!initialized) {
        initialized = true;
        return;
      }
      observedTabs.push(tabId);
    });

    assert.equal(shellView.activeTabId.value, "carTab");
    assert.deepEqual(observedTabs, []);

    shellView.activateTab("analysisTab");
    await harness.flush();

    assert.deepEqual(observedTabs, ["analysisTab"]);
    assert.equal(shellView.activeTabId.value, "analysisTab");
    assert.equal(
      requireElement(harness.host, '[data-settings-tab="analysisTab"]').getAttribute("aria-selected"),
      "true",
    );
    assert.equal(requireElement(harness.host, "#analysisTab").hidden, false);
    assert.equal(requireElement(harness.host, "#carTab").hidden, true);

    shellView.activateTab("analysisTab");
    await harness.flush();
    assert.deepEqual(observedTabs, ["analysisTab"]);

    dispose();
    shellView.activateTab("speedSourceTab");
    await harness.flush();
    assert.deepEqual(observedTabs, ["analysisTab"]);
  } finally {
    harness.cleanup();
  }
}

const referenceTests = [
  {
    name: "direct signal jsx bindings update without rerender",
    run: runDirectSignalBindingReferenceTest,
  },
  {
    name: "realtime live overview computed-driven output",
    run: runRealtimeLiveOverviewReferenceTest,
  },
  {
    name: "effectOnChange skips initial and unchanged values",
    run: runEffectOnChangeReferenceTest,
  },
  {
    name: "useSignalProperties returns direct binding signals",
    run: runSignalPropertiesHelperReferenceTest,
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
