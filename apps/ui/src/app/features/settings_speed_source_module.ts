import type { SpeedSourceKind, SpeedSourcePayload, SpeedSourceRequest } from "../../api/types";
import { getSettingsSpeedSource, updateSettingsSpeedSource } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";

const SPEED_SOURCE_KINDS = ["gps", "manual", "obd2"] as const satisfies readonly SpeedSourceKind[];

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
  settings: SettingsState;
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
  const { settings, els } = ctx;

  function isSpeedSourceKind(value: string): value is SpeedSourceKind {
    return SPEED_SOURCE_KINDS.some((kind) => kind === value);
  }

  function parseManualSpeedKph(rawValue: number): number | null {
    return Number.isFinite(rawValue) && rawValue > 0 && rawValue <= 500 ? rawValue : null;
  }

  function applyStaleTimeoutFromInput(payload: SpeedSourceRequest): void {
    const staleVal = Number(els.staleTimeoutInput?.value);
    if (staleVal >= 3 && staleVal <= 120) payload.stale_timeout_s = staleVal;
  }

  function syncSpeedSourceInputs(): void {
    els.speedSourceRadios.forEach((radio) => {
      radio.checked = radio.value === settings.speedSource;
    });
    if (els.manualSpeedInput) {
      els.manualSpeedInput.value = settings.manualSpeedKph != null ? String(settings.manualSpeedKph) : "";
    }
    if (els.headerManualSpeedInput) {
      els.headerManualSpeedInput.value = settings.manualSpeedKph != null ? String(settings.manualSpeedKph) : "";
    }
    if (els.headerManualOverrideGroup) {
      els.headerManualOverrideGroup.hidden = settings.speedSource !== "manual";
    }
  }

  function applySpeedSourcePayload(payload: SpeedSourcePayload): void {
    settings.speedSource = payload.speed_source;
    settings.manualSpeedKph = payload.manual_speed_kph;
    if (els.staleTimeoutInput) els.staleTimeoutInput.value = String(payload.stale_timeout_s);
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
    const payload: SpeedSourceRequest = {
      speed_source: src,
      manual_speed_kph: parseManualSpeedKph(Number(els.manualSpeedInput?.value)),
    };
    applyStaleTimeoutFromInput(payload);
    void syncSpeedSourceToServer(payload);
  }

  function saveHeaderManualSpeedFromInput(): void {
    const payload: SpeedSourceRequest = {
      speed_source: "manual",
      manual_speed_kph: parseManualSpeedKph(Number(els.headerManualSpeedInput?.value)),
    };
    applyStaleTimeoutFromInput(payload);
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
