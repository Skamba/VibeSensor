import type { FeatureDepsBase } from "../feature_deps_base";
import type { AppState } from "../ui_app_state";
import type { CarUpsertRequest, CarsPayload } from "../../api/types";
import {
  addSettingsCar,
  deleteSettingsCar,
  getSettingsCars,
  setActiveSettingsCar,
} from "../../api";
import {
  getSettingsCarListAction,
  renderSettingsCarList,
} from "../views/settings_car_list_view";
import {
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
  state: AppState;
  fmt: (n: number, digits?: number) => string;
  renderSpectrum: () => void;
  renderSpeedReadout: () => void;
  onCarSelectionStateChange: () => void;
}

export interface SettingsFeature {
  bindHandlers(): void;
  syncSettingsInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  loadAnalysisSettingsFromServer(): Promise<void>;
  loadCarsFromServer(): Promise<void>;
  renderCarList(): void;
  syncActiveCarToInputs(): void;
  saveAnalysisFromInputs(): void;
  saveSpeedSourceFromInputs(): void;
  saveHeaderManualSpeedFromInput(): void;
  addCarFromWizard(name: string, carType: string, aspects: Record<string, number>, variant?: string): Promise<void>;
  startGpsStatusPolling(): void;
  stopGpsStatusPolling(): void;
}

export function createSettingsFeature(ctx: SettingsFeatureDeps): SettingsFeature {
  const { state, els, t, escapeHtml, fmt } = ctx;
  let handlersBound = false;

  function showSettingsSaveError(error: unknown): void {
    window.alert(error instanceof Error ? error.message : t("settings.save_failed"));
  }

  function hasValidActiveCar(): boolean {
    return Boolean(state.activeCarId && state.cars.some((car) => car.id === state.activeCarId));
  }

  function syncCarDependentUiState(): void {
    const hasActiveCar = hasValidActiveCar();
    if (els.saveAnalysisBtn) {
      els.saveAnalysisBtn.disabled = !hasActiveCar;
    }
    if (els.analysisNoCarMessage) {
      els.analysisNoCarMessage.hidden = hasActiveCar;
    }
    ctx.onCarSelectionStateChange();
  }

  const analysisModule: SettingsAnalysisModule = createSettingsAnalysisModule({
    els,
    t,
    escapeHtml,
    state,
    renderSpectrum: ctx.renderSpectrum,
    hasValidActiveCar,
    onMissingActiveCar: syncCarDependentUiState,
    onSaveError: showSettingsSaveError,
  });
  const speedSourceModule: SettingsSpeedSourceModule = createSettingsSpeedSourceModule({
    els,
    t,
    escapeHtml,
    state,
    renderSpeedReadout: ctx.renderSpeedReadout,
    onSaveError: showSettingsSaveError,
  });
  const gpsStatusModule: SettingsGpsStatusModule = createSettingsGpsStatusModule({
    els,
    t,
    escapeHtml,
    state,
    fmt,
    renderSpeedReadout: ctx.renderSpeedReadout,
  });

  function applyCarsPayload(payload: CarsPayload): void {
    state.cars = payload.cars;
    const requestedActiveCarId = payload.activeCarId;
    const hasRequestedActive = requestedActiveCarId
      ? state.cars.some((car) => car.id === requestedActiveCarId)
      : false;
    state.activeCarId = hasRequestedActive ? requestedActiveCarId : null;
    syncCarDependentUiState();
  }

  async function loadCarsFromServer(): Promise<void> {
    try {
      const payload = await getSettingsCars();
      applyCarsPayload(payload);
      renderCarList();
      syncActiveCarToInputs();
    } catch (_err) { /* ignore */ }
  }

  async function handleActivateCar(carId: string): Promise<void> {
    if (!carId) return;
    try {
      const result = await setActiveSettingsCar(carId);
      applyCarsPayload(result);
      syncActiveCarToInputs();
      renderCarList();
      ctx.renderSpectrum();
    } catch (_err) {
      window.alert(t("settings.car.activate_failed"));
    }
  }

  async function handleDeleteCar(carId: string): Promise<void> {
    if (!carId) return;
    const car = state.cars.find((entry) => entry.id === carId);
    const ok = window.confirm(t("settings.car.delete_confirm", { name: car?.name || "" }));
    if (!ok) return;
    try {
      const result = await deleteSettingsCar(carId);
      applyCarsPayload(result);
      syncActiveCarToInputs();
      renderCarList();
      ctx.renderSpectrum();
    } catch (_err) {
      window.alert(t("settings.car.delete_failed"));
    }
  }

  function renderCarList(): void {
    if (!els.carListBody) return;
    renderSettingsCarList(els.carListBody, {
      cars: state.cars,
      activeCarId: state.activeCarId,
      t,
      escapeHtml,
      fmt,
    });
  }

  function syncActiveCarToInputs(): void {
    const car = state.cars.find((entry) => entry.id === state.activeCarId);
    if (!car) {
      syncCarDependentUiState();
      return;
    }
    if (car.aspects && typeof car.aspects === "object") {
      for (const key of Object.keys(car.aspects)) {
        state.vehicleSettings[key] = car.aspects[key];
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
      if (action.type === "activate") {
        void handleActivateCar(action.carId);
        return;
      }
      void handleDeleteCar(action.carId);
    });
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    bindSettingsTabs(els);
    bindCarListEvents();
    analysisModule.bindHandlers();
    speedSourceModule.bindHandlers();
  }

  async function addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number>,
    variant?: string,
  ): Promise<void> {
    try {
      const fullAspects = { ...state.vehicleSettings, ...aspects };
      const payload: CarUpsertRequest = { name, type: carType, aspects: fullAspects };
      if (variant) payload.variant = variant;
      const result = await addSettingsCar(payload);
      if (Array.isArray(result.cars)) {
        applyCarsPayload(result);
        const newCar = state.cars[state.cars.length - 1];
        if (newCar) {
          const setResult = await setActiveSettingsCar(newCar.id);
          applyCarsPayload(setResult);
        }
        syncActiveCarToInputs();
        renderCarList();
        ctx.renderSpectrum();
      }
    } catch (_err) { /* ignore */ }
  }

  return {
    bindHandlers,
    syncSettingsInputs: analysisModule.syncSettingsInputs,
    loadSpeedSourceFromServer: speedSourceModule.loadSpeedSourceFromServer,
    loadAnalysisSettingsFromServer: analysisModule.loadAnalysisSettingsFromServer,
    loadCarsFromServer,
    renderCarList,
    syncActiveCarToInputs,
    saveAnalysisFromInputs: analysisModule.saveAnalysisFromInputs,
    saveSpeedSourceFromInputs: speedSourceModule.saveSpeedSourceFromInputs,
    saveHeaderManualSpeedFromInput: speedSourceModule.saveHeaderManualSpeedFromInput,
    addCarFromWizard,
    startGpsStatusPolling: gpsStatusModule.startGpsStatusPolling,
    stopGpsStatusPolling: gpsStatusModule.stopGpsStatusPolling,
  };
}
