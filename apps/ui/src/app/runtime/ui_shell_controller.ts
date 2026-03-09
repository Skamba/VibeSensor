import * as I18N from "../../i18n";
import { formatIntLocale, fmt } from "../../format";
import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "../../api/settings";
import type { AppFeatureBundle } from "../app_feature_bundle";
import type { UiDomElements } from "../dom/ui_dom_registry";
import type { AppState } from "../state/ui_app_state";

const DEFAULT_VIEW_ID = "dashboardView";

const WS_KEY_BY_STATE: Record<string, string> = {
  connecting: "ws.connecting",
  connected: "ws.connected",
  reconnecting: "ws.reconnecting",
  stale: "ws.stale",
  no_data: "ws.no_data",
};

const WS_VARIANT_BY_STATE: Record<string, string> = {
  connecting: "muted",
  connected: "ok",
  reconnecting: "warn",
  stale: "bad",
  no_data: "muted",
};

const WS_BANNER_CFG: Record<string, { key: string; cls: string }> = {
  reconnecting: { key: "ws.banner.reconnecting", cls: "connection-banner--bad" },
  stale: { key: "ws.banner.stale", cls: "connection-banner--warn" },
  connecting: { key: "ws.banner.connecting", cls: "connection-banner--muted" },
};

type UiShellControllerDeps = {
  state: AppState;
  els: UiDomElements;
};

export class UiShellController {
  private readonly state: AppState;

  private readonly els: UiDomElements;

  private features: AppFeatureBundle | null = null;

  private renderSpectrumChart: (() => void) | null = null;

