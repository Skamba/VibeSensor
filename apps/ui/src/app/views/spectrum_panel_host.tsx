import type { JSX } from "preact";
import { memo } from "preact/compat";

import { getUiText } from "../ui_i18n";
import {
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { useDeferredModel } from "./view_model_binding";
import type {
  SpectrumBandLegendModel,
  SpectrumLegendHandlers,
  SpectrumPanelBandToggleModel,
  SpectrumPanelOverlayModel,
  SpectrumSensorLegendModel,
} from "../runtime/spectrum_panel_view";
import type { CreatedSpectrumPanel } from "./spectrum_panel";

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
const SPECTRUM_BAND_TOGGLE_KEYS = [
  "bandsVisible",
  "disabled",
  "hasBands",
  "hidden",
  "pressed",
  "text",
] as const;
const SPECTRUM_BAND_LEGEND_KEYS = ["emptyText", "items", "visible"] as const;
const SCREEN_READER_ONLY_STYLE = {
  border: "0",
  clip: "rect(0 0 0 0)",
  height: "1px",
  margin: "-1px",
  overflow: "hidden",
  padding: "0",
  position: "absolute",
  whiteSpace: "nowrap",
  width: "1px",
} as const satisfies JSX.CSSProperties;
type SpectrumCssVariableStyle = JSX.CSSProperties & {
  "--band-color"?: string;
  "--swatch-color"?: string;
};
type SpectrumPanelProps = CreatedSpectrumPanel["props"];

function bandColorStyle(color: string): SpectrumCssVariableStyle {
  return { "--band-color": color };
}

function swatchColorStyle(color: string): SpectrumCssVariableStyle {
  return { "--swatch-color": color };
}

const SpectrumBandLegend = memo(function SpectrumBandLegend(props: {
  bandLegend: ReadonlySignal<SpectrumBandLegendModel>;
}) {
  const {
    emptyText,
    items,
    visible,
  } = useSignalProperties(props.bandLegend, SPECTRUM_BAND_LEGEND_KEYS);
  const hidden = !visible.value;

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
  const legend = props.sensorLegend.value;
  const hasLegend = legend !== null
    && legend.items.length > 0
    && props.sensorLegendHandlers.value !== null;

  return (
    hasLegend
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
  const legend = props.sensorLegend.value;
  const items = legend?.items ?? EMPTY_SPECTRUM_SENSOR_LEGEND_ITEMS;
  const reset = legend?.reset ?? null;
  const handlers = props.sensorLegendHandlers.value;

  return (
    reset !== null && handlers !== null
      ? (
        <>
          <button
            type="button"
            class="legend-item legend-item--interactive legend-item--reset"
            aria-pressed={reset.ariaPressed ? "true" : "false"}
            title={reset.titleText}
            aria-label={reset.ariaLabel}
            data-legend-state={reset.active ? "active" : undefined}
            onClick={() => props.sensorLegendHandlers.peek()?.onReset()}
          >
            <span class="legend-item__label">{reset.labelText}</span>
          </button>
          {items.map((item) => (
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

function SpectrumPanel(props: SpectrumPanelProps) {
  const { chartDom } = props;
  const bandLegend = useDeferredModel(props.bandLegendModel, DEFAULT_SPECTRUM_BAND_LEGEND_MODEL);
  const bandToggle = useDeferredModel(props.bandToggleModel, DEFAULT_SPECTRUM_BAND_TOGGLE_MODEL);
  const overlayModel = props.overlayModel.value ?? DEFAULT_SPECTRUM_OVERLAY_MODEL;
  const sensorLegend = useDeferredModel(props.sensorLegendModel, null);
  const sensorLegendHandlers = useDeferredModel(props.sensorLegendHandlersModel, null);
  const titleText = getUiText("chart.spectrum_title", props.header.value.titleText);
  const hintText = getUiText("spectrum.controls_hint", props.header.value.hintText);
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
        <div id="spectrumOverlay" class="empty-state" hidden={overlayModel.hidden}>
          {overlayModel.text}
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
        <div id="spectrumInspector" class="spectrum-inspector">
          {props.inspectorText}
        </div>
        <div
          class="spectrum-inspector-announcer"
          aria-live="polite"
          aria-atomic="true"
          style={SCREEN_READER_ONLY_STYLE}
        >
          {props.inspectorAnnouncement}
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

export function SpectrumPanelHost(props: {
  panel: CreatedSpectrumPanel;
}) {
  return (
    <div id="spectrumPanelRoot">
      <SpectrumPanel {...props.panel.props} />
    </div>
  );
}
