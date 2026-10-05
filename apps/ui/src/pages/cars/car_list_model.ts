import type { CarRecord } from "../../api/types";
import {
  type Capabilities,
  carCapabilities,
  type FuelType,
} from "../../capabilities";
import {
  type ProvenanceTier,
  provenanceTier,
  savedCarReferences,
} from "../../car_references";
import {
  type CarSelectionState,
  getCarCompleteness,
} from "../../car_selection";
import { formatSavedCarTireSummary } from "./tires";
import { estimateNoteKey } from "./wizard_model";

/** Pure view models for the saved-car list and its guidance banner. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;
type FormatNumber = (value: number, digits?: number) => string;

export interface InlineState {
  title: string;
  body: string;
  detail: string | null;
  tone: "default" | "success";
}

export interface CarRow {
  carId: string;
  name: string;
  type: string | null;
  variant: string | null;
  isActive: boolean;
  isComplete: boolean;
  isHighlighted: boolean;
  activeText: string;
  readinessText: string;
  detail: string | null;
  metrics: Array<{
    label: string;
    value: string;
    code?: boolean;
    /** The reference's source chip; facts the owner states have none. */
    tier?: ProvenanceTier;
  }>;
  fuelType: FuelType;
  capabilities: Capabilities;
  /** Activate a ready inactive car; `null` for the active one or an incomplete one. */
  activateLabel: string | null;
  /** "Finish setup" on an incomplete car, plain "Edit" otherwise. */
  editLabel: string;
}

/** The banner above the list: just-added feedback or "no active car". */
export function guidance(
  selection: CarSelectionState,
  highlighted: { carName: string } | null,
  t: Translate,
): InlineState | null {
  if (selection.kind === "loading" || selection.kind === "no_cars") {
    return null;
  }
  if (selection.kind === "active") {
    return highlighted
      ? {
          title: t("settings.car.created_title"),
          body: t("settings.car.created_body", { name: highlighted.carName }),
          detail: t("settings.car.created_detail"),
          tone: "success",
        }
      : null;
  }
  return {
    title: t("settings.car.guidance.no_active_title"),
    body: t("settings.car.guidance.no_active"),
    detail: t("settings.car.guidance.no_active_detail"),
    tone: "default",
  };
}

function ratioText(value: unknown, fmt: FormatNumber, t: Translate): string {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? fmt(value, 2)
    : t("settings.car.value_missing");
}

function rowDetail(car: CarRecord, isComplete: boolean, t: Translate) {
  if (!isComplete) {
    return t(
      car.fuel_type === "EV"
        ? "settings.car.incomplete_detail_ev"
        : "settings.car.incomplete_detail",
    );
  }
  const estimate = estimateNoteKey(
    savedCarReferences(car),
    car.fuel_type ?? null,
  );
  return estimate
    ? `${t(estimate)} ${t("settings.car.confidence.review_detail")}`
    : null;
}

export function carRows(
  cars: readonly CarRecord[],
  activeCarId: string | null,
  highlightedCarId: string | null,
  fmt: FormatNumber,
  t: Translate,
): CarRow[] {
  return cars.map((car) => {
    const isActive = car.id === activeCarId;
    const { isComplete } = getCarCompleteness(car);
    const refs = savedCarReferences(car);
    return {
      carId: car.id,
      name: car.name,
      type: car.type ?? null,
      variant: car.variant ?? null,
      isActive,
      isComplete,
      isHighlighted: car.id === highlightedCarId,
      activeText: t(
        isActive ? "settings.car.active_label" : "settings.car.inactive_label",
      ),
      readinessText: t(
        isComplete
          ? "settings.car.ready_label"
          : "settings.car.incomplete_label",
      ),
      detail: rowDetail(car, isComplete, t),
      metrics: [
        {
          label: t("settings.car.col_tires"),
          value: formatSavedCarTireSummary(
            car.aspects,
            fmt,
            t("settings.car.tires_missing"),
          ),
          code: true,
          tier: provenanceTier(refs.tire),
        },
        {
          // An EV's final drive is its single reduction ratio.
          label: t(
            car.fuel_type === "EV"
              ? "settings.car.col_reduction"
              : "settings.car.col_drive",
          ),
          value: ratioText(car.aspects?.final_drive_ratio, fmt, t),
          tier: provenanceTier(refs.finalDrive),
        },
        // An EV has one fixed reduction: no top gear to show.
        ...(car.fuel_type === "EV"
          ? []
          : [
              {
                label: t("settings.car.col_gear"),
                value: ratioText(car.aspects?.current_gear_ratio, fmt, t),
                tier: provenanceTier(refs.topGear),
              },
            ]),
        {
          label: t("settings.car.col_drive_layout"),
          value: t(
            `settings.car.drive_layout.${car.drive_layout ?? "unknown"}`,
          ),
        },
      ],
      fuelType: car.fuel_type ?? null,
      capabilities: carCapabilities(refs, car.fuel_type ?? null),
      activateLabel:
        isComplete && !isActive ? t("settings.car.activate") : null,
      editLabel: t(
        isComplete ? "settings.car.edit" : "settings.car.finish_setup",
      ),
    };
  });
}
