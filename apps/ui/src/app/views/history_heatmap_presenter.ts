import type { HistoryInsightsPayload } from "../../api/types";
import { HISTORY_HEATMAP_POSITIONS } from "../../config";
import { heatColor, normalizeUnit } from "../features/heat_utils";
import type {
  HistoryHeatmapViewModel,
  HistoryHeatmapZoneViewModel,
} from "./history_table_models";
import type { PresenterParams } from "./history_presenter_shared";

type LocationIntensityRow = HistoryInsightsPayload["sensor_intensity_by_location"][number];

function normalizeLogLocationKey(location: unknown): string {
  const raw = String(location || "")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!raw) return "";
  if (raw.includes("front left") && raw.includes("wheel")) return "front-left wheel";
  if (raw.includes("front right") && raw.includes("wheel")) return "front-right wheel";
  if (raw.includes("rear left") && raw.includes("wheel")) return "rear-left wheel";
  if (raw.includes("rear right") && raw.includes("wheel")) return "rear-right wheel";
  if (raw.includes("engine")) return "engine bay";
  if (raw.includes("drive") && raw.includes("tunnel")) return "driveshaft tunnel";
  if (raw.includes("driver") && raw.includes("seat")) return "driver seat";
  if (raw.includes("trunk")) return "trunk";
  return raw;
}

function sensorIntensityRows(summary: HistoryInsightsPayload | null): LocationIntensityRow[] {
  return summary?.sensor_intensity_by_location ?? [];
}

function metricFromLocationStat(row: LocationIntensityRow): number | null {
  const value = Number(row.p95_intensity_db ?? row.mean_intensity_db ?? row.max_intensity_db);
  return Number.isFinite(value) ? value : null;
}

function humanizeHeatmapLocationKey(key: string): string {
  return key
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function buildHistoryHeatmapViewModel(
  summary: HistoryInsightsPayload | null,
  params: Pick<PresenterParams, "fmt" | "t">,
  options: {
    stateMessage?: string | null;
    stateTone?: "subtle" | "error" | null;
  } = {},
): HistoryHeatmapViewModel {
  const { fmt, t } = params;
  const { stateMessage = null, stateTone = null } = options;
  const title = t("history.preview_heatmap_title");
  if (summary === null) {
    return {
      title,
      stateMessage,
      stateTone,
      zones: [],
      extras: [],
    };
  }
  const statsRows = sensorIntensityRows(summary);
  const metricByLocation: Record<string, number> = {};
  const labelByLocation: Record<string, string> = {};
  for (const row of statsRows) {
    const key = normalizeLogLocationKey(row.location);
    const metric = metricFromLocationStat(row);
    const label = String(row.location ?? "").trim();
    if (key && typeof metric === "number" && Number.isFinite(metric)) {
      metricByLocation[key] = metric;
    }
    if (key && label) {
      labelByLocation[key] = label;
    }
  }
  const values = Object.values(metricByLocation).filter((value) => typeof value === "number");
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const knownPositionKeys = new Set<string>(HISTORY_HEATMAP_POSITIONS.map((point) => point.key));
  const strongestValue = values.length ? Math.max(...values) : null;
  const zones: HistoryHeatmapZoneViewModel[] = HISTORY_HEATMAP_POSITIONS.map((point) => {
    const value = metricByLocation[point.key];
    const label = labelByLocation[point.key] || humanizeHeatmapLocationKey(point.key);
    const hasValue = typeof value === "number" && Number.isFinite(value);
    if (!hasValue || min === null || max === null) {
      return {
        key: point.key,
        label,
        gridArea: point.area,
        valueLabel: t("report.missing"),
        strongest: false,
        accentColor: null,
        fillPercent: null,
      };
    }
    const norm = normalizeUnit(value, min, max);
    return {
      key: point.key,
      label,
      gridArea: point.area,
      valueLabel: `${fmt(value, 1)} dB`,
      strongest: strongestValue !== null && value === strongestValue,
      accentColor: heatColor(norm),
      fillPercent: Math.round(norm * 100),
    };
  });
  const extras = Object.keys(metricByLocation)
    .filter((key) => !knownPositionKeys.has(key))
    .map((key) => {
      const label = labelByLocation[key] || humanizeHeatmapLocationKey(key);
      return `${label} · ${fmt(metricByLocation[key] ?? 0, 1)} dB`;
    });
  return {
    title,
    stateMessage: null,
    stateTone: null,
    zones,
    extras,
  };
}
