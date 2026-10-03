import type { CarRecord } from "../../api/types";
import {
  type CarSelectionState,
  getCarCompleteness,
} from "../../car_selection";
import {
  buildOrderReferenceConfidenceDetail,
  formatSavedCarTireSummary,
} from "./tires";

/** Pure view models for the saved-car list and its guidance banner. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;
type FormatNumber = (value: number, digits?: number) => string;

export type CarRowAction = "activate" | "complete";

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
  metrics: Array<{ label: string; value: string; code?: boolean }>;
  primaryAction: {
    type: CarRowAction;
    label: string;
    className: string;
  } | null;
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

function primaryAction(
  isActive: boolean,
  isComplete: boolean,
  t: Translate,
): CarRow["primaryAction"] {
  if (!isComplete) {
    return {
      type: "complete",
      label: t(
        isActive ? "settings.car.open_analysis" : "settings.car.finish_setup",
      ),
      className: "btn btn--primary car-complete-btn",
    };
  }
  return isActive
    ? null
    : {
        type: "activate",
        label: t("settings.car.activate"),
        className: "btn car-activate-btn",
      };
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
      detail: isComplete
        ? buildOrderReferenceConfidenceDetail(car.order_reference_status, t)
        : t("settings.car.incomplete_detail"),
      metrics: [
        {
          label: t("settings.car.col_tires"),
          value: formatSavedCarTireSummary(
            car.aspects,
            fmt,
            t("settings.car.tires_missing"),
          ),
          code: true,
        },
        {
          label: t("settings.car.col_drive"),
          value: ratioText(car.aspects?.final_drive_ratio, fmt, t),
        },
        {
          label: t("settings.car.col_gear"),
          value: ratioText(car.aspects?.current_gear_ratio, fmt, t),
        },
      ],
      primaryAction: primaryAction(isActive, isComplete, t),
    };
  });
}
