import type { CSSProperties } from "preact";
import { useEffect, useRef } from "preact/hooks";

import { t } from "../../i18n";
import {
  activeBands,
  bandCoverage,
  bandsVisible,
  hasBands,
  inspector,
  legend,
  mountSpectrum,
  overlay,
  selectTrace,
  showAllTraces,
  toggleBands,
} from "./spectrum_store";

const colorVar = (name: "--band-color" | "--swatch-color", color: string) =>
  ({ [name]: color }) as CSSProperties;

function BandLegend() {
  const visible = bandsVisible.value;
  const bands = activeBands.value;
  return (
    <div id="bandLegend" class="legend band-legend" hidden={!visible}>
      {!visible ? null : bands.length ? (
        bands.map((band) => (
          <div
            key={band.label}
            class="legend-item legend-item--band"
            data-band-state="active"
            data-heard={band.heardAt ? "true" : undefined}
            style={colorVar("--band-color", band.color)}
          >
            <span
              class="swatch"
              style={colorVar("--swatch-color", band.color)}
            />
            <span>{band.label}</span>
          </div>
        ))
      ) : (
        <div class="legend-item legend-item--band" data-band-state="empty">
          {t("spectrum.bands.none")}
        </div>
      )}
    </div>
  );
}

/** The order families the bands cover, greyed with what each still needs. */
function BandStatusLine() {
  const { message, families } = bandCoverage.value;
  if (message === null && families.length === 0) {
    return null;
  }
  return (
    <div id="bandStatus" class="band-status">
      {message ? <div class="band-status__message">{message}</div> : null}
      {families.length ? (
        <ul class="band-status__families">
          {families.map((family) => (
            <li
              key={family.key}
              class="band-status__family"
              data-band-family={family.key}
              data-band-family-state={family.state}
            >
              <span class="band-status__family-label">{family.label}</span>
              {family.note ? (
                <span class="band-status__family-note">{family.note}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function TraceLegend() {
  const model = legend.value;
  if (!model) {
    return null;
  }
  return (
    <>
      <button
        type="button"
        class="legend-item legend-item--interactive legend-item--reset"
        aria-pressed={model.allActive ? "true" : "false"}
        title={t("spectrum.legend.clear_focus")}
        aria-label={model.resetAriaLabel}
        data-legend-state={model.allActive ? "active" : undefined}
        onClick={showAllTraces}
      >
        <span class="legend-item__label">
          {t("spectrum.legend.all_series")}
        </span>
      </button>
      {model.items.map((item) => (
        <button
          key={item.id}
          type="button"
          class="legend-item legend-item--interactive"
          aria-pressed={item.state === "active" ? "true" : "false"}
          title={item.title}
          aria-label={item.ariaLabel}
          data-legend-state={item.state}
          onClick={() => selectTrace(item.id)}
        >
          <span class="swatch" style={colorVar("--swatch-color", item.color)} />
          <span class="legend-item__text-group">
            <span class="legend-item__label">{item.label}</span>
            <span class="legend-item__meta">{item.detail}</span>
          </span>
        </button>
      ))}
    </>
  );
}

/** The live multi-sensor spectrum with trace focus and order reference bands. */
export function Spectrum() {
  const chart = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chart.current || !wrap.current) {
      return;
    }
    return mountSpectrum({
      specChart: chart.current,
      specChartWrap: wrap.current,
    });
  }, []);
  const overlayText = overlay.value;
  const pressed = bandsVisible.value ? "true" : "false";
  return (
    <div id="spectrumPanelRoot">
      <div class="card__header">
        <div class="card__title">{t("chart.spectrum_title")}</div>
      </div>
      <div id="specChartWrap" class="spectrum-wrap" ref={wrap}>
        <div id="specChart" ref={chart} />
        <div
          id="spectrumOverlay"
          class="empty-state"
          hidden={overlayText === null}
        >
          {overlayText ?? ""}
        </div>
      </div>
      <div class="spectrum-controls-panel">
        <div class="spectrum-toolbar">
          <div class="card__subtle spectrum-toolbar__hint">
            {t("spectrum.controls_hint")}
          </div>
          <div class="spectrum-toolbar__bands">
            <button
              id="spectrumBandToggle"
              class="btn spectrum-toolbar__toggle"
              type="button"
              aria-controls="bandLegend"
              aria-pressed={pressed}
              aria-expanded={pressed}
              hidden={!hasBands.value}
              disabled={!hasBands.value}
              onClick={toggleBands}
            >
              {t(
                bandsVisible.value
                  ? "spectrum.bands.hide"
                  : "spectrum.bands.show",
              )}
            </button>
            <BandLegend />
          </div>
          <BandStatusLine />
        </div>
        <div id="spectrumInspector" class="spectrum-inspector">
          {inspector.value}
        </div>
        <div id="legend" class="legend">
          <TraceLegend />
        </div>
      </div>
    </div>
  );
}
