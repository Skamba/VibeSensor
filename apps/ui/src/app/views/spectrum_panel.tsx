import { render } from "preact";
import { getUiText } from "../ui_i18n";
import {
  signal,
  useComputed,
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { createDeferredModelSignal } from "./view_model_binding";
import type {
  SpectrumBandLegendModel,
  SpectrumLegendHandlers,
  SpectrumPanelBandToggleModel,
  SpectrumPanelChartDom,
  SpectrumPanelHeaderModel,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "../runtime/spectrum_panel_view";

type MutableSpectrumPanelChartDom = {
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement | null;
};

const DEFAULT_SPECTRUM_BAND_TOGGLE_MODEL: SpectrumPanelBandToggleModel = {
  hasBands: false,
  bandsVisible: false,
  text: "Show reference bands",
};
const DEFAULT_SPECTRUM_BAND_LEGEND_MODEL: SpectrumBandLegendModel = {
  visible: false,
  items: [],
  emptyText: "No reference band",
};
const SPECTRUM_BAND_TOGGLE_KEYS = ["bandsVisible", "hasBands", "text"] as const;
const SPECTRUM_BAND_LEGEND_KEYS = ["emptyText", "items", "visible"] as const;

function requireSpectrumElement<T extends HTMLElement>(
  element: T | null,
  target: string,
): T {
  if (element !== null) {
    return element;
  }
  throw new Error(`Spectrum UI requires ${target}`);
}

function SpectrumBandLegend(props: {
  bandLegend: ReadonlySignal<SpectrumBandLegendModel>;
}) {
  const {
    emptyText,
    items,
    visible,
  } = useSignalProperties(props.bandLegend, SPECTRUM_BAND_LEGEND_KEYS);
  const hidden = useComputed(() => !visible.value);

  return (
    <div id="bandLegend" class="legend band-legend" hidden={hidden}>
      {visible.value
        ? items.value.length
          ? items.value.map((item) => (
            <div
              key={item.labelText}
              class="legend-item legend-item--band"
              data-band-state="active"
              style={`--band-color: ${item.color}`}
            >
              <span class="swatch" style={`--swatch-color: ${item.color}`} />
              <span>{item.labelText}</span>
            </div>
          ))
          : (
            <div class="legend-item legend-item--band" data-band-state="empty">
              {emptyText}
            </div>
          )
        : null}
    </div>
  );
}

function SpectrumSensorLegend(props: {
  sensorLegend: ReadonlySignal<SpectrumSensorLegendModel | null>;
  sensorLegendHandlers: ReadonlySignal<SpectrumLegendHandlers | null>;
}) {
  const hasLegend = useComputed(() => {
    const legend = props.sensorLegend.value;
    return legend !== null && legend.items.length > 0 && props.sensorLegendHandlers.value !== null;
  });
  if (!hasLegend.value) {
    return null;
  }

  const sensorLegend = props.sensorLegend.value;
  const sensorLegendHandlers = props.sensorLegendHandlers.value;
  if (sensorLegend === null || sensorLegendHandlers === null) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        class="legend-item legend-item--interactive legend-item--reset"
        aria-pressed={sensorLegend.reset.ariaPressed ? "true" : "false"}
        title={sensorLegend.reset.titleText}
        aria-label={sensorLegend.reset.ariaLabel}
        data-legend-state={sensorLegend.reset.active ? "active" : undefined}
        onClick={() => sensorLegendHandlers.onReset()}
      >
        <span class="legend-item__label">{sensorLegend.reset.labelText}</span>
      </button>
      {sensorLegend.items.map((item) => (
        <button
          key={item.id}
          type="button"
          class="legend-item legend-item--interactive"
          aria-pressed={item.ariaPressed ? "true" : "false"}
          title={item.titleText}
          aria-label={item.ariaLabel}
          data-legend-state={item.active ? "active" : item.muted ? "muted" : undefined}
          onClick={() => sensorLegendHandlers.onSelect(item.id)}
        >
          <span class="swatch" style={`--swatch-color: ${item.color}`} />
          <span class="legend-item__text-group">
            <span class="legend-item__label">{item.labelText}</span>
            {item.detailText
              ? <span class="legend-item__meta">{item.detailText}</span>
              : null}
          </span>
        </button>
      ))}
    </>
  );
}

function SpectrumPanel(props: {
  bandLegendModel: ReadonlySignal<ReadonlySignal<SpectrumBandLegendModel> | null>;
  bandToggleModel: ReadonlySignal<ReadonlySignal<SpectrumPanelBandToggleModel> | null>;
  chartDom: MutableSpectrumPanelChartDom;
  header: ReadonlySignal<SpectrumPanelHeaderModel>;
  inspectorText: ReadonlySignal<string>;
  onBandToggle: ReadonlySignal<(() => void) | null>;
  overlayMessage: ReadonlySignal<string | null>;
  sensorLegendHandlersModel: ReadonlySignal<ReadonlySignal<SpectrumLegendHandlers | null> | null>;
  sensorLegendModel: ReadonlySignal<ReadonlySignal<SpectrumSensorLegendModel | null> | null>;
}) {
  const { chartDom } = props;
  const bandLegend = useComputed(() => props.bandLegendModel.value?.value ?? DEFAULT_SPECTRUM_BAND_LEGEND_MODEL);
  const bandToggle = useComputed(() => props.bandToggleModel.value?.value ?? DEFAULT_SPECTRUM_BAND_TOGGLE_MODEL);
  const sensorLegend = useComputed(() => props.sensorLegendModel.value?.value ?? null);
  const sensorLegendHandlers = useComputed(() => props.sensorLegendHandlersModel.value?.value ?? null);
  const titleText = useComputed(() => getUiText("chart.spectrum_title", props.header.value.titleText));
  const hintText = useComputed(() => getUiText("spectrum.controls_hint", props.header.value.hintText));
  const overlayHidden = useComputed(() => props.overlayMessage.value === null);
  const overlayText = useComputed(() => props.overlayMessage.value ?? "Waiting for sensor data...");
  const {
    bandsVisible: bandToggleBandsVisible,
    hasBands: bandToggleHasBands,
    text: bandToggleText,
  } = useSignalProperties(bandToggle, SPECTRUM_BAND_TOGGLE_KEYS);
  const bandTogglePressed = useComputed(() =>
      bandToggleHasBands.value && bandToggleBandsVisible.value ? "true" : "false"
  );
  const bandToggleHidden = useComputed(() => !bandToggleHasBands.value);

  return (
    <>
      <div class="card__header">
        <div class="card__title">
          {titleText}
        </div>
      </div>
      <div
        id="specChartWrap"
        class="spectrum-wrap"
        ref={(element) => {
          chartDom.specChartWrap = element;
        }}
      >
        <div
          id="specChart"
          ref={(element) => {
            chartDom.specChart = element;
          }}
        />
        <div id="spectrumOverlay" class="empty-state" hidden={overlayHidden}>
          {overlayText}
        </div>
      </div>
      <div class="spectrum-controls-panel">
        <div class="spectrum-toolbar">
          <div class="card__subtle spectrum-toolbar__hint">
            {hintText}
          </div>
          <div class="spectrum-toolbar__bands">
            <button
              id="spectrumBandToggle"
              class="btn spectrum-toolbar__toggle"
              type="button"
              aria-controls="bandLegend"
              aria-pressed={bandTogglePressed}
              aria-expanded={bandTogglePressed}
              hidden={bandToggleHidden}
              disabled={bandToggleHidden}
              onClick={() => props.onBandToggle.peek()?.()}
            >
              {bandToggleText}
            </button>
            <SpectrumBandLegend bandLegend={bandLegend} />
          </div>
        </div>
        <div id="spectrumInspector" class="spectrum-inspector" aria-live="polite">
          {props.inspectorText}
        </div>
        <div id="legend" class="legend">
          <SpectrumSensorLegend
            sensorLegend={sensorLegend}
            sensorLegendHandlers={sensorLegendHandlers}
          />
        </div>
      </div>
    </>
  );
}

export function mountSpectrumPanel(host: HTMLElement): SpectrumPanelView {
  const header = signal<SpectrumPanelHeaderModel>({
    titleText: "Multi-Sensor Blended Spectrum",
    hintText: "Use the trace chips to isolate one sensor at a time. Turn on reference bands when you need order context.",
  });
  const overlayMessage = signal<string | null>(null);
  const bandToggleModel = createDeferredModelSignal<SpectrumPanelBandToggleModel>();
  const sensorLegendModel = createDeferredModelSignal<SpectrumSensorLegendModel | null>();
  const sensorLegendHandlersModel = createDeferredModelSignal<SpectrumLegendHandlers | null>();
  const bandLegendModel = createDeferredModelSignal<SpectrumBandLegendModel>();
  const inspectorText = signal("Use the trace chips or hover the chart to inspect the current peak.");
  const onBandToggle = signal<(() => void) | null>(null);
  const chartDom: MutableSpectrumPanelChartDom = {
    specChartWrap: null,
    specChart: null,
  };
  render(
    <SpectrumPanel
      bandLegendModel={bandLegendModel}
      bandToggleModel={bandToggleModel}
      chartDom={chartDom}
      header={header}
      inspectorText={inspectorText}
      onBandToggle={onBandToggle}
      overlayMessage={overlayMessage}
      sensorLegendHandlersModel={sensorLegendHandlersModel}
      sensorLegendModel={sensorLegendModel}
    />,
    host,
  );

  return {
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
    renderOverlay(message: string | null): void {
      overlayMessage.value = message;
    },
    renderInspectorText(text: string): void {
      inspectorText.value = text;
    },
  };
}
