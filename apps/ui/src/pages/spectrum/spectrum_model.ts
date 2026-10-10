import type { FuelType } from "../../capabilities";
import { fmt, formatMg } from "../../format";
import { spectrumDbToMg } from "../../spectrum";
import { orderBandFills } from "../../theme";
import type { RotationalSpeeds } from "../../transport/live_models";
import type { WsUiState } from "../../ws";

/** Pure models for the live spectrum: bands, legend, inspector, overlay. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

export type NumericSeries = readonly number[] | Float64Array;

export interface ChartBand {
  label: string;
  min_hz: number;
  max_hz: number;
  color: string;
}

export interface SeriesEntry {
  id: string;
  label: string;
  color: string;
  values: NumericSeries;
}

export interface FocusMarker {
  color: string;
  freq: number;
  value: number;
}

/** What the spectrum knows about each sensor's level and strongest peak. */
export interface SensorLevels {
  strengthDb(id: string): number | null;
  /** The strongest peak in mg on the report's scale; ranks the sensors as the report does. */
  peakMg(id: string): number | null;
  topPeakHz(id: string): number | null;
}

const FREQ_MATCH_EPSILON = 1e-6;

export function closestFrequencyIndex(
  freqAxis: NumericSeries,
  targetHz: number,
): number | null {
  if (!freqAxis.length || !Number.isFinite(targetHz)) {
    return null;
  }
  let best = 0;
  for (let index = 1; index < freqAxis.length; index += 1) {
    if (
      Math.abs(freqAxis[index] - targetHz) < Math.abs(freqAxis[best] - targetHz)
    ) {
      best = index;
    }
  }
  return best;
}

export function freqGridsMatch(
  left: NumericSeries,
  right: NumericSeries,
  len: number,
): boolean {
  for (let index = 0; index < len; index += 1) {
    if (Math.abs(left[index] - right[index]) > FREQ_MATCH_EPSILON) {
      return false;
    }
  }
  return true;
}

export const formatHz = (value: number) => fmt(value, value >= 100 ? 0 : 1);
/** A sensor's strength, dB above its noise floor, as the overview and report show it. */
const formatDbAboveFloor = (value: number) => fmt(value, 0);
/** A chart bin's amplitude (dB re 0.1 mg) in mg. */
const formatBinMg = (db: number) => formatMg(spectrumDbToMg(db));
const isFiniteNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

const BAND_STYLE: Record<string, { color: string; name: string }> = {
  wheel_1x: { color: orderBandFills.wheel1, name: "bands.wheel_1x" },
  wheel_2x: { color: orderBandFills.wheel2, name: "bands.wheel_2x" },
  driveshaft_1x: {
    color: orderBandFills.driveshaft1,
    name: "bands.driveshaft_1x",
  },
  engine_1x: { color: orderBandFills.engine1, name: "bands.engine_1x" },
  engine_2x: { color: orderBandFills.engine2, name: "bands.engine_2x" },
  driveshaft_engine_1x: {
    color: orderBandFills.driveshaftEngine1,
    name: "bands.driveshaft_engine_1x",
  },
};

/** An engine order's band: `engine_3x` is E3, `engine_1_5x` E1.5. */
const ENGINE_ORDER_KEY = /^engine_(\d+)(?:_(\d))?x$/;

/** Bands that follow engine RPM, labelled with how the RPM was obtained. */
function isEngineBand(key: string): boolean {
  return key === "driveshaft_engine_1x" || ENGINE_ORDER_KEY.test(key);
}

/** The name of a band the style table does not know: one of the engine's own orders. */
function engineOrderName(key: string, t: Translate): string | null {
  const match = ENGINE_ORDER_KEY.exec(key);
  if (!match) {
    return null;
  }
  const order = Number(match[1]) + Number(match[2] ?? 0) / 10;
  return t("bands.engine_order", {
    order: `${fmt(order, Number.isInteger(order) ? 0 : 1)}x`,
  });
}

/** "measured" with fresh OBD-II RPM, else "est., top gear" (estimated from speed). */
function engineBasis(speeds: RotationalSpeeds, t: Translate): string {
  return t(
    speeds.engine.mode === "measured"
      ? "bands.basis.measured"
      : "bands.basis.estimated_top_gear",
  );
}

/**
 * An EV's motor turns at the driveline order (wheel speed × reduction ratio),
 * so its driveline band is the motor's and it has no engine bands.
 */
const EV_BAND_NAME: Record<string, string> = {
  driveshaft_1x: "bands.motor_1x",
  driveshaft_engine_1x: "bands.motor_1x",
};

