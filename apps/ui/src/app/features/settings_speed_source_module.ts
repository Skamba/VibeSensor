import type { SpeedSourceKind, SpeedSourcePayload, SpeedSourceRequest } from "../../api/types";
import { getSettingsSpeedSource, updateSettingsSpeedSource } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { AppState } from "../ui_app_state";

const SPEED_SOURCE_KINDS = ["gps", "manual", "obd2"] as const satisfies readonly SpeedSourceKind[];

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
  state: AppState;
  renderSpeedReadout: () => void;
  onSaveError: (error: unknown) => void;
}

export interface SettingsSpeedSourceModule {
  bindHandlers(): void;
  syncSpeedSourceInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  saveSpeedSourceFromInputs(): void;
  saveHeaderManualSpeedFromInput(): void;
}

export function createSettingsSpeedSourceModule(ctx: SettingsSpeedSourceModuleDeps): SettingsSpeedSourceModule {
  const { state, els } = ctx;

  function isSpeedSourceKind(value: string): value is SpeedSourceKind {
    return SPEED_SOURCE_KINDS.some((kind) => kind === value);
  }

  function syncSpeedSourceInputs(): void {
    els.speedSourceRadios.forEach((radio) => {
      radio.checked = radio.value === state.speedSource;
    });
    if (els.manualSpeedInput) els.manualSpeedInput.value = state.manualSpeedKph != null ? String(state.manualSpeedKph) : "";
    if (els.headerManualSpeedInput) {
      els.headerManualSpeedInput.value = state.manualSpeedKph != null ? String(state.manualSpeedKph) : "";
    }
    if (els.headerManualOverrideGroup) {
      els.headerManualOverrideGroup.hidden = state.speedSource !== "manual";
    }
  }

  function applySpeedSourcePayload(payload: SpeedSourcePayload): void {
    state.speedSource = payload.speedSource;
    state.manualSpeedKph = payload.manualSpeedKph;
    if (els.staleTimeoutInput) els.staleTimeoutInput.value = String(payload.staleTimeoutS);
    syncSpeedSourceInputs();
    ctx.renderSpeedReadout();
  }

  async function syncSpeedSourceToServer(payload: SpeedSourceRequest): Promise<void> {
    try {
      const saved = await updateSettingsSpeedSource(payload);
      applySpeedSourcePayload(saved);
    } catch (error) {
      void loadSpeedSourceFromServer();
      ctx.onSaveError(error);
    }
  }

  async function loadSpeedSourceFromServer(): Promise<void> {
    try {
      const payload = await getSettingsSpeedSource();
      applySpeedSourcePayload(payload);
    } catch (_err) { /* ignore */ }
  }

  function saveSpeedSourceFromInputs(): void {
    let src: SpeedSourceKind = "gps";
    els.speedSourceRadios.forEach((radio) => {
      if (radio.checked && isSpeedSourceKind(radio.value)) src = radio.value;
    });
    const manual = Number(els.manualSpeedInput?.value);
    const payload: SpeedSourceRequest = {
      speedSource: src,
      manualSpeedKph: Number.isFinite(manual) && manual > 0 && manual <= 500 ? manual : null,
    };
    const staleVal = Number(els.staleTimeoutInput?.value);
    if (staleVal >= 3 && staleVal <= 120) payload.staleTimeoutS = staleVal;
    void syncSpeedSourceToServer(payload);
  }

  function saveHeaderManualSpeedFromInput(): void {
    const manual = Number(els.headerManualSpeedInput?.value);
    const payload: SpeedSourceRequest = {
      speedSource: "manual",
      manualSpeedKph: Number.isFinite(manual) && manual > 0 && manual <= 500 ? manual : null,
    };
    const staleVal = Number(els.staleTimeoutInput?.value);
    if (staleVal >= 3 && staleVal <= 120) payload.staleTimeoutS = staleVal;
    void syncSpeedSourceToServer(payload);
  }

  function bindHandlers(): void {
    els.saveSpeedSourceBtn?.addEventListener("click", saveSpeedSourceFromInputs);
    els.headerManualSpeedSaveBtn?.addEventListener("click", saveHeaderManualSpeedFromInput);
    els.headerManualSpeedInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        saveHeaderManualSpeedFromInput();
      }
    });
  }

  return {
    bindHandlers,
    syncSpeedSourceInputs,
    loadSpeedSourceFromServer,
    saveSpeedSourceFromInputs,
    saveHeaderManualSpeedFromInput,
  };
}
