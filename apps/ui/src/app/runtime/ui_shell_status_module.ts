import { fmt } from "../../format";
import type { UiDomElements } from "../ui_dom_registry";
import type { AppState } from "../ui_app_state";

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

export interface UiShellStatusModuleDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
}

export interface UiShellStatusModule {
  renderSpeedReadout(): void;
  renderWsState(): void;
  renderCarSelectionWarning(): void;
}

export function createUiShellStatusModule(ctx: UiShellStatusModuleDeps): UiShellStatusModule {
  const { state, els } = ctx;

  function speedValueInSelectedUnit(speedMps: number | null): number | null {
    if (!(typeof speedMps === "number") || !Number.isFinite(speedMps)) return null;
    return state.speedUnit === "mps" ? speedMps : speedMps * 3.6;
  }

  function selectedSpeedUnitLabel(): string {
    return state.speedUnit === "mps" ? ctx.t("speed.unit.mps") : ctx.t("speed.unit.kmh");
  }

  function renderSpeedReadout(): void {
    if (!els.speed) return;
    const unitLabel = selectedSpeedUnitLabel();
    if (typeof state.speedMps === "number" && Number.isFinite(state.speedMps)) {
      const value = speedValueInSelectedUnit(state.speedMps);
      const isManualSource = state.speedSource === "manual"
        && typeof state.manualSpeedKph === "number"
        && state.manualSpeedKph > 0;
      const isFallbackOverride = state.gpsFallbackActive
        || state.rotationalSpeeds?.basis_speed_source === "fallback_manual";
      const isOverride = isManualSource || isFallbackOverride;
      els.speed.textContent = ctx.t(isOverride ? "speed.override" : "speed.gps", {
        value: fmt(value!, 1),
        unit: unitLabel,
      });
      return;
    }
    els.speed.textContent = ctx.t("speed.none", { unit: unitLabel });
  }

  function renderWsState(): void {
    if (state.payloadError) {
      ctx.setPillState(els.linkState, "bad", ctx.t("ws.payload_error_pill"));
      return;
    }
    ctx.setPillState(
      els.linkState,
      WS_VARIANT_BY_STATE[state.wsState] || "muted",
      ctx.t(WS_KEY_BY_STATE[state.wsState] || "ws.connecting"),
    );

    const banner = els.connectionBanner;
    if (banner) {
      const cfg = WS_BANNER_CFG[state.wsState];
      if (cfg) {
        banner.hidden = false;
        banner.textContent = ctx.t(cfg.key);
        banner.className = `connection-banner ${cfg.cls}`;
      } else {
        banner.hidden = true;
        banner.textContent = "";
        banner.className = "connection-banner";
      }
    }

    if (els.appShellWrap) {
      const degraded = state.wsState === "reconnecting" || state.wsState === "stale";
      els.appShellWrap.classList.toggle("wrap--stale", degraded);
    }
  }

  function renderCarSelectionWarning(): void {
    const banner = els.carSelectionBanner;
    if (!banner) return;
    const hasValidActiveCar = Boolean(
      state.activeCarId && state.cars.some((car) => car.id === state.activeCarId),
    );
    if (hasValidActiveCar) {
      banner.hidden = true;
      banner.textContent = "";
      return;
    }
    banner.hidden = false;
    banner.textContent = `${ctx.t("header.no_car_selected")} ${ctx.t("header.no_car_selected_action")}`;
  }

  return {
    renderSpeedReadout,
    renderWsState,
    renderCarSelectionWarning,
  };
}