/** Order reference bands from the server's rotational speeds. */
export function orderBands(
  speeds: RotationalSpeeds | null,
  fuelType: FuelType,
  t: Translate,
): ChartBand[] {
  const electric = fuelType === "EV";
  const bands = speeds?.order_bands;
  if (!speeds || !Array.isArray(bands)) {
    return [];
  }
  const output: ChartBand[] = [];
  for (const band of bands) {
    const center = Number(band.center_hz);
    const tolerance = Number(band.tolerance);
    if (
      !Number.isFinite(center) ||
      center <= 0 ||
      !Number.isFinite(tolerance)
    ) {
      continue;
    }
    const style = BAND_STYLE[band.key];
    const engine = isEngineBand(band.key);
    // The report's workshop label (T1, P1, E2) leads, so both name an order alike.
    const coded = (label: string) =>
      t("bands.with_code", { code: band.code, band: label });
    if (electric) {
      if (engine && !EV_BAND_NAME[band.key]) {
        continue;
      }
      output.push({
        label: coded(t(EV_BAND_NAME[band.key] ?? style?.name ?? band.key)),
        min_hz: Math.max(0, center * (1 - tolerance)),
        max_hz: center * (1 + tolerance),
        color: style?.color ?? orderBandFills.wheel1,
      });
      continue;
    }
    const plain = style
      ? t(style.name)
      : (engineOrderName(band.key, t) ?? t(band.key));
    const name = band.firing ? t("bands.firing", { band: plain }) : plain;
    output.push({
      label: coded(
        engine
          ? t("bands.with_basis", { band: name, basis: engineBasis(speeds, t) })
          : name,
      ),
      min_hz: Math.max(0, center * (1 - tolerance)),
      max_hz: center * (1 + tolerance),
      color:
        style?.color ??
        (engine ? orderBandFills.engine2 : orderBandFills.wheel1),
    });
  }
  return output;
}

export type BandFamilyKey = "wheel" | "driveline" | "engine";

export interface BandFamily {
  key: BandFamilyKey;
  label: string;
  /** `on`: drawn; `missing`: a car reference is missing; `waiting`: no speed yet. */
  state: "on" | "missing" | "waiting";
  /** How the engine RPM is known, or what the family needs. */
  note: string | null;
}

export interface BandStatus {
  /** Why no bands are drawn at all, when that is the case. */
  message: string | null;
  families: BandFamily[];
}

const MISSING_REFERENCES = new Set([
  "missing_tire",
  "missing_final_drive",
  "missing_gear_ratio",
]);

/**
 * Which order families the live spectrum can draw, and what each one needs.
 * The spectrum itself always shows; only the bands need a car and a speed.
 * An EV has no engine family and its driveline family is its motor.
 */
export function bandStatus(
  input: {
    /** `false` once the cars have loaded and none is active. */
    carActive: boolean;
    fuelType: FuelType;
    speeds: RotationalSpeeds | null;
    speedMps: number | null;
    gpsReceiverMissing: boolean;
  },
  t: Translate,
): BandStatus {
  if (!input.carActive) {
    return { message: t("spectrum.bands.need_car"), families: [] };
  }
  const { speeds } = input;
  const electric = input.fuelType === "EV";
  const rows: Array<[BandFamilyKey, RotationalSpeeds["wheel"] | undefined]> = [
    ["wheel", speeds?.wheel],
    ["driveline", speeds?.driveshaft],
    ["engine", speeds?.engine],
  ];
  const families = rows
    .filter(([key]) => !(electric && key === "engine"))
    .map(([key, value]): BandFamily => {
      const label = t(
        electric && key === "driveline"
          ? "spectrum.bands.family.motor"
          : `spectrum.bands.family.${key}`,
      );
      if (value && value.rpm !== null) {
        return {
          key,
          label,
          state: "on",
          note: key === "engine" && speeds ? engineBasis(speeds, t) : null,
        };
      }
      const reason = value?.reason ?? "";
      return MISSING_REFERENCES.has(reason)
        ? {
            key,
            label,
            state: "missing",
            note: t(`spectrum.bands.needs.${key}.${reason}`),
          }
        : { key, label, state: "waiting", note: null };
    });
  if (!families.some((family) => family.state === "waiting")) {
    return { message: null, families };
  }
  const message =
    input.speedMps === 0
      ? t("spectrum.bands.need_motion")
      : input.gpsReceiverMissing
        ? `${t("spectrum.bands.need_speed")} ${t("speed.gps_no_receiver.title")}: ${t("speed.gps_no_receiver.body")}`
        : t("spectrum.bands.need_speed");
  return { message, families };
}

