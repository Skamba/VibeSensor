import type { UiCarsDom } from "../dom/cars_dom";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { UiShellDom } from "../dom/shell_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import {
  type CarSelectionState,
  deriveCarSelectionState,
  getCarCompleteness,
  hasResolvedActiveCar,
  resolveActiveCar,
} from "../car_selection_state";
import type { SettingsState } from "../ui_app_state";
import type { CarRecord, CarsPayload } from "../../api/types";
import {
  deleteSettingsCar,
  getSettingsCars,
  setActiveSettingsCar,
} from "../../api";
import {
  getSettingsCarListAction,
  renderSettingsCarList,
} from "../views/settings_car_list_view";
import { renderInlineStatePanel } from "../views/dom_helpers";
import {
  ANALYSIS_SETTING_KEYS,
  createSettingsAnalysisModule,
  type SettingsAnalysisModule,
} from "./settings_analysis_module";
import {
  createSettingsGpsStatusModule,
  type SettingsGpsStatusModule,
} from "./settings_gps_status_module";
import {
  createSettingsSpeedSourceModule,
  type SettingsSpeedSourceModule,
} from "./settings_speed_source_module";
import { bindSettingsTabs } from "./settings_tabs_controller";

export interface SettingsFeatureDeps extends FeatureDepsBase {
  dom: UiSettingsDom;
  shellDom: Pick<UiShellDom, "menuButtons">;
  carsDom: Pick<UiCarsDom, "addCarBtn">;
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  renderSpectrum: () => void;
  renderSpeedReadout: () => void;
  renderRealtimeStatus: () => void;
  renderRealtimeLoggingStatus: () => void;
}

export interface SettingsFeature {
  bindHandlers(): void;
  syncSettingsInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  loadAnalysisSettingsFromServer(): Promise<void>;
  loadCarsFromServer(): Promise<void>;
  renderCarList(): void;
  syncCarsPayload(payload: CarsPayload): void;
  syncActiveCarToInputs(): void;
  showCarCreationSuccess(carId: string, carName: string): void;
  saveAnalysisFromInputs(): void;
  saveSpeedSourceFromInputs(): void;
  startGpsStatusPolling(): void;
  stopGpsStatusPolling(): void;
}

