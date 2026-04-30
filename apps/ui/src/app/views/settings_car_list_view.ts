import type { CarRecord } from "../../api/types";
import {
  type CarSelectionState,
  getCarCompleteness,
} from "../car_selection_state";
import { buildOrderReferenceConfidenceDetail } from "../features/car_confidence_summary";
import { formatSavedCarTireSummary } from "../features/cars_tire_setup";

export interface CarsListHighlightedFeedback {
  carId: string;
  carName: string;
}

export interface SettingsCarListViewParams {
  cars: readonly CarRecord[];
  activeCarId: string | null;
  highlightedCarId?: string | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
  fmt: (value: number, digits?: number) => string;
}

export interface CarsListAction {
  type: "activate" | "complete" | "delete" | "add";
  carId: string | null;
}

export interface CarsInlineActionViewModel {
  labelText: string;
  type: CarsListAction["type"];
  variant?: "primary" | "success" | "muted";
}

export interface CarsInlineStateViewModel {
  bodyText: string;
  detailText?: string;
  titleText: string;
  action?: CarsInlineActionViewModel;
  tone?: "default" | "success";
}

export interface CarsListRowMetricViewModel {
  isCode?: boolean;
  labelText: string;
  valueText: string;
}

export interface CarsListRowActionViewModel {
  className: string;
  labelText: string;
  type: Exclude<CarsListAction["type"], "add">;
}

export interface CarsListRowViewModel {
  activeState: "active" | "inactive";
  activeStatusText: string;
  carId: string;
  completionDetailText: string | null;
  deleteLabelText: string;
  displayName: string;
  highlightedStatusText: string | null;
  isComplete: boolean;
  isHighlighted: boolean;
  metaTypeText: string | null;
  metaVariantText: string | null;
  primaryAction: CarsListRowActionViewModel | null;
  readinessState: "ready" | "incomplete";
  readinessStatusText: string;
  setupMetrics: readonly CarsListRowMetricViewModel[];
}

export type SettingsCarListTableRenderModel =
  | {
      emptyState: CarsInlineStateViewModel;
      kind: "empty";
    }
  | {
      kind: "rows";
      rows: readonly CarsListRowViewModel[];
    };

function sameInlineAction(
  left: CarsInlineActionViewModel | undefined,
  right: CarsInlineActionViewModel | undefined,
): boolean {
  return (
    left?.labelText === right?.labelText &&
    left?.type === right?.type &&
    left?.variant === right?.variant
  );
}

function sameInlineState(
  left: CarsInlineStateViewModel,
  right: CarsInlineStateViewModel,
): boolean {
  return (
    left.bodyText === right.bodyText &&
    left.detailText === right.detailText &&
    left.titleText === right.titleText &&
    left.tone === right.tone &&
    sameInlineAction(left.action, right.action)
  );
}

function sameRowAction(
  left: CarsListRowActionViewModel | null,
  right: CarsListRowActionViewModel | null,
): boolean {
  return (
    left?.className === right?.className &&
    left?.labelText === right?.labelText &&
    left?.type === right?.type
  );
}

function sameRowMetric(
  left: CarsListRowMetricViewModel,
  right: CarsListRowMetricViewModel,
): boolean {
  return (
    left.isCode === right.isCode &&
    left.labelText === right.labelText &&
    left.valueText === right.valueText
  );
}

function sameRowMetrics(
  left: readonly CarsListRowMetricViewModel[],
  right: readonly CarsListRowMetricViewModel[],
): boolean {
  return (
    left.length === right.length &&
    left.every((metric, index) => sameRowMetric(metric, right[index]))
  );
}

function sameCarRow(
  left: CarsListRowViewModel,
  right: CarsListRowViewModel,
): boolean {
  return (
    left.activeState === right.activeState &&
    left.activeStatusText === right.activeStatusText &&
    left.carId === right.carId &&
    left.completionDetailText === right.completionDetailText &&
    left.deleteLabelText === right.deleteLabelText &&
    left.displayName === right.displayName &&
    left.highlightedStatusText === right.highlightedStatusText &&
    left.isComplete === right.isComplete &&
    left.isHighlighted === right.isHighlighted &&
    left.metaTypeText === right.metaTypeText &&
    left.metaVariantText === right.metaVariantText &&
    sameRowAction(left.primaryAction, right.primaryAction) &&
    left.readinessState === right.readinessState &&
    left.readinessStatusText === right.readinessStatusText &&
    sameRowMetrics(left.setupMetrics, right.setupMetrics)
  );
}

function sameRowReferences(
  left: readonly CarsListRowViewModel[],
  right: readonly CarsListRowViewModel[],
): boolean {
  return (
    left.length === right.length &&
    left.every((row, index) => row === right[index])
  );
}

function hasConfiguredNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function formatTireSummary(
  car: CarRecord,
  fmt: SettingsCarListViewParams["fmt"],
  t: SettingsCarListViewParams["t"],
): string {
  return formatSavedCarTireSummary(
    car.aspects,
    fmt,
    t("settings.car.tires_missing"),
  );
}

function formatRatioValue(
  value: unknown,
  params: Pick<SettingsCarListViewParams, "fmt" | "t">,
): string {
  if (!hasConfiguredNumber(value)) {
    return params.t("settings.car.value_missing");
  }
  return params.fmt(value, 2);
}