export function bandsAt(
  bands: readonly ChartBand[],
  freqHz: number,
): ChartBand[] {
  return bands.filter((band) => freqHz >= band.min_hz && freqHz <= band.max_hz);
}

/** The pinned trace, else the strongest one (the report's ranking: by mg). */
export function focusEntry(
  entries: readonly SeriesEntry[],
  pinnedId: string | null,
  levels: SensorLevels,
): SeriesEntry | null {
  const pinned = pinnedId
    ? entries.find((entry) => entry.id === pinnedId)
    : undefined;
  if (pinned) {
    return pinned;
  }
  let best: SeriesEntry | null = null;
  let bestMg = Number.NEGATIVE_INFINITY;
  for (const entry of entries) {
    const mg = levels.peakMg(entry.id);
    if (isFiniteNumber(mg) && mg > bestMg) {
      bestMg = mg;
      best = entry;
    }
  }
  return best;
}

/** The trace's value at its reported strongest peak, snapped to the grid. */
export function focusPeak(
  entry: SeriesEntry,
  freqAxis: NumericSeries,
  levels: SensorLevels,
): { freq: number; value: number } | null {
  const peakHz = levels.topPeakHz(entry.id);
  const index = isFiniteNumber(peakHz)
    ? closestFrequencyIndex(freqAxis, peakHz)
    : null;
  const value = index === null ? undefined : entry.values[index];
  if (index === null || !isFiniteNumber(value)) {
    return null;
  }
  return { freq: freqAxis[index] ?? (peakHz as number), value };
}

export interface InspectorInput {
  entries: readonly SeriesEntry[];
  freqAxis: NumericSeries;
  bands: readonly ChartBand[];
  pinnedId: string | null;
  cursorIdx: number | null;
  levels: SensorLevels;
}

/** Inspector line: hovered bin, else the focused trace's peak, else a hint. */
export function inspectorText(
  input: InspectorInput,
  t: Translate,
): { text: string; mode: "idle" | "hover" | "focus" } {
  const idle = { text: t("spectrum.inspector_idle"), mode: "idle" as const };
  const entry = focusEntry(input.entries, input.pinnedId, input.levels);
  if (!entry) {
    return idle;
  }
  // The order bands the frequency falls in, appended only when there are any.
  const withBands = (text: string, freq: number) => {
    const active = bandsAt(input.bands, freq);
    return active.length
      ? `${text} · ${active.map((band) => band.label).join(", ")}`
      : text;
  };
  const { cursorIdx, freqAxis } = input;
  if (cursorIdx !== null && cursorIdx >= 0 && cursorIdx < freqAxis.length) {
    const freq = freqAxis[cursorIdx];
    const value = entry.values[Math.min(cursorIdx, entry.values.length - 1)];
    return {
      mode: "hover",
      text: withBands(
        t("spectrum.inspector_hover", {
          sensor: entry.label,
          freq: formatHz(freq),
          value: isFiniteNumber(value) ? formatBinMg(value) : "--",
        }),
        freq,
      ),
    };
  }
  const peak = focusPeak(entry, freqAxis, input.levels);
  if (!peak) {
    return idle;
  }
  // The sensor's level as the overview and the report give it (mg, then dB
  // above its floor), not the peak bin's level on the chart.
  const strength = input.levels.strengthDb(entry.id);
  const mg = input.levels.peakMg(entry.id);
  return {
    mode: "focus",
    text: withBands(
      t(
        input.pinnedId
          ? "spectrum.inspector_focus_selected"
          : "spectrum.inspector_focus_strongest",
        {
          sensor: entry.label,
          freq: formatHz(peak.freq),
          mg: isFiniteNumber(mg) ? formatMg(mg) : "--",
          value: isFiniteNumber(strength) ? formatDbAboveFloor(strength) : "--",
        },
      ),
      peak.freq,
    ),
  };
}

/** The frequency the band legend describes: hovered bin, else the focus peak. */
export function activeFrequency(input: InspectorInput): number | null {
  const { cursorIdx, freqAxis } = input;
  if (cursorIdx !== null && cursorIdx >= 0 && cursorIdx < freqAxis.length) {
    return freqAxis[cursorIdx];
  }
  const entry = focusEntry(input.entries, input.pinnedId, input.levels);
  return entry
    ? (focusPeak(entry, freqAxis, input.levels)?.freq ?? null)
    : null;
}

