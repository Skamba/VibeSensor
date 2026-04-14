import { createUiPreactMount } from "../runtime/ui_preact_mount";
import type {
  SpectrumBandLegendModel,
  SpectrumPanelHeaderModel,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "../runtime/spectrum_panel_view";

type SpectrumLegendHandlers = {
  onReset: () => void;
  onSelect: (entryId: string) => void;
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

function SpectrumPanel(props: { state: SpectrumPanelBridgeState }) {
  const { state } = props;

  return (
    <>
      <div class="card__header">
        <div class="card__title" data-i18n="chart.spectrum_title">
          {state.header.titleText}
        </div>
      </div>
      <div id="specChartWrap" class="spectrum-wrap">
        <div id="specChart" />
        <div id="spectrumOverlay" class="empty-state" hidden={state.overlayMessage === null}>
          {state.overlayMessage ?? "Waiting for sensor data..."}
        </div>
      </div>
      <div class="spectrum-controls-panel">
        <div class="spectrum-toolbar">
          <div class="card__subtle spectrum-toolbar__hint" data-i18n="spectrum.controls_hint">
            {state.header.hintText}
          </div>
          <div class="spectrum-toolbar__bands">
            <button
              id="spectrumBandToggle"
              class="btn spectrum-toolbar__toggle"
              type="button"
              aria-controls="bandLegend"
              aria-pressed={state.bandToggle.hasBands && state.bandToggle.bandsVisible ? "true" : "false"}
              aria-expanded={state.bandToggle.hasBands && state.bandToggle.bandsVisible ? "true" : "false"}
              hidden={!state.bandToggle.hasBands}
              disabled={!state.bandToggle.hasBands}
              onClick={() => state.onBandToggle?.()}
            >
              {state.bandToggle.text}
            </button>
            <div id="bandLegend" class="legend band-legend" hidden={!state.bandLegend.visible}>
              {state.bandLegend.visible
                ? state.bandLegend.items.length
                  ? state.bandLegend.items.map((item) => (
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
                      {state.bandLegend.emptyText}
                    </div>
                  )
                : null}
            </div>
          </div>
        </div>
        <div id="spectrumInspector" class="spectrum-inspector" aria-live="polite">
          {state.inspectorText}
        </div>
        <div id="legend" class="legend">
          {state.sensorLegend && state.sensorLegend.items.length > 0 && state.sensorLegendHandlers
            ? (
              <>
                <button
                  type="button"
                  class="legend-item legend-item--interactive legend-item--reset"
                  aria-pressed={state.sensorLegend.reset.ariaPressed ? "true" : "false"}
                  title={state.sensorLegend.reset.titleText}
                  aria-label={state.sensorLegend.reset.ariaLabel}
                  data-legend-state={state.sensorLegend.reset.active ? "active" : undefined}
                  onClick={() => state.sensorLegendHandlers?.onReset()}
                >
                  <span class="legend-item__label">{state.sensorLegend.reset.labelText}</span>
                </button>
                {state.sensorLegend.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    class="legend-item legend-item--interactive"
                    aria-pressed={item.ariaPressed ? "true" : "false"}
                    title={item.titleText}
                    aria-label={item.ariaLabel}
                    data-legend-state={item.active ? "active" : item.muted ? "muted" : undefined}
                    onClick={() => state.sensorLegendHandlers?.onSelect(item.id)}
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
  const mount = createUiPreactMount(host);
  let state: SpectrumPanelBridgeState = { ...DEFAULT_PANEL_STATE };

  function render(): void {
    mount.render(<SpectrumPanel state={state} />);
  }

  render();

  return {
    bindBandToggle(onToggle: () => void): void {
      state = { ...state, onBandToggle: onToggle };
      render();
    },
    renderHeader(model: SpectrumPanelHeaderModel): void {
      state = { ...state, header: model };
      render();
    },
    renderOverlay(message: string | null): void {
      state = { ...state, overlayMessage: message };
      render();
    },
    renderBandToggle(model: { hasBands: boolean; bandsVisible: boolean; text: string }): void {
      state = { ...state, bandToggle: model };
      render();
    },
    renderSensorLegend(
      model: SpectrumSensorLegendModel | null,
      handlers?: SpectrumLegendHandlers,
    ): void {
      state = {
        ...state,
        sensorLegend: model,
        sensorLegendHandlers: model && handlers ? handlers : null,
      };
      render();
    },
    renderBandLegend(model: SpectrumBandLegendModel): void {
      state = { ...state, bandLegend: model };
      render();
    },
    renderInspectorText(text: string): void {
      state = { ...state, inspectorText: text };
      render();
    },
  };
}
