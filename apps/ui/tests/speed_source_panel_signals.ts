import assert from "node:assert/strict";

import { signal } from "../src/app/ui_signals";
import { DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL } from "../src/app/views/speed_source_panel_defaults";
import type {
  SpeedSourceDiagnosticsRenderModel,
  SpeedSourcePanelView,
  SpeedSourcePanelRenderModel,
} from "../src/app/views/speed_source_panel";
import { mountSignalView } from "./dom_render_test_support";

function createSpeedSourcePanelModel(
  currentSourceText: string,
  diagnosticsShouldOpen: boolean,
): SpeedSourcePanelRenderModel {
  return {
    choiceCards: {
      gps: { badgeText: null, selected: true, state: null },
      manual: { badgeText: null, selected: false, state: null },
      obd2: { badgeText: null, selected: false, state: null },
    },
    diagnosticsShouldOpen,
    manualConfigVisible: false,
    manualSpeedFeedback: null,
    manualSpeedInputValue: "",
    obdConfigVisible: false,
    obdConfiguredDeviceText: "--",
    obdDevices: [],
    obdScanStatusText: "Scan to discover nearby Bluetooth OBD adapters.",
    obdSelectionInvalid: false,
    scanObdDevicesDisabled: false,
    saveFeedback: null,
    selectedMode: "gps",
    showGpsFallbackPanel: false,
    staleTimeoutFeedback: null,
    staleTimeoutInputValue: "10",
    summary: {
      currentSourceText,
      effectiveSpeedText: `${currentSourceText} effective`,
      fallbackActiveText: "Inactive",
    },
  };
}

function createDiagnosticsModel(stateText: string): SpeedSourceDiagnosticsRenderModel {
  return {
    gps: {
      ...DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL.gps,
      stateText,
    },
    obd: DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL.obd,
  };
}

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runSpeedSourcePanelSignalBindingTest(): Promise<void> {
  const harness = await mountSignalView(async () => {
    const { mountSpeedSourcePanel } = await import("../src/app/views/speed_source_panel");
    return mountSpeedSourcePanel;
  }, (): SpeedSourcePanelView => ({
    actions: signal(null),
    diagnostics: signal(null),
    model: signal(null),
    focusManualSpeedInput() {},
    focusScanObdDevices() {},
    focusStaleTimeoutInput() {},
    isObdConfigVisible() {
      return false;
    },
  }));

  try {
    const firstModel = signal(createSpeedSourcePanelModel("GPS primary", false));
    const secondModel = signal(createSpeedSourcePanelModel("OBD fallback", true));
    const firstDiagnostics = signal(createDiagnosticsModel("idle"));
    const secondDiagnostics = signal(createDiagnosticsModel("locked"));

    harness.view.model.value = firstModel;
    harness.view.diagnostics.value = firstDiagnostics;
    await harness.flush();

    const currentSource = requireElement<HTMLElement>(harness.host, "#speedSourceCurrentSource");
    const diagnosticsState = requireElement<HTMLElement>(harness.host, "#gpsStatusState");
    const diagnosticsDetails =
      requireElement<HTMLDetailsElement>(harness.host, "#speedSourceDiagnostics");

    assert.match(currentSource.textContent ?? "", /GPS primary/);
    assert.match(diagnosticsState.textContent ?? "", /idle/);
    assert.equal(diagnosticsDetails.hasAttribute("open"), false);

    firstModel.value = createSpeedSourcePanelModel("GPS updated", false);
    firstDiagnostics.value = createDiagnosticsModel("searching");
    await harness.flush();

    assert.match(currentSource.textContent ?? "", /GPS updated/);
    assert.match(diagnosticsState.textContent ?? "", /searching/);
    assert.equal(diagnosticsDetails.hasAttribute("open"), false);

    harness.view.model.value = secondModel;
    harness.view.diagnostics.value = secondDiagnostics;
    await harness.flush();

    assert.match(currentSource.textContent ?? "", /OBD fallback/);
    assert.match(diagnosticsState.textContent ?? "", /locked/);
    assert.equal(diagnosticsDetails.hasAttribute("open"), true);

    firstModel.value = createSpeedSourcePanelModel("stale first", false);
    firstDiagnostics.value = createDiagnosticsModel("stale");
    await harness.flush();

    assert.match(currentSource.textContent ?? "", /OBD fallback/);
    assert.match(diagnosticsState.textContent ?? "", /locked/);
    assert.equal(diagnosticsDetails.hasAttribute("open"), true);

    secondModel.value = createSpeedSourcePanelModel("OBD closed request", false);
    secondDiagnostics.value = createDiagnosticsModel("streaming");
    await harness.flush();

    assert.match(currentSource.textContent ?? "", /OBD closed request/);
    assert.match(diagnosticsState.textContent ?? "", /streaming/);
    assert.equal(diagnosticsDetails.hasAttribute("open"), true);
  } finally {
    harness.cleanup();
  }
}

await runSpeedSourcePanelSignalBindingTest();
console.log("PASS speed source panel signal bindings rebind without stale bridge state");
