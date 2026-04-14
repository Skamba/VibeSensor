import type { CarRecord } from "../../transport/http_models";
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

export interface SettingsCarListBindingDom {
  carListBody: HTMLElement | null;
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
        ? `<button class="btn car-activate-btn" data-car-action="activate" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.activate"))}</button>`
        : "")
    : `<button class="btn btn--primary car-complete-btn" data-car-action="complete" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t(isActive ? "settings.car.open_analysis" : "settings.car.finish_setup"))}</button>`;
  return `
    <div class="car-list-actions">
      ${primaryButton}
      <button class="btn btn--danger-quiet car-delete-btn" data-car-action="delete" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.delete"))}</button>
    </div>
  `;
}

function renderSetupMetric(labelHtml: string, valueHtml: string): string {
  return `
    <div class="car-row__setup-item">
      <span class="car-row__setup-label">${labelHtml}</span>
      <span class="car-row__setup-value">${valueHtml}</span>
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
      `<div class="settings-table-empty-state">${renderInlineStatePanel({
        titleHtml: escapeHtml(t("settings.car.empty.title")),
        bodyHtml: escapeHtml(t("settings.car.empty.body")),
        detailHtml: escapeHtml(t("settings.car.empty.detail")),
        action: {
          action: "add-car",
          labelHtml: escapeHtml(t("settings.car.empty.action")),
          variant: "success",
        },
      })}</div>`,
      3,
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
      const typeMarkup = car.type
        ? `<span class="car-row__type">${escapeHtml(car.type)}</span>`
        : "";
      const variantMarkup = car.variant
        ? `<span class="car-row__variant">${escapeHtml(car.variant)}</span>`
        : "";
      const metaMarkup = typeMarkup || variantMarkup
        ? `<div class="car-row__meta">${typeMarkup}${variantMarkup}</div>`
        : "";
      const completionDetail = isComplete
        ? ""
        : `<span class="subtle car-row__detail">${escapeHtml(t("settings.car.incomplete_detail"))}</span>`;
      const rowClass = isHighlighted ? ' class="car-list-row--highlighted"' : "";
      return `
        <tr
          ${rowClass}
          data-car-id="${escapeHtml(car.id)}"
          data-car-complete="${isComplete ? "true" : "false"}"
          data-highlighted="${isHighlighted ? "true" : "false"}"
        >
          <td>
            <div class="car-row__identity">
              <div class="car-row__heading">
                <strong>${escapeHtml(car.name)}</strong>
              </div>
              ${metaMarkup}
              <div class="car-status-stack">
                <span class="car-active-pill settings-entity-status" data-state="${isActive ? "active" : "inactive"}">${isActive ? escapeHtml(t("settings.car.active_label")) : escapeHtml(t("settings.car.inactive_label"))}</span>
                <span class="car-readiness-pill settings-entity-status" data-state="${isComplete ? "ready" : "incomplete"}">${escapeHtml(t(isComplete ? "settings.car.ready_label" : "settings.car.incomplete_label"))}</span>
                ${isHighlighted ? `<span class="car-created-pill settings-entity-status">${escapeHtml(t("settings.car.just_added"))}</span>` : ""}
              </div>
              ${completionDetail}
            </div>
          </td>
          <td>
            <div class="car-row__setup">
              ${renderSetupMetric(escapeHtml(t("settings.car.col_tires")), `<code>${escapeHtml(tireStr)}</code>`)}
              ${renderSetupMetric(escapeHtml(t("settings.car.col_drive")), escapeHtml(driveStr))}
              ${renderSetupMetric(escapeHtml(t("settings.car.col_gear")), escapeHtml(gearStr))}
            </div>
          </td>
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
  dom: SettingsCarListBindingDom,
  handlers: { onAction(action: SettingsCarListAction): void },
): ViewDisposer {
  return bindViewEvent(dom.carListBody, "click", (event: MouseEvent) => {
    const action = getSettingsCarListAction(event.target);
    if (action) {
      handlers.onAction(action);
    }
  });
}
