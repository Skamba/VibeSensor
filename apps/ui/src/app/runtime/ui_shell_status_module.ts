import { fmt } from "../../format";
import { deriveCarSelectionState } from "../car_selection_state";
import { isManualEffectiveSpeedSource } from "../speed_source_state";
import type { UiDomElements } from "../ui_dom_registry";
import type { RealtimeState, SettingsState, ShellState, TransportState } from "../ui_app_state";

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
  shell: ShellState;
  transport: TransportState;
  realtime: RealtimeState;
  settings: SettingsState;
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
  const { shell, transport, realtime, settings, els } = ctx;

  function speedValueInSelectedUnit(speedMps: number): number {
    return shell.speedUnit === "mps" ? speedMps : speedMps * 3.6;
  }

  function selectedSpeedUnitLabel(): string {
    return shell.speedUnit === "mps" ? ctx.t("speed.unit.mps") : ctx.t("speed.unit.kmh");
  }

  function renderSpeedReadout(): void {
    if (!els.speed) return;
    const unitLabel = selectedSpeedUnitLabel();
    if (typeof realtime.speedMps === "number" && Number.isFinite(realtime.speedMps)) {
      const value = speedValueInSelectedUnit(realtime.speedMps);
      const isOverride = isManualEffectiveSpeedSource(
        settings,
        realtime.rotationalSpeeds?.basis_speed_source ?? null,
      );
      els.speed.textContent = ctx.t(isOverride ? "speed.override" : "speed.gps", {
        value: fmt(value, 1),
        unit: unitLabel,
      });
      return;
    }
    els.speed.textContent = ctx.t("speed.none", { unit: unitLabel });
  }

  function renderWsState(): void {
    if (transport.payloadError) {
      ctx.setPillState(els.linkState, "bad", ctx.t("ws.payload_error_pill"));
      return;
    }
    ctx.setPillState(
      els.linkState,
      WS_VARIANT_BY_STATE[transport.wsState] || "muted",
      ctx.t(WS_KEY_BY_STATE[transport.wsState] || "ws.connecting"),
    );

    const banner = els.connectionBanner;
    if (banner) {
      const cfg = WS_BANNER_CFG[transport.wsState];
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
      const degraded = transport.wsState === "reconnecting" || transport.wsState === "stale";
      els.appShellWrap.classList.toggle("wrap--stale", degraded);
    }
  }

  function renderCarSelectionWarning(): void {
    const banner = els.carSelectionBanner;
    if (!banner) return;
    const carSelectionState = deriveCarSelectionState(settings);
    if (carSelectionState.kind === "loading" || carSelectionState.kind === "active") {
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
