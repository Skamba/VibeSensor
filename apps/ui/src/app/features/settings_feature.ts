import type { UiDomElements } from "../dom/ui_dom_registry";
import type { AppState } from "../state/ui_app_state";
import type { SpeedSourceStatusPayload } from "../../api/types";
import {
  addSettingsCar,
  deleteSettingsCar,
  getAnalysisSettings,
  getSettingsCars,
  getSettingsSpeedSource,
  getSpeedSourceStatus,
  setActiveSettingsCar,
  setAnalysisSettings,
  setSpeedOverride,
  updateSettingsSpeedSource,
} from "../../api";

export interface SettingsFeatureDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, any>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (n: number, digits?: number) => string;
  renderSpectrum: () => void;
  renderSpeedReadout: () => void;
}

export interface SettingsFeature {
  syncSettingsInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  loadAnalysisSettingsFromServer(): Promise<void>;
  loadCarsFromServer(): Promise<void>;
  renderCarList(): void;
  syncActiveCarToInputs(): void;
  saveAnalysisFromInputs(): void;
  saveSpeedSourceFromInputs(): void;
  saveHeaderManualSpeedFromInput(): void;
  bindSettingsTabs(): void;
  addCarFromWizard(name: string, carType: string, aspects: Record<string, number>): Promise<void>;
  startGpsStatusPolling(): void;
  stopGpsStatusPolling(): void;
}