export function createSettingsFeature(ctx: SettingsFeatureDeps): SettingsFeature {
  const { settings, dom: els, shellDom, carsDom, t, escapeHtml, fmt } = ctx;
  let handlersBound = false;
  let highlightedCarFeedback: { carId: string; carName: string } | null = null;

  function showSettingsSaveError(error: unknown): void {
    ctx.showError(error instanceof Error ? error.message : t("settings.save_failed"));
  }

  function hasValidActiveCar(): boolean {
    return hasResolvedActiveCar(settings);
  }

  function openSettingsTab(tabId: string): void {
    els.settingsTabs.find((button) => button.getAttribute("data-settings-tab") === tabId)?.click();
  }

  function clearHighlightedCarFeedback(): void {
    highlightedCarFeedback = null;
  }

  function dismissHighlightedCarFeedback(): void {
    if (highlightedCarFeedback === null) {
      return;
    }
    clearHighlightedCarFeedback();
    syncCarDependentUiState();
    renderCarList();
  }

  function settingsTabIdAt(index: number): string | null {
    if (!els.settingsTabs.length) {
      return null;
    }
    const safeIndex = ((index % els.settingsTabs.length) + els.settingsTabs.length) % els.settingsTabs.length;
    return els.settingsTabs[safeIndex].getAttribute("data-settings-tab");
  }

  function primaryViewIdAt(index: number): string | undefined {
    if (!shellDom.menuButtons.length) {
      return undefined;
    }
    const safeIndex = ((index % shellDom.menuButtons.length) + shellDom.menuButtons.length)
      % shellDom.menuButtons.length;
    return shellDom.menuButtons[safeIndex].dataset.view;
  }

  function bindHighlightedCarFeedbackResetEvents(): void {
    const dismissForSettingsTab = (tabId: string | null): void => {
      if (tabId && tabId !== "carTab") {
        dismissHighlightedCarFeedback();
      }
    };
    const dismissForPrimaryView = (viewId: string | undefined): void => {
      if (viewId && viewId !== "settingsView") {
        dismissHighlightedCarFeedback();
      }
    };

    els.settingsTabs.forEach((tab, index) => {
      tab.addEventListener("click", () => {
        dismissForSettingsTab(tab.getAttribute("data-settings-tab"));
      });
      tab.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          dismissForSettingsTab(tab.getAttribute("data-settings-tab"));
          return;
        }
        if (event.key === "ArrowRight") {
          dismissForSettingsTab(settingsTabIdAt(index + 1));
          return;
        }
        if (event.key === "ArrowLeft") {
          dismissForSettingsTab(settingsTabIdAt(index - 1));
          return;
        }
        if (event.key === "Home") {
          dismissForSettingsTab(settingsTabIdAt(0));
          return;
        }
        if (event.key === "End") {
          dismissForSettingsTab(settingsTabIdAt(els.settingsTabs.length - 1));
        }
      });
    });

    shellDom.menuButtons.forEach((button, index) => {
      button.addEventListener("click", () => {
        dismissForPrimaryView(button.dataset.view);
      });
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          dismissForPrimaryView(button.dataset.view);
          return;
        }
        if (event.key === "ArrowRight") {
          dismissForPrimaryView(primaryViewIdAt(index + 1));
          return;
        }
        if (event.key === "ArrowLeft") {
          dismissForPrimaryView(primaryViewIdAt(index - 1));
          return;
        }
        if (event.key === "Home") {
          dismissForPrimaryView(primaryViewIdAt(0));
          return;
        }
        if (event.key === "End") {
          dismissForPrimaryView(primaryViewIdAt(shellDom.menuButtons.length - 1));
        }
      });
    });
  }

  function renderCarSelectionGuidance(carSelectionState: CarSelectionState): void {
    const guidance = els.carSelectionGuidance;
    if (!guidance) {
      return;
    }
    if (carSelectionState.kind === "loading" || carSelectionState.kind === "no_cars") {
      guidance.hidden = true;
      guidance.replaceChildren();
      return;
    }
    if (carSelectionState.kind === "active" && highlightedCarFeedback) {
      guidance.hidden = false;
      guidance.innerHTML = `
        <div class="empty-state empty-state--inline car-selection-feedback car-selection-feedback--success" role="status">
          <strong class="empty-state__title">${escapeHtml(t("settings.car.created_title"))}</strong>
          <span class="empty-state__body">${escapeHtml(t("settings.car.created_body", { name: highlightedCarFeedback.carName }))}</span>
          <span class="empty-state__detail">${escapeHtml(t("settings.car.created_detail"))}</span>
        </div>
      `;
      return;
    }
    if (carSelectionState.kind === "active") {
      guidance.hidden = true;
      guidance.replaceChildren();
      return;
    }
    guidance.hidden = false;
    guidance.innerHTML = renderInlineStatePanel({
      titleHtml: escapeHtml(t("settings.car.guidance.no_active_title")),
      bodyHtml: escapeHtml(t("settings.car.guidance.no_active")),
      detailHtml: escapeHtml(t("settings.car.guidance.no_active_detail")),
    });
  }

  function syncCarDependentUiState(): void {
    const carSelectionState = deriveCarSelectionState(settings);
    const hasActiveCar = carSelectionState.kind === "active";
    if (els.saveAnalysisBtn) {
      els.saveAnalysisBtn.disabled = !hasActiveCar;
    }
    if (els.resetAnalysisBtn) {
      els.resetAnalysisBtn.disabled = !hasActiveCar;
    }
    if (els.analysisNoCarMessage) {
      els.analysisNoCarMessage.hidden = hasActiveCar || carSelectionState.kind === "loading";
    }
    renderCarSelectionGuidance(carSelectionState);
  }

  const analysisModule: SettingsAnalysisModule = createSettingsAnalysisModule({
    dom: els,
    t,
    escapeHtml,
    showError: ctx.showError,
    settings,
    renderSpectrum: ctx.renderSpectrum,
    hasValidActiveCar,
    onMissingActiveCar: syncCarDependentUiState,
    onSaveError: showSettingsSaveError,
  });
  const speedSourceModule: SettingsSpeedSourceModule = createSettingsSpeedSourceModule({
    dom: els,
    shellDom,
    t,
    escapeHtml,
    showError: ctx.showError,
    settings,
    getSpeedUnit: ctx.getSpeedUnit,
    fmt,
    renderSpeedReadout: ctx.renderSpeedReadout,
    onSaveError: showSettingsSaveError,
  });
  const gpsStatusModule: SettingsGpsStatusModule = createSettingsGpsStatusModule({
    dom: els,
    t,
    escapeHtml,
    showError: ctx.showError,
    settings,
    getSpeedUnit: ctx.getSpeedUnit,
    fmt,
    syncSpeedSourceSelectionUi: speedSourceModule.syncSpeedSourceSelectionUi,
    renderSpeedReadout: ctx.renderSpeedReadout,
  });
  syncCarDependentUiState();

  function syncCarsPayload(payload: CarsPayload): void {
    settings.cars = payload.cars;
    settings.carsLoaded = true;
    const requestedActiveCarId = payload.active_car_id;
    const hasRequestedActive = requestedActiveCarId
      ? settings.cars.some((car) => car.id === requestedActiveCarId)
      : false;
    settings.activeCarId = hasRequestedActive ? requestedActiveCarId : null;
    if (highlightedCarFeedback && !settings.cars.some((car) => car.id === highlightedCarFeedback?.carId)) {
      highlightedCarFeedback = null;
    }
    syncCarDependentUiState();
    ctx.renderRealtimeStatus();
    ctx.renderRealtimeLoggingStatus();
  }

  async function loadCarsFromServer(): Promise<void> {
    try {
      const payload = await getSettingsCars();
      syncCarsPayload(payload);
      renderCarList();
      syncActiveCarToInputs();
    } catch (_err) { /* ignore */ }
  }

  function findCar(carId: string): CarRecord | null {
    return settings.cars.find((entry) => entry.id === carId) ?? null;
  }

  async function handleActivateCar(carId: string): Promise<void> {
    if (!carId) return;
    const car = findCar(carId);
    if (!car) {
      return;
    }
    if (!getCarCompleteness(car).isComplete) {
      ctx.showError(t("settings.car.activate_incomplete"));
      return;
    }
    try {
      const result = await setActiveSettingsCar(carId);
      syncCarsPayload(result);
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      syncCarDependentUiState();
      renderCarList();
      ctx.renderSpectrum();
    } catch (_err) {
      ctx.showError(t("settings.car.activate_failed"));
    }
  }

  async function handleCompleteCar(carId: string): Promise<void> {
    if (!carId) {
      return;
    }
    const car = findCar(carId);
    if (!car) {
      return;
    }
    try {
      let didSyncSelection = false;
      if (car.id !== settings.activeCarId) {
        const result = await setActiveSettingsCar(carId);
        syncCarsPayload(result);
        syncActiveCarToInputs();
        ctx.renderSpectrum();
        didSyncSelection = true;
      }
      const hadFeedback = highlightedCarFeedback !== null;
      clearHighlightedCarFeedback();
      if (didSyncSelection || hadFeedback) {
        syncCarDependentUiState();
        renderCarList();
      }
      openSettingsTab("analysisTab");
    } catch (_err) {
      ctx.showError(t("settings.car.activate_failed"));
    }
  }

  async function handleDeleteCar(carId: string): Promise<void> {
    if (!carId) return;
    const car = settings.cars.find((entry) => entry.id === carId);
    const ok = window.confirm(t("settings.car.delete_confirm", { name: car?.name || "" }));
    if (!ok) return;
    try {
      const result = await deleteSettingsCar(carId);
      syncCarsPayload(result);
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      syncCarDependentUiState();
      renderCarList();
      ctx.renderSpectrum();
    } catch (_err) {
      ctx.showError(t("settings.car.delete_failed"));
    }
  }

  function renderCarList(): void {
    if (!els.carListBody) return;
    renderSettingsCarList(els.carListBody, {
      cars: settings.cars,
      activeCarId: settings.activeCarId,
      highlightedCarId: highlightedCarFeedback?.carId ?? null,
      t,
      escapeHtml,
      fmt,
    });
  }

  function syncActiveCarToInputs(): void {
    const car = resolveActiveCar(settings);
    if (!car) {
      syncCarDependentUiState();
      return;
    }
    if (car.aspects && typeof car.aspects === "object") {
      for (const key of ANALYSIS_SETTING_KEYS) {
        const value = car.aspects[key];
        if (typeof value === "number") {
          settings.vehicleSettings[key] = value;
        }
      }
    }
    analysisModule.syncSettingsInputs();
    syncCarDependentUiState();
  }

  function bindCarListEvents(): void {
    if (!els.carListBody) return;
    els.carListBody.addEventListener("click", (event) => {
      const action = getSettingsCarListAction(event.target);
      if (!action) {
        return;
      }
      if (action.type === "add") {
        carsDom.addCarBtn.click();
        return;
      }
      if (action.type === "activate") {
        if (action.carId) {
          void handleActivateCar(action.carId);
        }
        return;
      }
      if (action.type === "complete") {
        if (action.carId) {
          void handleCompleteCar(action.carId);
        }
        return;
      }
      if (action.carId) {
        void handleDeleteCar(action.carId);
      }
    });
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    bindSettingsTabs(els);
    bindHighlightedCarFeedbackResetEvents();
    bindCarListEvents();
    analysisModule.bindHandlers();
    speedSourceModule.bindHandlers();
  }

  return {
    bindHandlers,
    syncSettingsInputs: analysisModule.syncSettingsInputs,
    loadSpeedSourceFromServer: speedSourceModule.loadSpeedSourceFromServer,
    loadAnalysisSettingsFromServer: analysisModule.loadAnalysisSettingsFromServer,
    loadCarsFromServer,
    renderCarList,
    syncCarsPayload,
    syncActiveCarToInputs,
    showCarCreationSuccess(carId: string, carName: string): void {
      highlightedCarFeedback = { carId, carName };
      syncCarDependentUiState();
    },
    saveAnalysisFromInputs: analysisModule.saveAnalysisFromInputs,
    saveSpeedSourceFromInputs: speedSourceModule.saveSpeedSourceFromInputs,
    startGpsStatusPolling: gpsStatusModule.startGpsStatusPolling,
    stopGpsStatusPolling: gpsStatusModule.stopGpsStatusPolling,
  };
}
