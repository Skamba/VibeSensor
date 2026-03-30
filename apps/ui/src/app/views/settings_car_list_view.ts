import type { CarRecord } from "../../api/types";
import {
  closestFromTarget,
  renderInlineStatePanel,
  renderTableEmptyRow,
} from "./dom_helpers";

export interface SettingsCarListViewParams {
  cars: CarRecord[];
  activeCarId: string | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
}

export interface SettingsCarListAction {
  type: "activate" | "delete" | "add";
  carId: string | null;
}

export function renderSettingsCarList(
  container: HTMLElement,
  params: SettingsCarListViewParams,
): void {
  const { cars, activeCarId, t, escapeHtml, fmt } = params;
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
      const aspects = car.aspects || {};
      const tireStr = `${aspects.tire_width_mm || "?"}/${aspects.tire_aspect_pct || "?"}R${aspects.rim_in || "?"}`;
      const driveStr = typeof aspects.final_drive_ratio === "number" ? fmt(aspects.final_drive_ratio, 2) : "?";
      const gearStr = typeof aspects.current_gear_ratio === "number" ? fmt(aspects.current_gear_ratio, 2) : "?";
      return `<tr data-car-id="${escapeHtml(car.id)}"><td><span class="car-active-pill ${isActive ? "active" : "inactive"}">${isActive ? escapeHtml(t("settings.car.active_label")) : escapeHtml(t("settings.car.inactive_label"))}</span></td><td><strong>${escapeHtml(car.name)}</strong></td><td>${escapeHtml(car.type)}</td><td><code>${escapeHtml(tireStr)}</code></td><td>${escapeHtml(driveStr)}</td><td>${escapeHtml(gearStr)}</td><td class="car-list-actions">${isActive ? "" : `<button class="btn btn--success car-activate-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.activate"))}</button>`}<button class="btn btn--danger car-delete-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.delete"))}</button></td></tr>`;
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
  const button = closestFromTarget<HTMLButtonElement>(target, ".car-activate-btn, .car-delete-btn");
  if (!button) {
    return null;
  }
  const carId = button.getAttribute("data-car-id");
  if (!carId) {
    return null;
  }
  return {
    type: button.classList.contains("car-activate-btn") ? "activate" : "delete",
    carId,
  };
}