function carApproximationDetail(
  car: CarRecord,
  t: SettingsCarListViewParams["t"],
): string | null {
  return buildOrderReferenceConfidenceDetail(car.order_reference_status, t);
}

function buildPrimaryAction(options: {
  isActive: boolean;
  isComplete: boolean;
  t: SettingsCarListViewParams["t"];
}): CarsListRowActionViewModel | null {
  const { isActive, isComplete, t } = options;
  if (isComplete) {
    if (isActive) {
      return null;
    }
    return {
      className: "btn car-activate-btn",
      labelText: t("settings.car.activate"),
      type: "activate",
    };
  }
  return {
    className: "btn btn--primary car-complete-btn",
    labelText: t(
      isActive ? "settings.car.open_analysis" : "settings.car.finish_setup",
    ),
    type: "complete",
  };
}

export function buildCarsGuidanceRenderModel(options: {
  carSelectionState: CarSelectionState;
  highlightedCarFeedback: CarsListHighlightedFeedback | null;
  t: SettingsCarListViewParams["t"];
}): CarsInlineStateViewModel | null {
  const { carSelectionState, highlightedCarFeedback, t } = options;
  if (
    carSelectionState.kind === "loading" ||
    carSelectionState.kind === "no_cars"
  ) {
    return null;
  }
  if (carSelectionState.kind === "active" && highlightedCarFeedback) {
    return {
      bodyText: t("settings.car.created_body", {
        name: highlightedCarFeedback.carName,
      }),
      detailText: t("settings.car.created_detail"),
      titleText: t("settings.car.created_title"),
      tone: "success",
    };
  }
  if (carSelectionState.kind === "active") {
    return null;
  }
  return {
    bodyText: t("settings.car.guidance.no_active"),
    detailText: t("settings.car.guidance.no_active_detail"),
    titleText: t("settings.car.guidance.no_active_title"),
    tone: "default",
  };
}

export function buildSettingsCarListRenderModel(
  params: SettingsCarListViewParams,
): SettingsCarListTableRenderModel {
  const { cars, activeCarId, highlightedCarId = null, t, fmt } = params;
  if (cars.length === 0) {
    return {
      kind: "empty",
      emptyState: {
        action: {
          labelText: t("settings.car.empty.action"),
          type: "add",
          variant: "success",
        },
        bodyText: t("settings.car.empty.body"),
        detailText: t("settings.car.empty.detail"),
        titleText: t("settings.car.empty.title"),
      },
    };
  }

  return {
    kind: "rows",
    rows: cars.map((car) => {
      const isActive = car.id === activeCarId;
      const isHighlighted = car.id === highlightedCarId;
      const { isComplete } = getCarCompleteness(car);
      return {
        activeState: isActive ? "active" : "inactive",
        activeStatusText: t(
          isActive
            ? "settings.car.active_label"
            : "settings.car.inactive_label",
        ),
        carId: car.id,
        completionDetailText: isComplete
          ? carApproximationDetail(car, t)
          : t("settings.car.incomplete_detail"),
        deleteLabelText: t("settings.car.delete"),
        displayName: car.name,
        highlightedStatusText: isHighlighted
          ? t("settings.car.just_added")
          : null,
        isComplete,
        isHighlighted,
        metaTypeText: car.type ?? null,
        metaVariantText: car.variant ?? null,
        primaryAction: buildPrimaryAction({ isActive, isComplete, t }),
        readinessState: isComplete ? "ready" : "incomplete",
        readinessStatusText: t(
          isComplete
            ? "settings.car.ready_label"
            : "settings.car.incomplete_label",
        ),
        setupMetrics: [
          {
            isCode: true,
            labelText: t("settings.car.col_tires"),
            valueText: formatTireSummary(car, fmt, t),
          },
          {
            labelText: t("settings.car.col_drive"),
            valueText: formatRatioValue(car.aspects?.final_drive_ratio, {
              fmt,
              t,
            }),
          },
          {
            labelText: t("settings.car.col_gear"),
            valueText: formatRatioValue(car.aspects?.current_gear_ratio, {
              fmt,
              t,
            }),
          },
        ],
      };
    }),
  };
}

export function createSettingsCarListRenderModelMemo(): (
  params: SettingsCarListViewParams,
) => SettingsCarListTableRenderModel {
  let previousModel: SettingsCarListTableRenderModel | null = null;
  let previousRowsById = new Map<string, CarsListRowViewModel>();

  return (
    params: SettingsCarListViewParams,
  ): SettingsCarListTableRenderModel => {
    const nextModel = buildSettingsCarListRenderModel(params);
    if (nextModel.kind === "empty") {
      previousRowsById = new Map();
      if (
        previousModel?.kind === "empty" &&
        sameInlineState(previousModel.emptyState, nextModel.emptyState)
      ) {
        return previousModel;
      }
      previousModel = nextModel;
      return nextModel;
    }

    const nextRows = nextModel.rows.map((row) => {
      const previousRow = previousRowsById.get(row.carId);
      return previousRow && sameCarRow(previousRow, row) ? previousRow : row;
    });
    previousRowsById = new Map(nextRows.map((row) => [row.carId, row]));
    if (
      previousModel?.kind === "rows" &&
      sameRowReferences(previousModel.rows, nextRows)
    ) {
      return previousModel;
    }

    previousModel = {
      kind: "rows",
      rows: nextRows,
    };
    return previousModel;
  };
}
