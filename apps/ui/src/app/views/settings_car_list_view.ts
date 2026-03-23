import type { CarRecord } from "../../api/types";
import { renderTableEmptyRow } from "./dom_helpers";

export interface SettingsCarListViewParams {
  cars: CarRecord[];
  activeCarId: string | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
}

export interface SettingsCarListAction {
  type: "activate" | "delete";
  carId: string;
}

export function renderSettingsCarList(
  container: HTMLElement,
  params: SettingsCarListViewParams,
): void {
  const { cars, activeCarId, t, escapeHtml, fmt } = params;
  if (!cars.length) {
    container.innerHTML = renderTableEmptyRow(
      escapeHtml(t("settings.car.no_cars")),
      7,
    );
    return;
  }

  container.innerHTML = cars
    .map((car) => {
      const isActive = car.id === activeCarId;
      const aspects = car.aspects || {};
      const tireStr = `${aspects.tire_width_mm || "?"}/${aspects.tire_aspect_pct || "?"}R${aspects.rim_in || "?"}`;
      const driveStr = fmt(aspects.final_drive_ratio, 2);
      const gearStr = fmt(aspects.current_gear_ratio, 2);
      return `<tr data-car-id="${escapeHtml(car.id)}"><td><span class="car-active-pill ${isActive ? "active" : "inactive"}">${isActive ? escapeHtml(t("settings.car.active_label")) : escapeHtml(t("settings.car.inactive_label"))}</span></td><td><strong>${escapeHtml(car.name)}</strong></td><td>${escapeHtml(car.type)}</td><td><code>${escapeHtml(tireStr)}</code></td><td>${escapeHtml(driveStr)}</td><td>${escapeHtml(gearStr)}</td><td class="car-list-actions">${isActive ? "" : `<button class="btn btn--success car-activate-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.activate"))}</button>`}<button class="btn btn--danger car-delete-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.delete"))}</button></td></tr>`;
    })
    .join("");
}

export function getSettingsCarListAction(
  target: EventTarget | null,
): SettingsCarListAction | null {
  if (!(target instanceof Element)) {
    return null;
  }
  const button = target.closest<HTMLButtonElement>(".car-activate-btn, .car-delete-btn");
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
