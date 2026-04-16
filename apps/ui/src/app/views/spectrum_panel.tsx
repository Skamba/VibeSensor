import { render } from "preact";
import { getUiText } from "../ui_i18n";
import {
  signal,
  useComputed,
  type ReadonlySignal,
} from "../ui_signals";
import type {
  SpectrumBandLegendModel,
  SpectrumPanelChartDom,
  SpectrumPanelHeaderModel,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "../runtime/spectrum_panel_view";

type SpectrumLegendHandlers = {
  onReset: () => void;
  onSelect: (entryId: string) => void;
};

type MutableSpectrumPanelChartDom = {
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement | null;
};

type SpectrumPanelBridgeState = {
  header: SpectrumPanelHeaderModel;
  overlayMessage: string | null;
  bandToggle: {
    hasBands: boolean;
    bandsVisible: boolean;
    text: string;
  };
  sensorLegend: SpectrumSensorLegendModel | null;
  sensorLegendHandlers: SpectrumLegendHandlers | null;
  bandLegend: SpectrumBandLegendModel;
  inspectorText: string;
  onBandToggle: (() => void) | null;
};

const DEFAULT_PANEL_STATE: SpectrumPanelBridgeState = {
  header: {
    titleText: "Multi-Sensor Blended Spectrum",
    hintText: "Use the trace chips to isolate one sensor at a time. Turn on reference bands when you need order context.",
  },
  overlayMessage: null,
  bandToggle: {
    hasBands: false,
    bandsVisible: false,
    text: "Show reference bands",
  },
  sensorLegend: null,
  sensorLegendHandlers: null,
  bandLegend: {
    visible: false,
    items: [],
    emptyText: "No reference band",
  },
  inspectorText: "Use the trace chips or hover the chart to inspect the current peak.",
  onBandToggle: null,
};

function createDefaultPanelState(): SpectrumPanelBridgeState {
  return {
    header: { ...DEFAULT_PANEL_STATE.header },
    overlayMessage: DEFAULT_PANEL_STATE.overlayMessage,
    bandToggle: { ...DEFAULT_PANEL_STATE.bandToggle },
    sensorLegend: DEFAULT_PANEL_STATE.sensorLegend,
    sensorLegendHandlers: DEFAULT_PANEL_STATE.sensorLegendHandlers,
    bandLegend: { ...DEFAULT_PANEL_STATE.bandLegend, items: [...DEFAULT_PANEL_STATE.bandLegend.items] },
    inspectorText: DEFAULT_PANEL_STATE.inspectorText,
    onBandToggle: DEFAULT_PANEL_STATE.onBandToggle,
  };
}

function requireSpectrumElement<T extends HTMLElement>(
  element: T | null,
  target: string,
): T {
  if (element !== null) {
    return element;
  }
  throw new Error(`Spectrum UI requires ${target}`);
}

function SpectrumPanel(props: {
  bandLegend: ReadonlySignal<SpectrumBandLegendModel>;
  bandToggle: ReadonlySignal<SpectrumPanelBridgeState["bandToggle"]>;
  chartDom: MutableSpectrumPanelChartDom;
  header: ReadonlySignal<SpectrumPanelHeaderModel>;
  inspectorText: ReadonlySignal<string>;
  onBandToggle: ReadonlySignal<(() => void) | null>;
  overlayMessage: ReadonlySignal<string | null>;
  sensorLegend: ReadonlySignal<SpectrumSensorLegendModel | null>;
  sensorLegendHandlers: ReadonlySignal<SpectrumLegendHandlers | null>;
}) {
  const { chartDom } = props;
  const titleText = useComputed(() => getUiText("chart.spectrum_title", props.header.value.titleText));
  const hintText = useComputed(() => getUiText("spectrum.controls_hint", props.header.value.hintText));
  const overlayHidden = useComputed(() => props.overlayMessage.value === null);
  const overlayText = useComputed(() => props.overlayMessage.value ?? "Waiting for sensor data...");
  const bandToggleHasBands = useComputed(() => props.bandToggle.value.hasBands);
  const bandToggleBandsVisible = useComputed(() => props.bandToggle.value.bandsVisible);
  const bandTogglePressed = useComputed(() =>
    bandToggleHasBands.value && bandToggleBandsVisible.value ? "true" : "false"
  );
  const bandToggleText = useComputed(() => props.bandToggle.value.text);
  const bandToggleHidden = useComputed(() => !bandToggleHasBands.value);
  const bandLegendHidden = useComputed(() => !props.bandLegend.value.visible);
  const bandLegend = props.bandLegend.value;
  const sensorLegend = props.sensorLegend.value;
  const sensorLegendHandlers = props.sensorLegendHandlers.value;

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
              onClick={() => props.onBandToggle.value?.()}
            >
              {bandToggleText}
            </button>
            <div id="bandLegend" class="legend band-legend" hidden={bandLegendHidden}>
              {bandLegend.visible
                ? bandLegend.items.length
                  ? bandLegend.items.map((item) => (
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
                      {bandLegend.emptyText}
                    </div>
                  )
                : null}
            </div>
          </div>
        </div>
        <div id="spectrumInspector" class="spectrum-inspector" aria-live="polite">
          {props.inspectorText}
        </div>
        <div id="legend" class="legend">
          {sensorLegend && sensorLegend.items.length > 0 && sensorLegendHandlers
            ? (
              <>
                <button
                  type="button"
                  class="legend-item legend-item--interactive legend-item--reset"
                  aria-pressed={sensorLegend.reset.ariaPressed ? "true" : "false"}
                  title={sensorLegend.reset.titleText}
                  aria-label={sensorLegend.reset.ariaLabel}
                  data-legend-state={sensorLegend.reset.active ? "active" : undefined}
                  onClick={() => sensorLegendHandlers?.onReset()}
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
                    onClick={() => sensorLegendHandlers?.onSelect(item.id)}
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
            )
            : null}
        </div>
      </div>
    </>
  );
}

export function mountSpectrumPanel(host: HTMLElement): SpectrumPanelView {
  const defaultState = createDefaultPanelState();
  const header = signal<SpectrumPanelHeaderModel>(defaultState.header);
  const overlayMessage = signal<string | null>(defaultState.overlayMessage);
  const bandToggle = signal(defaultState.bandToggle);
  const sensorLegend = signal<SpectrumSensorLegendModel | null>(defaultState.sensorLegend);
  const sensorLegendHandlers = signal<SpectrumLegendHandlers | null>(defaultState.sensorLegendHandlers);
  const bandLegend = signal(defaultState.bandLegend);
  const inspectorText = signal(defaultState.inspectorText);
  const onBandToggle = signal<(() => void) | null>(defaultState.onBandToggle);
  const chartDom: MutableSpectrumPanelChartDom = {
    specChartWrap: null,
    specChart: null,
  };
  render(
    <SpectrumPanel
      bandLegend={bandLegend}
      bandToggle={bandToggle}
      chartDom={chartDom}
      header={header}
      inspectorText={inspectorText}
      onBandToggle={onBandToggle}
      overlayMessage={overlayMessage}
      sensorLegend={sensorLegend}
      sensorLegendHandlers={sensorLegendHandlers}
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
    renderHeader(model: SpectrumPanelHeaderModel): void {
      header.value = model;
    },
    renderOverlay(message: string | null): void {
      overlayMessage.value = message;
    },
    renderBandToggle(model: { hasBands: boolean; bandsVisible: boolean; text: string }): void {
      bandToggle.value = model;
    },
    renderSensorLegend(
      model: SpectrumSensorLegendModel | null,
      handlers?: SpectrumLegendHandlers,
    ): void {
      sensorLegend.value = model;
      sensorLegendHandlers.value = model && handlers ? handlers : null;
    },
    renderBandLegend(model: SpectrumBandLegendModel): void {
      bandLegend.value = model;
    },
    renderInspectorText(text: string): void {
      inspectorText.value = text;
    },
  };
}
