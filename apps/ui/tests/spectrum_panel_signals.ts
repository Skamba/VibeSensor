import assert from "node:assert/strict";

import { options } from "preact";

import type {
  SpectrumBandLegendModel,
  SpectrumPanelBandToggleModel,
  SpectrumSensorLegendModel,
} from "../src/app/runtime/spectrum_panel_view";
import { mountSignalView } from "./dom_render_test_support";

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runSpectrumPanelSignalProjectionTest(): Promise<void> {
  const previousDiffed = options.diffed;
  let spectrumPanelRenderCount = 0;
  options.diffed = (vnode) => {
    if (typeof vnode.type === "function" && vnode.type.name === "SpectrumPanel") {
      spectrumPanelRenderCount += 1;
    }
    previousDiffed?.(vnode);
  };

  const harness = await mountSignalView(async () => {
    const { mountSpectrumPanel } = await import("../src/app/views/spectrum_panel");
    return mountSpectrumPanel;
  });

  try {
    await harness.flush();
    assert.equal(spectrumPanelRenderCount, 1);

    const bandToggleModel: SpectrumPanelBandToggleModel = {
      bandsVisible: true,
      hasBands: true,
      text: "Hide reference bands",
    };
    harness.view.renderBandToggle(bandToggleModel);
    await harness.flush();

    const bandToggleBaseline = spectrumPanelRenderCount;
    assert.equal(requireElement<HTMLButtonElement>(harness.host, "#spectrumBandToggle").textContent, "Hide reference bands");

    const bandLegendModel: SpectrumBandLegendModel = {
      visible: true,
      items: [{ color: "#f59e0b", labelText: "Wheel 1x" }],
      emptyText: "No reference band",
    };
    harness.view.renderBandLegend(bandLegendModel);
    await harness.flush();

    assert.equal(spectrumPanelRenderCount, bandToggleBaseline);
    assert.match(requireElement(harness.host, "#bandLegend").textContent ?? "", /Wheel 1x/);

    let resetClicks = 0;
    const selectedIds: string[] = [];
    const sensorLegendModel: SpectrumSensorLegendModel = {
      reset: {
        labelText: "All sensor traces",
        titleText: "Show all traces",
        ariaLabel: "Show all sensor traces",
        ariaPressed: true,
        active: true,
      },
      items: [{
        id: "front-left",
        labelText: "Front Left",
        color: "#2563eb",
        detailText: "12.0 dB",
        titleText: "Focus Front Left",
        ariaLabel: "Focus Front Left",
        ariaPressed: false,
        active: false,
        muted: false,
      }],
    };
    harness.view.renderSensorLegend(sensorLegendModel, {
      onReset: () => {
        resetClicks += 1;
      },
      onSelect: (entryId) => {
        selectedIds.push(entryId);
      },
    });
    await harness.flush();

    assert.equal(spectrumPanelRenderCount, bandToggleBaseline);
    assert.match(requireElement(harness.host, "#legend").textContent ?? "", /Front Left/);
    assert.match(requireElement(harness.host, "#legend").textContent ?? "", /12.0 dB/);

    requireElement<HTMLButtonElement>(harness.host, ".legend-item--reset").click();
    requireElement<HTMLButtonElement>(harness.host, '[aria-label="Focus Front Left"]').click();
    assert.equal(resetClicks, 1);
    assert.deepEqual(selectedIds, ["front-left"]);

    harness.view.renderSensorLegend({
      ...sensorLegendModel,
      items: [{
        ...sensorLegendModel.items[0],
        detailText: "13.0 dB",
        active: true,
        ariaPressed: true,
      }],
    }, {
      onReset: () => {
        resetClicks += 1;
      },
      onSelect: (entryId) => {
        selectedIds.push(entryId);
      },
    });
    await harness.flush();

    assert.equal(spectrumPanelRenderCount, bandToggleBaseline);
    assert.match(requireElement(harness.host, "#legend").textContent ?? "", /13.0 dB/);
  } finally {
    options.diffed = previousDiffed;
    harness.cleanup();
  }
}

await runSpectrumPanelSignalProjectionTest();
console.log("PASS spectrum panel legend signal projections avoid rerender");
