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

export const formatHz = (value: number) =>
  value >= 100 ? value.toFixed(0) : value.toFixed(1);
const formatDb = (value: number) => value.toFixed(1);
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

/** Order reference bands from the server's rotational speeds. */
export function orderBands(
  speeds: RotationalSpeeds | null,
  t: Translate,
): ChartBand[] {
  const bands = speeds?.order_bands;
  if (!Array.isArray(bands)) {
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
    output.push({
      label: t(style?.name ?? band.key),
      min_hz: Math.max(0, center * (1 - tolerance)),
      max_hz: center * (1 + tolerance),
      color: style?.color ?? orderBandFills.wheel1,
    });
  }
  return output;
}

export function bandsAt(
  bands: readonly ChartBand[],
  freqHz: number,
): ChartBand[] {
  return bands.filter((band) => freqHz >= band.min_hz && freqHz <= band.max_hz);
}

/** The pinned trace, else the loudest one. */
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
  let bestDb = Number.NEGATIVE_INFINITY;
  for (const entry of entries) {
    const db = levels.strengthDb(entry.id);
    if (isFiniteNumber(db) && db > bestDb) {
      bestDb = db;
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
  const bandText = (freq: number) => {
    const active = bandsAt(input.bands, freq);
    return active.length
      ? active.map((band) => band.label).join(", ")
      : t("spectrum.inspector_no_band");
  };
  const { cursorIdx, freqAxis } = input;
  if (cursorIdx !== null && cursorIdx >= 0 && cursorIdx < freqAxis.length) {
    const freq = freqAxis[cursorIdx];
    const value = entry.values[Math.min(cursorIdx, entry.values.length - 1)];
    return {
      mode: "hover",
      text: t("spectrum.inspector_hover", {
        sensor: entry.label,
        freq: formatHz(freq),
        value: isFiniteNumber(value) ? formatDb(value) : "--",
        bands: bandText(freq),
      }),
    };
  }
  const peak = focusPeak(entry, freqAxis, input.levels);
  if (!peak) {
    return idle;
  }
  return {
    mode: "focus",
    text: t(
      input.pinnedId
        ? "spectrum.inspector_focus_selected"
        : "spectrum.inspector_focus_strongest",
      {
        sensor: entry.label,
        freq: formatHz(peak.freq),
        value: formatDb(peak.value),
        bands: bandText(peak.freq),
      },
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
        ? t("spectrum.legend.sensor_level", { value: formatDb(db) })
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
 * Feeds inspector lines to the screen: hover lines at most every 33 ms and
 * never announced; focus lines announced once each; idle lines immediately.
 */
export function createInspectorFeed(deps: {
  show(text: string): void;
  announce(text: string): void;
  now(): number;
  schedule(run: () => void, delayMs: number): () => void;
}): {
  update(line: { text: string; mode: "idle" | "hover" | "focus" }): void;
  dispose(): void;
} {
  let shown: string | null = null;
  let announced: string | null = null;
  let pendingHover: string | null = null;
  let lastHoverAt: number | null = null;
  let cancelTimer: (() => void) | null = null;

  const commit = (text: string, announce: boolean) => {
    const shouldAnnounce = announce && text !== announced;
    if (text === shown && !shouldAnnounce) {
      return;
    }
    shown = text;
    deps.show(text);
    if (shouldAnnounce) {
      announced = text;
      deps.announce(text);
    }
  };
  const flushHover = () => {
    if (pendingHover === null) {
      return;
    }
    const text = pendingHover;
    pendingHover = null;
    lastHoverAt = deps.now();
    commit(text, false);
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
        commit(line.text, line.mode === "focus");
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
