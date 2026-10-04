import type { AnalysisSettingsRequest } from "../../api/types";
import { fmt } from "../../format";
import {
  type AnalysisTuningSettings,
  defaultAnalysisTuningSettings,
} from "../../vehicle_settings";

/** Field specs, formatting, and validation for the analysis settings page. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

export type FieldKey = keyof AnalysisTuningSettings;
export type Drafts = Record<FieldKey, string>;

export interface FieldSpec {
  key: FieldKey;
  inputId: string;
  guidanceId: string;
  labelKey: string;
  /** Values outside this range are rejected. */
  hardMin: number;
  hardMax: number;
  /** Values outside this range need a confirmation. */
  guidedMin: number;
  guidedMax: number;
}

const UNIT = "%";

export const FIELDS: readonly FieldSpec[] = [
  {
    key: "speed_uncertainty_pct",
    inputId: "speedUncertaintyInput",
    guidanceId: "speedUncertaintyGuidance",
    labelKey: "settings.speed_uncertainty",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 5,
  },
  {
    key: "tire_diameter_uncertainty_pct",
    inputId: "tireDiameterUncertaintyInput",
    guidanceId: "tireDiameterUncertaintyGuidance",
    labelKey: "settings.tire_diameter_uncertainty",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 5,
  },
  {
    key: "final_drive_uncertainty_pct",
    inputId: "finalDriveUncertaintyInput",
    guidanceId: "finalDriveUncertaintyGuidance",
    labelKey: "settings.final_drive_uncertainty",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 2,
  },
  {
    key: "gear_uncertainty_pct",
    inputId: "gearUncertaintyInput",
    guidanceId: "gearUncertaintyGuidance",
    labelKey: "settings.gear_slip_uncertainty",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 4,
  },
];

function roundSetting(value: number): number {
  return Number(value.toFixed(1));
}

/** A setting as its number input holds it: at most one decimal, "." separator. */
function draftValue(value: number): string {
  return String(roundSetting(value));
}

/** A setting shown in text, in the UI language ("0.1", nl "0,1"). */
function displayValue(value: number): string {
  const rounded = roundSetting(value);
  return fmt(rounded, Number.isInteger(rounded) ? 0 : 1);
}

export function draftsFrom(settings: AnalysisTuningSettings): Drafts {
  return {
    speed_uncertainty_pct: draftValue(settings.speed_uncertainty_pct),
    tire_diameter_uncertainty_pct: draftValue(
      settings.tire_diameter_uncertainty_pct,
    ),
    final_drive_uncertainty_pct: draftValue(
      settings.final_drive_uncertainty_pct,
    ),
    gear_uncertainty_pct: draftValue(settings.gear_uncertainty_pct),
  };
}

export function guidanceLines(
  field: FieldSpec,
  t: Translate,
): Array<{ label: string; value: string }> {
  return [
    {
      label: t("settings.analysis.recommended_range_label"),
      value: t("settings.analysis.range_value", {
        min: displayValue(field.guidedMin),
        max: displayValue(field.guidedMax),
        unit: UNIT,
      }),
    },
    {
      label: t("settings.analysis.default_label"),
      value: `${displayValue(defaultAnalysisTuningSettings[field.key])}${UNIT}`,
    },
  ];
}

export type DraftCheck =
  | { kind: "invalid"; field: FieldKey; message: string }
  | { kind: "risky"; request: AnalysisSettingsRequest; confirmation: string }
  | { kind: "ok"; request: AnalysisSettingsRequest };

/**
 * Rejects empty or out-of-bounds values (first problem wins); values outside
 * the guided range need a confirmation listing each of them.
 */
export function checkDrafts(drafts: Drafts, t: Translate): DraftCheck {
  const values = FIELDS.map((field) => {
    const raw = drafts[field.key].trim();
    return { field, raw, value: Number(raw) };
  });
  const missing = values.find(
    ({ raw, value }) => raw === "" || !Number.isFinite(value),
  );
  if (missing) {
    return {
      kind: "invalid",
      field: missing.field.key,
      message: t("settings.analysis.invalid_number", {
        field: t(missing.field.labelKey),
      }),
    };
  }
  const outOfBounds = values.find(
    ({ field, value }) => value < field.hardMin || value > field.hardMax,
  );
  if (outOfBounds) {
    const { field, value } = outOfBounds;
    return {
      kind: "invalid",
      field: field.key,
      message: t("settings.analysis.invalid_value", {
        field: t(field.labelKey),
        min: displayValue(field.hardMin),
        max: displayValue(field.hardMax),
        value: displayValue(value),
        unit: UNIT,
      }),
    };
  }
  const request: AnalysisSettingsRequest = Object.fromEntries(
    values.map(({ field, value }) => [field.key, value]),
  );
  const risky = values.filter(
    ({ field, value }) => value < field.guidedMin || value > field.guidedMax,
  );
  if (risky.length === 0) {
    return { kind: "ok", request };
  }
  const confirmation = [
    t("settings.analysis.risky_confirm_intro"),
    ...risky.map(({ field, value }) =>
      t("settings.analysis.risky_confirm_line", {
        field: t(field.labelKey),
        value: displayValue(value),
        min: displayValue(field.guidedMin),
        max: displayValue(field.guidedMax),
        defaultValue: displayValue(defaultAnalysisTuningSettings[field.key]),
        unit: UNIT,
      }),
    ),
    "",
    t("settings.analysis.risky_confirm_outro"),
  ].join("\n");
  return { kind: "risky", request, confirmation };
}
