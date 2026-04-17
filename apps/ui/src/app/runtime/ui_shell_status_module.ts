import { fmt } from "../../format";
import { createSpeedSourceDerivedState } from "../speed_source_state";
import type {
  RealtimeState,
  SettingsState,
  ShellState,
  TransportState,
} from "../ui_app_state";
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
    return deps.shell.speedUnit.value === "mps" ? speedMps : speedMps * 3.6;
  }

  function selectedSpeedUnitLabel(): string {
    return deps.shell.speedUnit.value === "mps"
      ? deps.t("speed.unit.mps")
      : deps.t("speed.unit.kmh");
  }

  const runtimeSpeedSource = computed(() => {
    return deps.realtime.rotationalSpeeds.value?.basis_speed_source ?? null;
  });
  const speedSourceState = createSpeedSourceDerivedState(
    deps.settings,
    runtimeSpeedSource,
  );

  const wsLinkState = computed<UiShellBadgeModel>(() => {
    if (deps.transport.payloadError.value) {
      return {
        text: deps.t("ws.payload_error_pill"),
        variant: "bad",
      };
    }
    const wsState = deps.transport.wsState.value;
    return {
      text: deps.t(WS_KEY_BY_STATE[wsState] || "ws.connecting"),
      variant: WS_VARIANT_BY_STATE[wsState] || "muted",
    };
  });

  const speedReadoutText = computed(() => {
    const unitLabel = selectedSpeedUnitLabel();
    if (
      typeof deps.realtime.speedMps.value === "number" &&
      Number.isFinite(deps.realtime.speedMps.value)
    ) {
      const value = speedValueInSelectedUnit(deps.realtime.speedMps.value);
      const labelKey = speedSourceState.speedReadoutLabelKey.value;
      return deps.t(labelKey, {
        unit: unitLabel,
        value: fmt(value, 1),
      });
    }
    return deps.t("speed.none", { unit: unitLabel });
  });

  const connectionState = computed(() => {
    const degraded =
      deps.transport.payloadError.value !== null ||
      deps.transport.wsState.value === "reconnecting" ||
      deps.transport.wsState.value === "stale";
    return degraded ? "degraded" : "live";
  });

  return {
    connectionState,
    speedReadoutText,
    wsLinkState,
  };
}
