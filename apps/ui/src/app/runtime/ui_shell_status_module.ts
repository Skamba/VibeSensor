import { fmt } from "../../format";
import { createSpeedSourceDerivedState } from "../speed_source_state";
import type {
  RealtimeState,
  SettingsState,
  ShellState,
  TransportState,
} from "../ui_app_state";
import { trackAppStateSlice } from "../ui_app_state";
import type { VisualVariant } from "../view_style_types";
import { computed, type ReadonlySignal } from "../ui_signals";
import type { UiShellBadgeModel } from "./ui_shell_chrome";

const WS_KEY_BY_STATE: Record<string, string> = {
  connecting: "ws.connecting",
  connected: "ws.connected",
  reconnecting: "ws.reconnecting",
  stale: "ws.stale",
  no_data: "ws.connected",
};

const WS_VARIANT_BY_STATE: Record<string, VisualVariant> = {
  connecting: "muted",
  connected: "ok",
  reconnecting: "warn",
  stale: "bad",
  no_data: "ok",
};

type UiShellStatusDeps = {
  realtime: RealtimeState;
  settings: SettingsState;
  shell: ShellState;
  t: (key: string, vars?: Record<string, unknown>) => string;
  transport: TransportState;
};

export interface UiShellStatusModule {
  readonly connectionState: ReadonlySignal<"degraded" | "live">;
  readonly speedReadoutText: ReadonlySignal<string>;
  readonly wsLinkState: ReadonlySignal<UiShellBadgeModel>;
}

export function createUiShellStatusModule(
  deps: UiShellStatusDeps,
): UiShellStatusModule {
  function speedValueInSelectedUnit(speedMps: number): number {
    return deps.shell.speedUnit === "mps" ? speedMps : speedMps * 3.6;
  }

  function selectedSpeedUnitLabel(): string {
    return deps.shell.speedUnit === "mps"
      ? deps.t("speed.unit.mps")
      : deps.t("speed.unit.kmh");
  }

  const runtimeSpeedSource = computed(() => {
    trackAppStateSlice(deps.realtime);
    return deps.realtime.rotationalSpeeds?.basis_speed_source ?? null;
  });
  const speedSourceState = createSpeedSourceDerivedState(
    deps.settings,
    runtimeSpeedSource,
  );

  const wsLinkState = computed<UiShellBadgeModel>(() => {
    trackAppStateSlice(deps.transport);
    if (deps.transport.payloadError) {
      return {
        text: deps.t("ws.payload_error_pill"),
        variant: "bad",
      };
    }
    const wsState = deps.transport.wsState;
    return {
      text: deps.t(WS_KEY_BY_STATE[wsState] || "ws.connecting"),
      variant: WS_VARIANT_BY_STATE[wsState] || "muted",
    };
  });

  const speedReadoutText = computed(() => {
    trackAppStateSlice(deps.realtime);
    const unitLabel = selectedSpeedUnitLabel();
    if (
      typeof deps.realtime.speedMps === "number" &&
      Number.isFinite(deps.realtime.speedMps)
    ) {
      const value = speedValueInSelectedUnit(deps.realtime.speedMps);
      const labelKey = speedSourceState.speedReadoutLabelKey.value;
      return deps.t(labelKey, {
        unit: unitLabel,
        value: fmt(value, 1),
      });
    }
    return deps.t("speed.none", { unit: unitLabel });
  });

  const connectionState = computed(() => {
    trackAppStateSlice(deps.transport);
    const degraded =
      deps.transport.payloadError !== null ||
      deps.transport.wsState === "reconnecting" ||
      deps.transport.wsState === "stale";
    return degraded ? "degraded" : "live";
  });

  return {
    connectionState,
    speedReadoutText,
    wsLinkState,
  };
}
