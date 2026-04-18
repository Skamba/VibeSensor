import type { JSX } from "preact";
import { memo } from "preact/compat";
import { getUiText } from "../ui_i18n";
import {
  signal,
  useComputed,
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { createDeferredModelSignal, useDeferredModel } from "./view_model_binding";
import type {
  SpectrumBandLegendModel,
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

const DEFAULT_SPECTRUM_BAND_TOGGLE_MODEL: SpectrumPanelBandToggleModel = {
  disabled: true,
  hasBands: false,
  bandsVisible: false,
  hidden: true,
  pressed: "false",
  text: "Show reference bands",
};
const DEFAULT_SPECTRUM_OVERLAY_MODEL: SpectrumPanelOverlayModel = {
  hidden: true,
  text: "Waiting for sensor data...",
};
const DEFAULT_SPECTRUM_BAND_LEGEND_MODEL: SpectrumBandLegendModel = {
  visible: false,
  items: [],
  emptyText: "No reference band",
};
const EMPTY_SPECTRUM_SENSOR_LEGEND_ITEMS: SpectrumSensorLegendModel["items"] = [];
type SpectrumCssVariableStyle = JSX.CSSProperties & {
  "--band-color"?: string;
  "--swatch-color"?: string;
};

function bandColorStyle(color: string): SpectrumCssVariableStyle {
  return { "--band-color": color };
}

function swatchColorStyle(color: string): SpectrumCssVariableStyle {
  return { "--swatch-color": color };
}

const SPECTRUM_BAND_TOGGLE_KEYS = [
  "bandsVisible",
  "disabled",
  "hasBands",
  "hidden",
  "pressed",
  "text",
] as const;
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

const SpectrumBandLegend = memo(function SpectrumBandLegend(props: {
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
              style={bandColorStyle(item.color)}
            >
              <span class="swatch" style={swatchColorStyle(item.color)} />
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
});

const SpectrumSensorLegend = memo(function SpectrumSensorLegend(props: {
  sensorLegend: ReadonlySignal<SpectrumSensorLegendModel | null>;
  sensorLegendHandlers: ReadonlySignal<SpectrumLegendHandlers | null>;
}) {
  const hasLegend = useComputed(() => {
    const legend = props.sensorLegend.value;
    return (
      legend !== null
      && legend.items.length > 0
      && props.sensorLegendHandlers.value !== null
    );
  });

  return (
    hasLegend.value
      ? (
        <SpectrumSensorLegendContent
          sensorLegend={props.sensorLegend}
          sensorLegendHandlers={props.sensorLegendHandlers}
        />
      )
      : null
  );
});

const SpectrumSensorLegendContent = memo(function SpectrumSensorLegendContent(
  props: {
    sensorLegend: ReadonlySignal<SpectrumSensorLegendModel | null>;
    sensorLegendHandlers: ReadonlySignal<SpectrumLegendHandlers | null>;
  },
) {
  const items = useComputed(
    () => props.sensorLegend.value?.items ?? EMPTY_SPECTRUM_SENSOR_LEGEND_ITEMS,
  );
  const reset = useComputed(() => props.sensorLegend.value?.reset ?? null);

  return (
    reset.value !== null && props.sensorLegendHandlers.value !== null
      ? (
        <>
          <button
            type="button"
            class="legend-item legend-item--interactive legend-item--reset"
            aria-pressed={reset.value.ariaPressed ? "true" : "false"}
            title={reset.value.titleText}
            aria-label={reset.value.ariaLabel}
            data-legend-state={reset.value.active ? "active" : undefined}
            onClick={() => props.sensorLegendHandlers.peek()?.onReset()}
          >
            <span class="legend-item__label">{reset.value.labelText}</span>
          </button>
          {items.value.map((item) => (
            <button
              key={item.id}
              type="button"
              class="legend-item legend-item--interactive"
              aria-pressed={item.ariaPressed ? "true" : "false"}
              title={item.titleText}
              aria-label={item.ariaLabel}
              data-legend-state={item.active ? "active" : item.muted ? "muted" : undefined}
              onClick={() => props.sensorLegendHandlers.peek()?.onSelect(item.id)}
            >
              <span class="swatch" style={swatchColorStyle(item.color)} />
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
      : null
  );
});

type SpectrumPanelProps = {
  bandLegendModel: ReadonlySignal<ReadonlySignal<SpectrumBandLegendModel> | null>;
  bandToggleModel: ReadonlySignal<ReadonlySignal<SpectrumPanelBandToggleModel> | null>;
  chartDom: MutableSpectrumPanelChartDom;
  header: ReadonlySignal<SpectrumPanelHeaderModel>;
  inspectorText: ReadonlySignal<string>;
  onBandToggle: ReadonlySignal<(() => void) | null>;
  overlayModel: ReadonlySignal<SpectrumPanelOverlayModel>;
  sensorLegendHandlersModel: ReadonlySignal<ReadonlySignal<SpectrumLegendHandlers | null> | null>;
  sensorLegendModel: ReadonlySignal<ReadonlySignal<SpectrumSensorLegendModel | null> | null>;
};

function SpectrumPanel(props: SpectrumPanelProps) {
  const { chartDom } = props;
  const bandLegend = useDeferredModel(props.bandLegendModel, DEFAULT_SPECTRUM_BAND_LEGEND_MODEL);
  const bandToggle = useDeferredModel(props.bandToggleModel, DEFAULT_SPECTRUM_BAND_TOGGLE_MODEL);
  const overlayModel = useComputed(() => props.overlayModel.value ?? DEFAULT_SPECTRUM_OVERLAY_MODEL);
  const sensorLegend = useDeferredModel(props.sensorLegendModel, null);
  const sensorLegendHandlers = useDeferredModel(props.sensorLegendHandlersModel, null);
  const titleText = useComputed(() => getUiText("chart.spectrum_title", props.header.value.titleText));
  const hintText = useComputed(() => getUiText("spectrum.controls_hint", props.header.value.hintText));
  const {
    disabled: bandToggleDisabled,
    hidden: bandToggleHidden,
    pressed: bandTogglePressed,
    text: bandToggleText,
  } = useSignalProperties(bandToggle, SPECTRUM_BAND_TOGGLE_KEYS);

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
        <div id="spectrumOverlay" class="empty-state" hidden={overlayModel.value.hidden}>
          {overlayModel.value.text}
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
              disabled={bandToggleDisabled}
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
      renderInspectorText(text: string): void {
        inspectorText.value = text;
      },
    },
  };
}

export function SpectrumPanelHost(props: {
  panel: CreatedSpectrumPanel;
}) {
  return (
    <div id="spectrumPanelRoot">
      <SpectrumPanel {...props.panel.props} />
    </div>
  );
}
