import {
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import { createDeferredModelSignal } from "./view_model_binding";
import type {
  SpectrumBandLegendModel,
  SpectrumInspectorRenderModel,
  SpectrumLegendHandlers,
  SpectrumPanelBandToggleModel,
  SpectrumPanelChartDom,
  SpectrumPanelHeaderModel,
  SpectrumPanelOverlayModel,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "../runtime/spectrum_panel_view";

type MutableSpectrumPanelChartDom = {
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement | null;
};

const DEFAULT_SPECTRUM_OVERLAY_MODEL: SpectrumPanelOverlayModel = {
  hidden: true,
  text: "Waiting for sensor data...",
};

function requireSpectrumElement<T extends HTMLElement>(
  element: T | null,
  target: string,
): T {
  if (element !== null) {
    return element;
  }
  throw new Error(`Spectrum UI requires ${target}`);
}

type SpectrumPanelProps = {
  bandLegendModel: ReadonlySignal<ReadonlySignal<SpectrumBandLegendModel> | null>;
  bandToggleModel: ReadonlySignal<ReadonlySignal<SpectrumPanelBandToggleModel> | null>;
  chartDom: MutableSpectrumPanelChartDom;
  header: ReadonlySignal<SpectrumPanelHeaderModel>;
  inspectorAnnouncement: ReadonlySignal<string>;
  inspectorText: ReadonlySignal<string>;
  onBandToggle: ReadonlySignal<(() => void) | null>;
  overlayModel: ReadonlySignal<SpectrumPanelOverlayModel>;
  sensorLegendHandlersModel: ReadonlySignal<ReadonlySignal<SpectrumLegendHandlers | null> | null>;
  sensorLegendModel: ReadonlySignal<ReadonlySignal<SpectrumSensorLegendModel | null> | null>;
};

export interface CreatedSpectrumPanel {
  props: SpectrumPanelProps;
  view: SpectrumPanelView;
}

export function createSpectrumPanel(): CreatedSpectrumPanel {
  const header = signal<SpectrumPanelHeaderModel>({
    titleText: "Multi-Sensor Blended Spectrum",
    hintText: "Use the trace chips to isolate one sensor at a time. Turn on reference bands when you need order context.",
  });
  const overlayModel = signal<SpectrumPanelOverlayModel>(DEFAULT_SPECTRUM_OVERLAY_MODEL);
  const bandToggleModel = createDeferredModelSignal<SpectrumPanelBandToggleModel>();
  const sensorLegendModel = createDeferredModelSignal<SpectrumSensorLegendModel | null>();
  const sensorLegendHandlersModel = createDeferredModelSignal<SpectrumLegendHandlers | null>();
  const bandLegendModel = createDeferredModelSignal<SpectrumBandLegendModel>();
  const inspectorAnnouncement = signal("");
  const inspectorText = signal("Use the trace chips or hover the chart to inspect the current peak.");
  const onBandToggle = signal<(() => void) | null>(null);
  const chartDom: MutableSpectrumPanelChartDom = {
    specChartWrap: null,
    specChart: null,
  };
  return {
    props: {
      bandLegendModel,
      bandToggleModel,
      chartDom,
      header,
      inspectorAnnouncement,
      inspectorText,
      onBandToggle,
      overlayModel,
      sensorLegendHandlersModel,
      sensorLegendModel,
    },
    view: {
      chartDom: {
        get specChartWrap(): HTMLElement {
          return requireSpectrumElement(chartDom.specChartWrap, "#specChartWrap");
        },
        get specChart(): HTMLElement {
          return requireSpectrumElement(chartDom.specChart, "#specChart");
        },
      } satisfies SpectrumPanelChartDom,
      bindBandToggle(onToggle: () => void): void {
        onBandToggle.value = onToggle;
      },
      bindBandToggleModel(model: ReadonlySignal<SpectrumPanelBandToggleModel>): void {
        bandToggleModel.value = model;
      },
      bindSensorLegendModel(
        model: ReadonlySignal<SpectrumSensorLegendModel | null>,
        handlers: ReadonlySignal<SpectrumLegendHandlers | null>,
      ): void {
        sensorLegendModel.value = model;
        sensorLegendHandlersModel.value = handlers;
      },
      bindBandLegendModel(model: ReadonlySignal<SpectrumBandLegendModel>): void {
        bandLegendModel.value = model;
      },
      renderHeader(model: SpectrumPanelHeaderModel): void {
        header.value = model;
      },
      renderOverlay(model: SpectrumPanelOverlayModel): void {
        overlayModel.value = model;
      },
      renderInspector(model: SpectrumInspectorRenderModel): void {
        inspectorText.value = model.text;
        if (model.announce) {
          inspectorAnnouncement.value = model.text;
        }
      },
    },
  };
}
