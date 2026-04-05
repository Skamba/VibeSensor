import type { CarRecord } from "../../api/types";
import type { UiSettingsDom } from "../dom/settings_dom";
import { getCarCompleteness } from "../car_selection_state";
import {
  closestFromTarget,
  renderInlineStatePanel,
  renderTableEmptyRow,
} from "./dom_helpers";
import { bindViewEvent, type ViewDisposer } from "./dom_event_bindings";

export interface SettingsCarListViewParams {
  cars: CarRecord[];
  activeCarId: string | null;
  highlightedCarId?: string | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
}

export interface SettingsCarListAction {
  type: "activate" | "complete" | "delete" | "add";
  carId: string | null;
}

function hasConfiguredNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function formatTireSummary(
  car: CarRecord,
  t: SettingsCarListViewParams["t"],
): string {
  const aspects = car.aspects || {};
  if (
    hasConfiguredNumber(aspects.tire_width_mm)
    && hasConfiguredNumber(aspects.tire_aspect_pct)
    && hasConfiguredNumber(aspects.rim_in)
  ) {
    return `${aspects.tire_width_mm}/${aspects.tire_aspect_pct}R${aspects.rim_in}`;
  }
  return t("settings.car.tires_missing");
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

function renderRowActionButtons(
  car: CarRecord,
  options: {
    isActive: boolean;
    isComplete: boolean;
    params: Pick<SettingsCarListViewParams, "escapeHtml" | "t">;
  },
): string {
  const {
    isActive,
    isComplete,
    params: { escapeHtml, t },
  } = options;
  const primaryButton = isComplete
    ? (!isActive
        ? `<button class="btn btn--success car-activate-btn" data-car-action="activate" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.activate"))}</button>`
        : "")
    : `<button class="btn btn--primary car-complete-btn" data-car-action="complete" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t(isActive ? "settings.car.open_analysis" : "settings.car.finish_setup"))}</button>`;
  return `
    <div class="car-list-actions">
      ${primaryButton}
      <button class="btn btn--danger-quiet car-delete-btn" data-car-action="delete" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.delete"))}</button>
    </div>
  `;
}

export function renderSettingsCarList(
  container: HTMLElement,
  params: SettingsCarListViewParams,
): void {
  const {
    cars,
    activeCarId,
    highlightedCarId = null,
    t,
    escapeHtml,
    fmt,
  } = params;
  if (!cars.length) {
    container.innerHTML = renderTableEmptyRow(
      renderInlineStatePanel({
        titleHtml: escapeHtml(t("settings.car.empty.title")),
        bodyHtml: escapeHtml(t("settings.car.empty.body")),
        detailHtml: escapeHtml(t("settings.car.empty.detail")),
        action: {
          action: "add-car",
          labelHtml: escapeHtml(t("settings.car.empty.action")),
          variant: "success",
        },
      }),
      7,
    );
    return;
  }

  container.innerHTML = cars
    .map((car) => {
      const isActive = car.id === activeCarId;
      const isHighlighted = car.id === highlightedCarId;
      const { isComplete } = getCarCompleteness(car);
      const tireStr = formatTireSummary(car, t);
      const driveStr = formatRatioValue(car.aspects?.final_drive_ratio, { fmt, t });
      const gearStr = formatRatioValue(car.aspects?.current_gear_ratio, { fmt, t });
      const variantMarkup = car.variant
        ? `<span class="subtle car-row__variant">${escapeHtml(car.variant)}</span>`
        : "";
      const completionDetail = isComplete
        ? ""
        : `<span class="subtle car-row__detail">${escapeHtml(t("settings.car.incomplete_detail"))}</span>`;
      return `
        <tr
          data-car-id="${escapeHtml(car.id)}"
          data-car-complete="${isComplete ? "true" : "false"}"
          class="${isHighlighted ? "car-list-row--highlighted" : ""}"
        >
          <td>
            <div class="car-status-stack">
              <span class="car-active-pill ${isActive ? "active" : "inactive"}">${isActive ? escapeHtml(t("settings.car.active_label")) : escapeHtml(t("settings.car.inactive_label"))}</span>
              <span class="car-readiness-pill ${isComplete ? "ready" : "incomplete"}">${escapeHtml(t(isComplete ? "settings.car.ready_label" : "settings.car.incomplete_label"))}</span>
              ${isHighlighted ? `<span class="car-created-pill">${escapeHtml(t("settings.car.just_added"))}</span>` : ""}
            </div>
          </td>
          <td>
            <div class="car-row__identity">
              <strong>${escapeHtml(car.name)}</strong>
              ${variantMarkup}
              ${completionDetail}
            </div>
          </td>
          <td>${escapeHtml(car.type)}</td>
          <td><code>${escapeHtml(tireStr)}</code></td>
          <td>${escapeHtml(driveStr)}</td>
          <td>${escapeHtml(gearStr)}</td>
          <td>${renderRowActionButtons(car, { isActive, isComplete, params: { escapeHtml, t } })}</td>
        </tr>
      `;
    })
    .join("");
}

export function getSettingsCarListAction(
  target: EventTarget | null,
): SettingsCarListAction | null {
  const inlineAction = closestFromTarget<HTMLElement>(target, '[data-inline-state-action="add-car"]');
  if (inlineAction) {
    return {
      type: "add",
      carId: null,
    };
  }
  const button = closestFromTarget<HTMLButtonElement>(target, "[data-car-action]");
  if (!button) {
    return null;
  }
  const type = button.getAttribute("data-car-action");
  if (type !== "activate" && type !== "complete" && type !== "delete") {
    return null;
  }
  const carId = button.getAttribute("data-car-id");
  if (!carId) {
    return null;
  }
  return {
    type,
    carId,
  };
}

export function bindSettingsCarListActions(
  dom: Pick<UiSettingsDom, "carListBody">,
  handlers: { onAction(action: SettingsCarListAction): void },
): ViewDisposer {
  return bindViewEvent(dom.carListBody, "click", (event: MouseEvent) => {
    const action = getSettingsCarListAction(event.target);
    if (action) {
      handlers.onAction(action);
    }
  });
}