export interface LegendItem {
  id: string;
  label: string;
  color: string;
  detail: string;
  title: string;
  ariaLabel: string;
  state: "active" | "muted" | undefined;
}

/** Trace chips: a reset chip plus one per sensor, with level and focus state. */
export function legendModel(
  entries: readonly SeriesEntry[],
  pinnedId: string | null,
  levels: SensorLevels,
  t: Translate,
): { allActive: boolean; resetAriaLabel: string; items: LegendItem[] } | null {
  if (!entries.length) {
    return null;
  }
  const allActive = pinnedId === null;
  const allLabel = t("spectrum.legend.all_series");
  return {
    allActive,
    resetAriaLabel: allActive
      ? `${allLabel}. ${t("spectrum.legend.state_all_visible")}`
      : allLabel,
    items: entries.map((entry) => {
      const active = pinnedId === entry.id;
      const muted = !allActive && !active;
      const stateText = t(
        `spectrum.legend.state_${active ? "isolated" : muted ? "inactive" : "visible"}`,
      );
      const db = levels.strengthDb(entry.id);
      const level = isFiniteNumber(db)
        ? t("spectrum.legend.sensor_level", { value: formatDbAboveFloor(db) })
        : null;
      return {
        id: entry.id,
        label: entry.label,
        color: entry.color,
        detail: level ?? stateText,
        title: active
          ? t("spectrum.legend.clear_focus")
          : t("spectrum.legend.focus_series", { sensor: entry.label }),
        ariaLabel: [entry.label, stateText, level].filter(Boolean).join(". "),
        state: active ? "active" : muted ? "muted" : undefined,
      };
    }),
  };
}

export interface OverlayInput {
  chartLoadError: string | null;
  prepareError: string | null;
  payloadError: string | null;
  hasReceivedPayload: boolean;
  wsState: WsUiState;
  chartLoading: boolean;
  hasData: boolean;
}

/** Why the chart is empty or not trustworthy right now, or null to hide. */
export function overlayMessage(
  input: OverlayInput,
  t: Translate,
): string | null {
  if (input.chartLoadError) {
    return t("spectrum.chart_load_error", { message: input.chartLoadError });
  }
  if (input.prepareError) {
    return t("spectrum.frame_prepare_error", { message: input.prepareError });
  }
  if (input.payloadError) {
    return input.payloadError;
  }
  if (input.wsState === "connecting" && !input.hasReceivedPayload) {
    return t("spectrum.loading");
  }
  if (input.wsState === "connecting" || input.wsState === "reconnecting") {
    return t("ws.connecting");
  }
  if (input.wsState === "stale") {
    return t("spectrum.stale");
  }
  if (input.chartLoading && input.hasData) {
    return t("spectrum.loading");
  }
  return input.hasData ? null : t("spectrum.empty");
}

const HOVER_THROTTLE_MS = 33;

/**
 * Feeds inspector lines to the screen: hover lines at most every 33 ms; focus
 * and idle lines immediately. The line is plain text, not a live region: it
 * changes with every live frame, so announcing it would talk over the user.
 */
export function createInspectorFeed(deps: {
  show(text: string): void;
  now(): number;
  schedule(run: () => void, delayMs: number): () => void;
}): {
  update(line: { text: string; mode: "idle" | "hover" | "focus" }): void;
  dispose(): void;
} {
  let shown: string | null = null;
  let pendingHover: string | null = null;
  let lastHoverAt: number | null = null;
  let cancelTimer: (() => void) | null = null;

  const commit = (text: string) => {
    if (text !== shown) {
      shown = text;
      deps.show(text);
    }
  };
  const flushHover = () => {
    if (pendingHover === null) {
      return;
    }
    const text = pendingHover;
    pendingHover = null;
    lastHoverAt = deps.now();
    commit(text);
  };
  const cancelHover = () => {
    cancelTimer?.();
    cancelTimer = null;
    pendingHover = null;
  };
  return {
    update(line) {
      if (line.mode !== "hover") {
        cancelHover();
        commit(line.text);
        return;
      }
      pendingHover = line.text;
      const now = deps.now();
      if (lastHoverAt === null || now - lastHoverAt >= HOVER_THROTTLE_MS) {
        flushHover();
      } else if (cancelTimer === null) {
        cancelTimer = deps.schedule(
          () => {
            cancelTimer = null;
            flushHover();
          },
          HOVER_THROTTLE_MS - (now - lastHoverAt),
        );
      }
    },
    dispose: cancelHover,
  };
}
