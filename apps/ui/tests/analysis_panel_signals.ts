import assert from "node:assert/strict";

import { signal } from "../src/app/ui_signals";
import type {
  AnalysisPanelCarAvailability,
  AnalysisPanelFieldKey,
  AnalysisPanelRenderModel,
  AnalysisPanelView,
} from "../src/app/views/analysis_panel";
import { mountSignalView } from "./dom_render_test_support";

const ANALYSIS_FIELD_KEYS = [
  "wheel_bandwidth_pct",
  "driveshaft_bandwidth_pct",
  "engine_bandwidth_pct",
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
  "min_abs_band_hz",
  "max_band_half_width_pct",
] as const satisfies readonly AnalysisPanelFieldKey[];

function createAnalysisModel(wheelBandwidth: string): AnalysisPanelRenderModel {
  const fields = Object.fromEntries(
    ANALYSIS_FIELD_KEYS.map((key) => [
      key,
      {
        guidance: {
          error: null,
          lines:
            key === "wheel_bandwidth_pct"
              ? [{ label: "Current", value: `${wheelBandwidth}%` }]
              : [],
        },
        invalid: false,
        value: key === "wheel_bandwidth_pct" ? wheelBandwidth : "",
      },
    ]),
  ) as AnalysisPanelRenderModel["fields"];
  return {
    fields,
    saveFeedback: null,
  };
}

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runAnalysisPanelSignalBindingTest(): Promise<void> {
  const harness = await mountSignalView(async () => {
    const { mountAnalysisPanel } = await import("../src/app/views/analysis_panel");
    return mountAnalysisPanel;
  }, (): AnalysisPanelView => ({
    actions: signal(null),
    carAvailability: signal(null),
    model: signal(null),
    focusField() {},
    openGuidance() {},
  }));

  try {
    const firstAvailability = signal<AnalysisPanelCarAvailability>({
      hasActiveCar: false,
      isLoading: false,
    });
    const secondAvailability = signal<AnalysisPanelCarAvailability>({
      hasActiveCar: true,
      isLoading: false,
    });
    const firstModel = signal(createAnalysisModel("5"));
    const secondModel = signal(createAnalysisModel("11"));

    harness.view.carAvailability.value = firstAvailability;
    harness.view.model.value = firstModel;
    await harness.flush();

    const noCarMessage = requireElement<HTMLElement>(harness.host, "#analysisNoCarMessage");
    const saveButton = requireElement<HTMLButtonElement>(harness.host, "#saveAnalysisBtn");
    const wheelBandwidthGuidance = requireElement<HTMLElement>(harness.host, "#wheelBandwidthGuidance");

    assert.equal(noCarMessage.hidden, false);
    assert.equal(saveButton.disabled, true);
    assert.match(wheelBandwidthGuidance.textContent ?? "", /Current 5%/);

    firstAvailability.value = {
      hasActiveCar: true,
      isLoading: false,
    };
    firstModel.value = createAnalysisModel("8");
    await harness.flush();

    assert.equal(noCarMessage.hidden, true);
    assert.equal(saveButton.disabled, false);
    assert.match(wheelBandwidthGuidance.textContent ?? "", /Current 8%/);

    harness.view.carAvailability.value = secondAvailability;
    harness.view.model.value = secondModel;
    await harness.flush();

    assert.equal(noCarMessage.hidden, true);
    assert.equal(saveButton.disabled, false);
    assert.match(wheelBandwidthGuidance.textContent ?? "", /Current 11%/);

    firstAvailability.value = {
      hasActiveCar: false,
      isLoading: false,
    };
    firstModel.value = createAnalysisModel("13");
    await harness.flush();

    assert.equal(noCarMessage.hidden, true);
    assert.equal(saveButton.disabled, false);
    assert.match(wheelBandwidthGuidance.textContent ?? "", /Current 11%/);

    secondAvailability.value = {
      hasActiveCar: false,
      isLoading: false,
    };
    secondModel.value = createAnalysisModel("15");
    await harness.flush();

    assert.equal(noCarMessage.hidden, false);
    assert.equal(saveButton.disabled, true);
    assert.match(wheelBandwidthGuidance.textContent ?? "", /Current 15%/);
  } finally {
    harness.cleanup();
  }
}

await runAnalysisPanelSignalBindingTest();
console.log("PASS analysis panel signal bindings rebind without stale bridge state");