  private updateSpectrumOverlayState: (() => void) | null = null;

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    this.els = deps.els;
  }

  attachFeatures(features: AppFeatureBundle): void {
    this.features = features;
  }

  attachSpectrumHooks(deps: {
    renderSpectrum: () => void;
    updateSpectrumOverlay: () => void;
  }): void {
    this.renderSpectrumChart = deps.renderSpectrum;
    this.updateSpectrumOverlayState = deps.updateSpectrumOverlay;
  }

  t(key: string, vars?: Record<string, unknown>): string {
    return I18N.get(this.state.lang, key, vars);
  }

  localFormatInt(value: number): string {
    return formatIntLocale(value, this.state.lang);
  }

  setStatValue(container: HTMLElement | null, value: string | number): void {
    const valueEl = container?.querySelector?.("[data-value]");
    if (valueEl) {
      valueEl.textContent = String(value);
      return;
    }
    if (container) {
      container.textContent = String(value);
    }
  }

  setPillState(el: HTMLElement | null, variant: string, text: string): void {
    if (!el) return;
    el.className = `pill pill--${variant}`;
    el.textContent = text;
  }

  renderSpeedReadout(): void {
    if (!this.els.speed) return;
    const unitLabel = this.selectedSpeedUnitLabel();
    if (typeof this.state.speedMps === "number" && Number.isFinite(this.state.speedMps)) {
      const value = this.speedValueInSelectedUnit(this.state.speedMps);
      const isManualSource = this.state.speedSource === "manual"
        && typeof this.state.manualSpeedKph === "number"
        && this.state.manualSpeedKph > 0;
      const isFallbackOverride = this.state.gpsFallbackActive
        || this.state.rotationalSpeeds?.basis_speed_source === "fallback_manual";
      const isOverride = isManualSource || isFallbackOverride;
      this.els.speed.textContent = this.t(isOverride ? "speed.override" : "speed.gps", {
        value: fmt(value!, 1),
        unit: unitLabel,
      });
      return;
    }
    this.els.speed.textContent = this.t("speed.none", { unit: unitLabel });
  }

  renderWsState(): void {
    if (this.state.payloadError) {
      this.setPillState(this.els.linkState, "bad", this.t("ws.payload_error_pill"));
      return;
    }
    this.setPillState(
      this.els.linkState,
      WS_VARIANT_BY_STATE[this.state.wsState] || "muted",
      this.t(WS_KEY_BY_STATE[this.state.wsState] || "ws.connecting"),
    );

    const banner = this.els.connectionBanner;
    if (banner) {
      const cfg = WS_BANNER_CFG[this.state.wsState];
      if (cfg) {
        banner.hidden = false;
        banner.textContent = this.t(cfg.key);
        banner.className = `connection-banner ${cfg.cls}`;
      } else {
        banner.hidden = true;
        banner.textContent = "";
        banner.className = "connection-banner";
      }
    }

    const wrap = document.querySelector(".wrap");
    if (wrap) {
      const degraded = this.state.wsState === "reconnecting" || this.state.wsState === "stale";
      wrap.classList.toggle("wrap--stale", degraded);
    }
  }

  renderCarSelectionWarning(): void {
    const banner = this.els.carSelectionBanner;
    if (!banner) return;
    const hasValidActiveCar = Boolean(
      this.state.activeCarId && this.state.cars.some((car) => car.id === this.state.activeCarId),
    );
    if (hasValidActiveCar) {
      banner.hidden = true;
      banner.textContent = "";
      return;
    }
    banner.hidden = false;
    banner.textContent = `${this.t("header.no_car_selected")} ${this.t("header.no_car_selected_action")}`;
  }

  setActiveView(viewId: string): void {
    const valid = this.els.views.some((view) => view.id === viewId);
    this.state.activeViewId = valid ? viewId : DEFAULT_VIEW_ID;
    for (const view of this.els.views) {
      const isActive = view.id === this.state.activeViewId;
      view.classList.toggle("active", isActive);
      view.hidden = !isActive;
    }
    for (const button of this.els.menuButtons) {
      const isActive = button.dataset.view === this.state.activeViewId;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
      button.tabIndex = isActive ? 0 : -1;
    }
    if (this.state.activeViewId === DEFAULT_VIEW_ID && this.state.spectrumPlot) {
      this.state.spectrumPlot.resize();
    }
  }

  applyLanguage(forceReloadInsights = false): void {
    const features = this.requireFeatures();
    document.documentElement.lang = this.state.lang;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (key) element.textContent = this.t(key);
    });
    if (this.els.languageSelect) this.els.languageSelect.value = this.state.lang;
    if (this.els.speedUnitSelect) this.els.speedUnitSelect.value = this.state.speedUnit;
    this.state.locationOptions = features.realtime.buildLocationOptions(this.state.locationCodes);
    this.state.sensorsSettingsSignature = "";
    features.realtime.maybeRenderSensorsSettingsList(true);
    this.renderSpeedReadout();
    features.realtime.renderLoggingStatus();
    features.history.renderHistoryTable();
    this.renderWsState();
    this.renderCarSelectionWarning();
    if (this.state.spectrumPlot) {
      this.state.spectrumPlot.destroy();
      this.state.spectrumPlot = null;
      this.renderSpectrumChart?.();
    }
    if (forceReloadInsights) {
      features.history.reloadExpandedRunOnLanguageChange();
    }
    this.updateSpectrumOverlayState?.();
  }

  bindUiEvents(): void {
    this.bindMenuEvents();
    this.bindFeatureEvents();
    this.bindHistoryTableEvents();
    this.bindPreferenceEvents();
  }

  async hydratePersistedPreferences(): Promise<void> {
    try {
      const languageResponse = await getSettingsLanguage();
      if (languageResponse?.language) {
        this.state.lang = I18N.normalizeLang(languageResponse.language);
        this.applyLanguage(true);
      }
    } catch (error) {
      console.warn("Failed to load persisted language", error);
    }
    try {
      const speedUnitResponse = await getSettingsSpeedUnit();
      if (speedUnitResponse?.speedUnit) {
        this.state.speedUnit = this.normalizeSpeedUnit(speedUnitResponse.speedUnit);
        if (this.els.speedUnitSelect) {
          this.els.speedUnitSelect.value = this.state.speedUnit;
        }
        this.renderSpeedReadout();
      }
    } catch (error) {
      console.warn("Failed to load persisted speed unit", error);
    }
  }

  private normalizeSpeedUnit(raw: string): string {
    return raw === "mps" ? "mps" : "kmh";
  }

  private saveLanguage(lang: string): void {
    this.state.lang = I18N.normalizeLang(lang);
    void setSettingsLanguage(this.state.lang).catch(() => {});
  }

  private saveSpeedUnit(unit: string): void {
    this.state.speedUnit = this.normalizeSpeedUnit(unit);
    void setSettingsSpeedUnit(this.state.speedUnit).catch(() => {});
  }

  private speedValueInSelectedUnit(speedMps: number | null): number | null {
    if (!(typeof speedMps === "number") || !Number.isFinite(speedMps)) return null;
    return this.state.speedUnit === "mps" ? speedMps : speedMps * 3.6;
  }

  private selectedSpeedUnitLabel(): string {
    return this.state.speedUnit === "mps" ? this.t("speed.unit.mps") : this.t("speed.unit.kmh");
  }

  private activateMenuTabByIndex(index: number): void {
    if (!this.els.menuButtons.length) return;
    const safeIndex = ((index % this.els.menuButtons.length) + this.els.menuButtons.length)
      % this.els.menuButtons.length;
    const button = this.els.menuButtons[safeIndex];
    const viewId = button.dataset.view;
    if (!viewId) return;
    this.setActiveView(viewId);
    button.focus();
  }

  private bindMenuEvents(): void {
    this.els.menuButtons.forEach((button, index) => {
      const activate = (): void => {
        const viewId = button.dataset.view;
        if (viewId) this.setActiveView(viewId);
      };
      button.addEventListener("click", activate);
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
          return;
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          this.activateMenuTabByIndex(index + 1);
          return;
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          this.activateMenuTabByIndex(index - 1);
          return;
        }
        if (event.key === "Home") {
          event.preventDefault();
          this.activateMenuTabByIndex(0);
          return;
        }
        if (event.key === "End") {
          event.preventDefault();
          this.activateMenuTabByIndex(this.els.menuButtons.length - 1);
        }
      });
    });
  }

  private bindFeatureEvents(): void {
    const features = this.requireFeatures();
    features.settings.bindSettingsTabs();
    features.cars.bindWizardHandlers();
    features.update.bindUpdateHandlers();
    features.espFlash.bindHandlers();
    this.els.saveAnalysisBtn?.addEventListener("click", features.settings.saveAnalysisFromInputs);
    this.els.saveSpeedSourceBtn?.addEventListener(
      "click",
      features.settings.saveSpeedSourceFromInputs,
    );
    this.els.headerManualSpeedSaveBtn?.addEventListener(
      "click",
      features.settings.saveHeaderManualSpeedFromInput,
    );
    this.els.headerManualSpeedInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        features.settings.saveHeaderManualSpeedFromInput();
      }
    });
    this.els.startLoggingBtn?.addEventListener("click", features.realtime.startLogging);
    this.els.stopLoggingBtn?.addEventListener("click", features.realtime.stopLogging);
    this.els.refreshHistoryBtn?.addEventListener("click", features.history.refreshHistory);
    this.els.deleteAllRunsBtn?.addEventListener("click", () => void features.history.deleteAllRuns());
  }

  private bindHistoryTableEvents(): void {
    const features = this.requireFeatures();
    this.els.historyTableBody?.addEventListener("click", (event) => {
      const target = event.target as HTMLElement;
      const actionElement = target?.closest?.("[data-run-action]") as HTMLElement | null;
      if (actionElement) {
        const action = actionElement.getAttribute("data-run-action");
        const runId = actionElement.getAttribute("data-run") || this.state.expandedRunId || "";
        if (action !== "download-raw") event.preventDefault();
        event.stopPropagation();
        void features.history.onHistoryTableAction(action || "", runId);
        return;
      }
      const rowElement = target?.closest?.('tr[data-run-row="1"]') as HTMLElement | null;
      if (rowElement) {
        features.history.toggleRunDetails(rowElement.getAttribute("data-run") || "");
      }
    });
  }

  private bindPreferenceEvents(): void {
    if (this.els.languageSelect) {
      this.els.languageSelect.value = this.state.lang;
      this.els.languageSelect.addEventListener("change", () => {
        this.saveLanguage(this.els.languageSelect!.value);
        this.applyLanguage(true);
      });
    }
    if (this.els.speedUnitSelect) {
      this.els.speedUnitSelect.value = this.state.speedUnit;
      this.els.speedUnitSelect.addEventListener("change", () => {
        this.saveSpeedUnit(this.els.speedUnitSelect!.value);
        this.renderSpeedReadout();
      });
    }
  }

  private requireFeatures(): AppFeatureBundle {
    if (this.features === null) {
      throw new Error("UiShellController features used before initialization");
    }
    return this.features;
  }
}