export function createSettingsFeature(ctx: SettingsFeatureDeps): SettingsFeature {
  const { state, els, t, escapeHtml, fmt } = ctx;

  const GPS_POLL_FAST = 2_000;
  const GPS_POLL_SLOW = 10_000;
  let gpsPollTimer: ReturnType<typeof setTimeout> | null = null;

  function syncSettingsInputs(): void {
    if (els.wheelBandwidthInput) els.wheelBandwidthInput.value = String(state.vehicleSettings.wheel_bandwidth_pct);
    if (els.driveshaftBandwidthInput) els.driveshaftBandwidthInput.value = String(state.vehicleSettings.driveshaft_bandwidth_pct);
    if (els.engineBandwidthInput) els.engineBandwidthInput.value = String(state.vehicleSettings.engine_bandwidth_pct);
    if (els.speedUncertaintyInput) els.speedUncertaintyInput.value = String(state.vehicleSettings.speed_uncertainty_pct);
    if (els.tireDiameterUncertaintyInput) els.tireDiameterUncertaintyInput.value = String(state.vehicleSettings.tire_diameter_uncertainty_pct);
    if (els.finalDriveUncertaintyInput) els.finalDriveUncertaintyInput.value = String(state.vehicleSettings.final_drive_uncertainty_pct);
    if (els.gearUncertaintyInput) els.gearUncertaintyInput.value = String(state.vehicleSettings.gear_uncertainty_pct);
    if (els.minAbsBandHzInput) els.minAbsBandHzInput.value = String(state.vehicleSettings.min_abs_band_hz);
    if (els.maxBandHalfWidthInput) els.maxBandHalfWidthInput.value = String(state.vehicleSettings.max_band_half_width_pct);
  }

  async function syncSpeedSourceToServer(): Promise<void> {
    try {
      const payload: Record<string, unknown> = {
        speedSource: state.speedSource,
        manualSpeedKph: state.manualSpeedKph,
      };
      const staleVal = Number(els.staleTimeoutInput?.value);
      if (staleVal >= 3 && staleVal <= 120) payload.staleTimeoutS = staleVal;
      const fallbackVal = els.fallbackModeSelect?.value;
      if (fallbackVal) payload.fallbackMode = fallbackVal;
      await updateSettingsSpeedSource(payload);
      await setSpeedOverride(state.manualSpeedKph ?? null);
    } catch (_err) { /* ignore */ }
  }

  async function loadSpeedSourceFromServer(): Promise<void> {
    try {
      const payload = await getSettingsSpeedSource() as Record<string, any>;
      if (payload && typeof payload === "object") {
        if (typeof payload.speedSource === "string") state.speedSource = payload.speedSource;
        state.manualSpeedKph = typeof payload.manualSpeedKph === "number" ? payload.manualSpeedKph : null;
        if (typeof payload.staleTimeoutS === "number" && els.staleTimeoutInput) {
          els.staleTimeoutInput.value = String(payload.staleTimeoutS);
        }
        if (typeof payload.fallbackMode === "string" && els.fallbackModeSelect) {
          els.fallbackModeSelect.value = payload.fallbackMode;
        }
        syncSpeedSourceInputs();
        ctx.renderSpeedReadout();
      }
    } catch (_err) { /* ignore */ }
  }

  function syncSpeedSourceInputs(): void {
    const radios = document.querySelectorAll<HTMLInputElement>('input[name="speedSourceRadio"]');
    radios.forEach((r) => { r.checked = r.value === state.speedSource; });
    if (els.manualSpeedInput) els.manualSpeedInput.value = state.manualSpeedKph != null ? String(state.manualSpeedKph) : "";
    if (els.headerManualSpeedInput) {
      els.headerManualSpeedInput.value = state.manualSpeedKph != null ? String(state.manualSpeedKph) : "";
    }
    if (els.headerManualOverrideGroup) {
      els.headerManualOverrideGroup.hidden = state.speedSource !== "manual";
    }
  }

  async function syncAnalysisSettingsToServer(): Promise<void> {
    const payload: Record<string, number> = {
      tire_width_mm: state.vehicleSettings.tire_width_mm,
      tire_aspect_pct: state.vehicleSettings.tire_aspect_pct,
      rim_in: state.vehicleSettings.rim_in,
      final_drive_ratio: state.vehicleSettings.final_drive_ratio,
      current_gear_ratio: state.vehicleSettings.current_gear_ratio,
      wheel_bandwidth_pct: state.vehicleSettings.wheel_bandwidth_pct,
      driveshaft_bandwidth_pct: state.vehicleSettings.driveshaft_bandwidth_pct,
      engine_bandwidth_pct: state.vehicleSettings.engine_bandwidth_pct,
      speed_uncertainty_pct: state.vehicleSettings.speed_uncertainty_pct,
      tire_diameter_uncertainty_pct: state.vehicleSettings.tire_diameter_uncertainty_pct,
      final_drive_uncertainty_pct: state.vehicleSettings.final_drive_uncertainty_pct,
      gear_uncertainty_pct: state.vehicleSettings.gear_uncertainty_pct,
      min_abs_band_hz: state.vehicleSettings.min_abs_band_hz,
      max_band_half_width_pct: state.vehicleSettings.max_band_half_width_pct,
    };
    try {
      await setAnalysisSettings(payload);
    } catch (_err) { /* ignore */ }
  }

  async function loadAnalysisSettingsFromServer(): Promise<void> {
    try {
      const serverSettings = await getAnalysisSettings();
      if (serverSettings && typeof serverSettings === "object") {
        for (const key of Object.keys(serverSettings)) {
          if (typeof serverSettings[key] === "number") state.vehicleSettings[key] = serverSettings[key];
        }
        syncSettingsInputs();
        ctx.renderSpectrum();
      }
    } catch (_err) { /* ignore */ }
  }

  async function loadCarsFromServer(): Promise<void> {
    try {
      const payload = await getSettingsCars() as Record<string, any>;
      if (Array.isArray(payload?.cars)) {
        state.cars = payload.cars;
        state.activeCarId = payload.activeCarId || (payload.cars[0]?.id ?? null);
        renderCarList();
        syncActiveCarToInputs();
      }
    } catch (_err) { /* ignore */ }
  }

  function renderCarList(): void {
    if (!els.carListBody) return;
    if (!state.cars.length) {
      els.carListBody.innerHTML = `<tr><td colspan="7">${escapeHtml(t("settings.car.no_cars"))}</td></tr>`;
      return;
    }
    els.carListBody.innerHTML = state.cars.map((car) => {
      const isActive = car.id === state.activeCarId;
      const a = car.aspects || {};
      const tireStr = `${a.tire_width_mm || "?"}/${a.tire_aspect_pct || "?"}R${a.rim_in || "?"}`;
      const driveStr = `${fmt(a.final_drive_ratio, 2)}`;
      const gearStr = `${fmt(a.current_gear_ratio, 2)}`;
      return `<tr data-car-id="${escapeHtml(car.id)}"><td><span class="car-active-pill ${isActive ? "active" : "inactive"}">${isActive ? escapeHtml(t("settings.car.active_label")) : escapeHtml(t("settings.car.inactive_label"))}</span></td><td><strong>${escapeHtml(car.name)}</strong></td><td>${escapeHtml(car.type)}</td><td><code>${escapeHtml(tireStr)}</code></td><td>${escapeHtml(driveStr)}</td><td>${escapeHtml(gearStr)}</td><td class="car-list-actions">${isActive ? "" : `<button class="btn btn--success car-activate-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.activate"))}</button>`}<button class="btn btn--danger car-delete-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.delete"))}</button></td></tr>`;
    }).join("");

    els.carListBody.querySelectorAll(".car-activate-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const carId = btn.getAttribute("data-car-id");
        if (!carId) return;
        try {
          const result = await setActiveSettingsCar(carId) as Record<string, any>;
          if (result?.cars) {
            state.cars = result.cars;
            state.activeCarId = result.activeCarId;
            syncActiveCarToInputs();
            renderCarList();
            ctx.renderSpectrum();
          }
        } catch (_err) { /* ignore */ }
      });
    });

    els.carListBody.querySelectorAll(".car-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const carId = btn.getAttribute("data-car-id");
        if (!carId) return;
        const car = state.cars.find((c) => c.id === carId);
        if (state.cars.length <= 1) {
          window.alert(t("settings.car.cannot_delete_last"));
          return;
        }
        const ok = window.confirm(t("settings.car.delete_confirm", { name: car?.name || "" }));
        if (!ok) return;
        try {
          const result = await deleteSettingsCar(carId) as Record<string, any>;
          if (result?.cars) {
            state.cars = result.cars;
            state.activeCarId = result.activeCarId;
            syncActiveCarToInputs();
            renderCarList();
            ctx.renderSpectrum();
          }
        } catch (_err) { /* ignore */ }
      });
    });
  }

  function syncActiveCarToInputs(): void {
    const car = state.cars.find((c) => c.id === state.activeCarId);
    if (!car) return;
    if (car.aspects && typeof car.aspects === "object") {
      for (const key of Object.keys(car.aspects)) {
        if (typeof car.aspects[key] === "number") state.vehicleSettings[key] = car.aspects[key];
      }
    }
    syncSettingsInputs();
  }

  function saveAnalysisFromInputs(): void {
    const wheelBandwidth = Number(els.wheelBandwidthInput?.value);
    const driveshaftBandwidth = Number(els.driveshaftBandwidthInput?.value);
    const engineBandwidth = Number(els.engineBandwidthInput?.value);
    const speedUncertainty = Number(els.speedUncertaintyInput?.value);
    const tireDiameterUncertainty = Number(els.tireDiameterUncertaintyInput?.value);
    const finalDriveUncertainty = Number(els.finalDriveUncertaintyInput?.value);
    const gearUncertainty = Number(els.gearUncertaintyInput?.value);
    const minAbsBandHz = Number(els.minAbsBandHzInput?.value);
    const maxBandHalfWidth = Number(els.maxBandHalfWidthInput?.value);
    const validBandwidths = wheelBandwidth > 0 && wheelBandwidth <= 40 && driveshaftBandwidth > 0 && driveshaftBandwidth <= 40 && engineBandwidth > 0 && engineBandwidth <= 40;
    const validUncertainty = speedUncertainty >= 0 && speedUncertainty <= 20 && tireDiameterUncertainty >= 0 && tireDiameterUncertainty <= 20 && finalDriveUncertainty >= 0 && finalDriveUncertainty <= 10 && gearUncertainty >= 0 && gearUncertainty <= 20;
    const validBandLimits = minAbsBandHz >= 0 && minAbsBandHz <= 10 && maxBandHalfWidth > 0 && maxBandHalfWidth <= 25;
    if (!validBandwidths || !validUncertainty || !validBandLimits) return;
    state.vehicleSettings.wheel_bandwidth_pct = wheelBandwidth;
    state.vehicleSettings.driveshaft_bandwidth_pct = driveshaftBandwidth;
    state.vehicleSettings.engine_bandwidth_pct = engineBandwidth;
    state.vehicleSettings.speed_uncertainty_pct = speedUncertainty;
    state.vehicleSettings.tire_diameter_uncertainty_pct = tireDiameterUncertainty;
    state.vehicleSettings.final_drive_uncertainty_pct = finalDriveUncertainty;
    state.vehicleSettings.gear_uncertainty_pct = gearUncertainty;
    state.vehicleSettings.min_abs_band_hz = minAbsBandHz;
    state.vehicleSettings.max_band_half_width_pct = maxBandHalfWidth;
    void syncAnalysisSettingsToServer();
    ctx.renderSpectrum();
  }

  function saveSpeedSourceFromInputs(): void {
    const radios = document.querySelectorAll<HTMLInputElement>('input[name="speedSourceRadio"]');
    let src = "gps";
    radios.forEach((r) => { if (r.checked) src = r.value; });
    const manual = Number(els.manualSpeedInput?.value);
    state.speedSource = src;
    state.manualSpeedKph = Number.isFinite(manual) && manual > 0 ? manual : null;
    void syncSpeedSourceToServer();
    ctx.renderSpeedReadout();
  }

  function saveHeaderManualSpeedFromInput(): void {
    const manual = Number(els.headerManualSpeedInput?.value);
    state.speedSource = "manual";
    state.manualSpeedKph = Number.isFinite(manual) && manual > 0 ? manual : null;
    syncSpeedSourceInputs();
    void syncSpeedSourceToServer();
    ctx.renderSpeedReadout();
  }

  function setActiveSettingsTab(tabId: string): void {
    els.settingsTabs.forEach((tab) => {
      const isActive = tab.getAttribute("data-settings-tab") === tabId;
      tab.classList.toggle("active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
      tab.tabIndex = isActive ? 0 : -1;
    });
    els.settingsTabPanels.forEach((panel) => {
      const isActive = panel.id === tabId;
      panel.classList.toggle("active", isActive);
      panel.hidden = !isActive;
    });
  }

  function bindSettingsTabs(): void {
    els.settingsTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const tabId = tab.getAttribute("data-settings-tab");
        if (tabId) setActiveSettingsTab(tabId);
      });
    });
  }

  async function addCarFromWizard(name: string, carType: string, aspects: Record<string, number>): Promise<void> {
    try {
      const fullAspects = { ...state.vehicleSettings, ...aspects };
      const result = await addSettingsCar({ name, type: carType, aspects: fullAspects }) as Record<string, any>;
      if (result?.cars) {
        state.cars = result.cars;
        const newCar = result.cars[result.cars.length - 1];
        if (newCar) {
          const setResult = await setActiveSettingsCar(newCar.id) as Record<string, any>;
          if (setResult?.cars) {
            state.cars = setResult.cars;
            state.activeCarId = setResult.activeCarId;
          }
        }
        syncActiveCarToInputs();
        renderCarList();
        ctx.renderSpectrum();
      }
    } catch (_err) { /* ignore */ }
  }

  // -- GPS status polling & rendering -----------------------------------------

  function connectionStateLabel(cs: string): string {
    const map: Record<string, string> = {
      disabled: t("settings.speed.state_disabled"),
      disconnected: t("settings.speed.state_disconnected"),
      connected: t("settings.speed.state_connected"),
      stale: t("settings.speed.state_stale"),
    };
    return map[cs] ?? cs;
  }

  function speedKmhInSelectedUnit(speedKmh: number | null): number | null {
    if (typeof speedKmh !== "number" || !Number.isFinite(speedKmh)) return null;
    return state.speedUnit === "mps" ? speedKmh / 3.6 : speedKmh;
  }

  function selectedSpeedUnitLabel(): string {
    return state.speedUnit === "mps" ? t("speed.unit.mps") : t("speed.unit.kmh");
  }

  function renderGpsStatus(status: SpeedSourceStatusPayload): void {
    if (els.headerGpsStatus) {
      const stateLabel = connectionStateLabel(status.connection_state);
      const speed = speedKmhInSelectedUnit(status.effective_speed_kmh);
      const speedText = speed != null ? ` ${fmt(speed, 1)} ${selectedSpeedUnitLabel()}` : "";
      els.headerGpsStatus.textContent = `GPS ${stateLabel}${speedText}`;
      const variant = status.connection_state === "connected"
        ? "ok"
        : (status.connection_state === "stale" ? "warn" : "muted");
      els.headerGpsStatus.className = `pill pill--${variant}`;
    }
    if (els.gpsStatusState) els.gpsStatusState.textContent = connectionStateLabel(status.connection_state);
    if (els.gpsStatusDevice) els.gpsStatusDevice.textContent = status.device ?? "--";
    if (els.gpsStatusLastUpdate) {
      els.gpsStatusLastUpdate.textContent = status.last_update_age_s != null
        ? t("settings.speed.last_update_value", {
          value: {
            number: status.last_update_age_s,
            options: { minimumFractionDigits: 1, maximumFractionDigits: 1 },
          },
        })
        : t("settings.speed.last_update_never");
    }
    if (els.gpsStatusRawSpeed) {
      const rawSpeed = speedKmhInSelectedUnit(status.raw_speed_kmh);
      els.gpsStatusRawSpeed.textContent = rawSpeed != null ? `${fmt(rawSpeed, 1)} ${selectedSpeedUnitLabel()}` : "--";
    }
    if (els.gpsStatusEffectiveSpeed) {
      const effectiveSpeed = speedKmhInSelectedUnit(status.effective_speed_kmh);
      els.gpsStatusEffectiveSpeed.textContent = effectiveSpeed != null
        ? `${fmt(effectiveSpeed, 1)} ${selectedSpeedUnitLabel()}`
        : "--";
    }
    if (els.gpsStatusLastError) {
      els.gpsStatusLastError.textContent = status.last_error ?? "--";
    }
    if (els.gpsStatusReconnect) {
      els.gpsStatusReconnect.textContent = status.reconnect_delay_s != null ? `${fmt(status.reconnect_delay_s, 1)}s` : "--";
    }
    if (els.gpsStatusFallback) {
      els.gpsStatusFallback.textContent = status.fallback_active ? t("settings.speed.fallback_yes") : t("settings.speed.fallback_no");
    }
  }

  async function pollGpsStatus(): Promise<void> {
    try {
      const status = await getSpeedSourceStatus();
      state.gpsFallbackActive = status.fallback_active
        || (
          state.speedSource !== "manual"
          && typeof state.manualSpeedKph === "number"
          && state.manualSpeedKph > 0
          && status.connection_state !== "connected"
        );
      renderGpsStatus(status);
      ctx.renderSpeedReadout();
      const interval = status.connection_state === "connected" ? GPS_POLL_FAST : GPS_POLL_SLOW;
      gpsPollTimer = setTimeout(() => void pollGpsStatus(), interval);
    } catch {
      gpsPollTimer = setTimeout(() => void pollGpsStatus(), GPS_POLL_SLOW);
    }
  }

  function startGpsStatusPolling(): void {
    if (gpsPollTimer !== null) return;
    void pollGpsStatus();
  }

  function stopGpsStatusPolling(): void {
    if (gpsPollTimer !== null) {
      clearTimeout(gpsPollTimer);
      gpsPollTimer = null;
    }
  }

  return {
    syncSettingsInputs,
    loadSpeedSourceFromServer,
    loadAnalysisSettingsFromServer,
    loadCarsFromServer,
    renderCarList,
    syncActiveCarToInputs,
    saveAnalysisFromInputs,
    saveSpeedSourceFromInputs,
    saveHeaderManualSpeedFromInput,
    bindSettingsTabs,
    addCarFromWizard,
    startGpsStatusPolling,
    stopGpsStatusPolling,
  };
}
