import type { SpeedSourceKind, SpeedSourcePayload, SpeedSourceRequest } from "../../api/types";
import { getSettingsSpeedSource, updateSettingsSpeedSource } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import {
  deriveDisplayedSpeedSourceMode,
  isManualLikeSpeedSource,
  resolveEffectiveSpeedSource,
} from "../speed_source_state";
import type { SettingsState } from "../ui_app_state";

const SPEED_SOURCE_KINDS = ["gps", "manual", "obd2"] as const satisfies readonly SpeedSourceKind[];

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  renderSpeedReadout: () => void;
  onSaveError: (error: unknown) => void;
}

export interface SettingsSpeedSourceModule {
  bindHandlers(): void;
  syncSpeedSourceSelectionUi(): void;
  syncSpeedSourceInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  saveSpeedSourceFromInputs(): void;
}

export function createSettingsSpeedSourceModule(ctx: SettingsSpeedSourceModuleDeps): SettingsSpeedSourceModule {
  const { settings, els, t } = ctx;
  let speedSourceDraftDirty = false;

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

  function selectedSpeedUnitLabel(): string {
    return ctx.getSpeedUnit() === "mps" ? t("speed.unit.mps") : t("speed.unit.kmh");
  }

  function speedKphInSelectedUnit(speedKmh: number | null): number | null {
    if (speedKmh === null || !Number.isFinite(speedKmh)) return null;
    return ctx.getSpeedUnit() === "mps" ? speedKmh / 3.6 : speedKmh;
  }

  function formatSpeedValue(speedKmh: number | null): string {
    const speed = speedKphInSelectedUnit(speedKmh);
    return speed != null ? `${ctx.fmt(speed, 1)} ${selectedSpeedUnitLabel()}` : "--";
  }

  function activeSourceLabel(): string {
    const effectiveSource = resolveEffectiveSpeedSource(settings);
    if (effectiveSource === "fallback_manual") {
      return t("settings.speed.current_source_fallback_manual");
    }
    if (effectiveSource === "manual") {
      return t("settings.speed.manual");
    }
    if (effectiveSource === "gps" || effectiveSource == null) {
      return t("settings.speed.gps");
    }
    if (effectiveSource === "obd2") {
      return t("dashboard.rotational.source.obd2");
    }
    return effectiveSource;
  }

  function activeEffectiveSpeedKph(): number | null {
    return isManualLikeSpeedSource(resolveEffectiveSpeedSource(settings))
      ? settings.manualSpeedKph
      : settings.gpsEffectiveSpeedKph;
  }

  function applyDisplayedModeToRadios(displayedMode: "gps" | "manual"): void {
    els.speedSourceRadios.forEach((radio) => {
      radio.checked = radio.value === displayedMode;
    });
  }

  function selectedSpeedSourceMode(): "gps" | "manual" {
    const checkedRadio = els.speedSourceRadios.find((radio) => radio.checked);
    if (checkedRadio?.value === "manual") return "manual";
    if (checkedRadio?.value === "gps") return "gps";
    return deriveDisplayedSpeedSourceMode(settings);
  }

  function updateSpeedSourceSummary(): void {
    if (els.speedSourceCurrentSource) {
      els.speedSourceCurrentSource.textContent = activeSourceLabel();
    }
    if (els.speedSourceEffectiveSpeed) {
      els.speedSourceEffectiveSpeed.textContent = formatSpeedValue(activeEffectiveSpeedKph());
    }
  }

  function syncSpeedSourceSelectionUi(): void {
    const displayedMode = deriveDisplayedSpeedSourceMode(settings);
    if (!speedSourceDraftDirty) {
      applyDisplayedModeToRadios(displayedMode);
    }
    const selectedMode = selectedSpeedSourceMode();
    els.speedSourceChoiceGps?.classList.toggle("speed-source-choice--selected", selectedMode === "gps");
    els.speedSourceChoiceManual?.classList.toggle("speed-source-choice--selected", selectedMode === "manual");
    if (els.manualSpeedConfig) {
      els.manualSpeedConfig.hidden = selectedMode !== "manual";
    }
    if (els.gpsFallbackPanel) {
      els.gpsFallbackPanel.hidden = selectedMode !== "gps";
    }
    updateSpeedSourceSummary();
  }

  function syncSpeedSourceInputs(): void {
    speedSourceDraftDirty = false;
    applyDisplayedModeToRadios(deriveDisplayedSpeedSourceMode(settings));
    if (els.manualSpeedInput) {
      els.manualSpeedInput.value = settings.manualSpeedKph != null ? String(settings.manualSpeedKph) : "";
    }
    syncSpeedSourceSelectionUi();
  }

  function applySpeedSourcePayload(payload: SpeedSourcePayload): void {
    settings.speedSource = payload.speed_source;
    settings.manualSpeedKph = payload.manual_speed_kph;
    settings.resolvedSpeedSource = null;
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

  function bindHandlers(): void {
    els.speedSourceRadios.forEach((radio) => {
      radio.addEventListener("change", () => {
        speedSourceDraftDirty = true;
        syncSpeedSourceSelectionUi();
      });
    });
    els.saveSpeedSourceBtn?.addEventListener("click", saveSpeedSourceFromInputs);
  }

  return {
    bindHandlers,
    syncSpeedSourceSelectionUi,
    syncSpeedSourceInputs,
    loadSpeedSourceFromServer,
    saveSpeedSourceFromInputs,
  };
}
