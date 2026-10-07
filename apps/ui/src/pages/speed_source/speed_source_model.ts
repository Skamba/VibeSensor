import type {
  ObdDevicePayload,
  ObdStatusPayload,
  SpeedSourceKind,
  SpeedSourceRequest,
  SpeedSourceStatusPayload,
} from "../../api/types";
import { fmt, formatSpeed, type SpeedUnit } from "../../format";
import {
  fallbackReasonKey,
  gpsReceiverMissing,
  resolveEffectiveSpeedSource,
  type SpeedSourceSnapshot,
} from "../../speed_source";

/** Pure text, validation, and ordering for the speed source page. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

export interface ChoiceState {
  selected: boolean;
  state: "active" | "draft" | "error" | null;
  badge: string | null;
}

export interface DeviceBadge {
  label: string;
  active: boolean;
}

const CONNECTION_STATE_KEYS: Record<string, string> = {
  connected: "settings.speed.state_connected",
  disabled: "settings.speed.state_disabled",
  disconnected: "settings.speed.state_disconnected",
  stale: "settings.speed.state_stale",
};
const MAC_RE = /^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i;

const SOURCE_TITLE_KEYS: Record<SpeedSourceKind, string> = {
  gps: "settings.speed.gps",
  obd2: "settings.speed.obd",
  manual: "settings.speed.manual",
};

/** The saved choice, named as its card is. */
export function selectedSourceLabel(
  source: SpeedSourceKind,
  t: Translate,
): string {
  return t(SOURCE_TITLE_KEYS[source]);
}

/** Why the chosen live source gives no speed at all (and no fallback is set). */
function noSpeedReasonKey(
  settings: SpeedSourceSnapshot,
  status: SpeedSourceStatusPayload | null,
): string {
  if (settings.speedSource === "obd2") {
    return "speed.fallback_reason.obd2";
  }
  return gpsReceiverMissing(settings.speedSource, status)
    ? "speed.gps_no_receiver.title"
    : "speed.fallback_reason.gps_no_fix";
}

/**
 * Where the app's speed comes from right now, with that speed: the saved live
 * source, the typed-in speed, the typed-in fallback standing in for a live
 * source that gives none (and why), or no speed at all.
 */
export function liveSourceText(
  input: {
    settings: SpeedSourceSnapshot;
    status: SpeedSourceStatusPayload | null;
    /** The live source's current speed, km/h. */
    liveSpeedKph: number | null;
    unit: SpeedUnit;
  },
  t: Translate,
): string {
  const { settings, status, unit } = input;
  const speed = (kph: number | null) => formatSpeed(kph, unit, t, 1);
  const reason = fallbackReasonKey(settings, status);
  if (reason) {
    return t("settings.speed.live_fallback", {
      reason: t(reason),
      speed: speed(settings.manualSpeedKph),
    });
  }
  const effective = resolveEffectiveSpeedSource(settings);
  if (effective === "manual") {
    return t("settings.speed.live_manual", {
      speed: speed(settings.manualSpeedKph),
    });
  }
  if (effective === "gps" || effective === "obd2") {
    const source = selectedSourceLabel(effective, t);
    return input.liveSpeedKph === null
      ? t("settings.speed.live_waiting", { source })
      : t("settings.speed.live_source", {
          source,
          speed: speed(input.liveSpeedKph),
        });
  }
  return t("settings.speed.live_none", {
    reason: t(noSpeedReasonKey(settings, status)),
  });
}

export function choiceState(options: {
  active: boolean;
  pending: boolean;
  error: boolean;
  t: Translate;
}): ChoiceState {
  const { active, pending, error, t } = options;
  return {
    selected: active,
    state: error ? "error" : pending ? "draft" : active ? "active" : null,
    badge: pending
      ? t("settings.speed.choice_pending")
      : active
        ? t("settings.speed.choice_active")
        : null,
  };
}

export function configuredDeviceText(
  mac: string | null,
  name: string | null,
  t: Translate,
): string {
  if (name && mac) {
    return `${name} (${mac})`;
  }
  return name ?? mac ?? t("settings.speed.obd_not_configured");
}

export function hasReadableName(device: ObdDevicePayload): boolean {
  const name = device.name?.trim();
  return Boolean(name) && !MAC_RE.test(name ?? "");
}

/** Connected, then paired, then named adapters first; then by name and MAC. */
export function compareDevices(
  left: ObdDevicePayload,
  right: ObdDevicePayload,
): number {
  const rank = (device: ObdDevicePayload) => [
    Number(!device.connected),
    Number(!device.paired),
    Number(!hasReadableName(device)),
  ];
  const [a, b] = [rank(left), rank(right)];
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) {
      return a[index] - b[index];
    }
  }
  const leftName = left.name?.trim() || left.mac_address;
  const rightName = right.name?.trim() || right.mac_address;
  return (
    leftName.localeCompare(rightName) ||
    left.mac_address.localeCompare(right.mac_address)
  );
}

export function deviceBadges(
  device: ObdDevicePayload,
  configuredMac: string | null,
  t: Translate,
): DeviceBadge[] {
  const badges: DeviceBadge[] = [];
  if (device.mac_address === configuredMac) {
    badges.push({
      label: t("settings.speed.obd_configured_badge"),
      active: true,
    });
  }
  if (device.paired) {
    badges.push({ label: t("settings.speed.obd_paired_badge"), active: false });
  }
  if (device.trusted) {
    badges.push({
      label: t("settings.speed.obd_trusted_badge"),
      active: false,
    });
  }
  if (device.connected) {
    badges.push({
      label: t("settings.speed.obd_connected_badge"),
      active: true,
    });
  }
  return badges;
}

export function deviceActionLabel(
  device: ObdDevicePayload,
  pairingMac: string | null,
  t: Translate,
): string {
  if (pairingMac === device.mac_address) {
    return t("settings.speed.obd_pairing");
  }
  return t(
    device.paired && device.trusted
      ? "settings.speed.obd_use"
      : "settings.speed.obd_pair_and_use",
  );
}

/** The highest manual speed the server takes, in km/h. */
const MAX_MANUAL_SPEED_KMH = 500;

/** A saved manual speed (km/h) as the field shows it, in the display unit. */
export function manualSpeedFieldValue(
  speedKph: number | null,
  unit: SpeedUnit,
): string {
  if (speedKph == null) {
    return "";
  }
  // Two decimals in m/s read back as the same 0.1 km/h when saved again.
  return String(
    unit === "mps" ? Math.round((speedKph / 3.6) * 100) / 100 : speedKph,
  );
}

/** The highest manual speed the field accepts, in the display unit. */
export function maxManualSpeed(unit: SpeedUnit): number {
  return unit === "mps"
    ? Math.floor((MAX_MANUAL_SPEED_KMH / 3.6) * 10) / 10
    : MAX_MANUAL_SPEED_KMH;
}

export type SaveCheck =
  | { ok: true; request: SpeedSourceRequest }
  | { ok: false; problem: "manual_speed" | "stale_timeout" | "obd_device" };

/**
 * Validates the draft before saving. The radio draft wins; otherwise the
 * configured source is kept (a manual fallback does not switch to manual).
 * The manual speed is typed in the display unit and saved in km/h.
 */
export function checkSave(draft: {
  source: SpeedSourceKind;
  manualSpeed: string;
  speedUnit: SpeedUnit;
  staleTimeout: string;
  obdDeviceMac: string | null;
}): SaveCheck {
  const manualRaw = draft.manualSpeed.trim();
  const manualValue = Number(manualRaw);
  const manualKph =
    draft.speedUnit === "mps"
      ? Math.round(manualValue * 3.6 * 10) / 10
      : manualValue;
  const manualSpeedKph =
    Number.isFinite(manualKph) &&
    manualKph > 0 &&
    manualKph <= MAX_MANUAL_SPEED_KMH
      ? manualKph
      : null;
  if (
    manualSpeedKph === null &&
    (draft.source === "manual" || manualRaw !== "")
  ) {
    return { ok: false, problem: "manual_speed" };
  }
  const staleRaw = draft.staleTimeout.trim();
  const staleValue = Number(staleRaw);
  const staleValid =
    staleRaw !== "" &&
    Number.isFinite(staleValue) &&
    staleValue >= 3 &&
    staleValue <= 120;
  if (draft.source !== "manual" && !staleValid) {
    return { ok: false, problem: "stale_timeout" };
  }
  if (draft.source === "obd2" && !draft.obdDeviceMac) {
    return { ok: false, problem: "obd_device" };
  }
  const request: SpeedSourceRequest = {
    manual_speed_kph: manualSpeedKph,
    speed_source: draft.source,
  };
  if (staleValid) {
    request.stale_timeout_s = staleValue;
  }
  return { ok: true, request };
}

function yesNo(value: boolean, t: Translate): string {
  return t(
    value ? "settings.speed.fallback_yes" : "settings.speed.fallback_no",
  );
}

function ageText(seconds: number | null, t: Translate): string | null {
  return seconds != null
    ? t("settings.speed.last_update_value", {
        value: {
          number: seconds,
          options: { minimumFractionDigits: 1, maximumFractionDigits: 1 },
        },
      })
    : null;
}

export interface DiagnosticRow {
  id: string;
  labelKey: string;
  value: string;
}

export function gpsDiagnostics(
  status: SpeedSourceStatusPayload | null,
  unit: SpeedUnit,
  t: Translate,
): DiagnosticRow[] {
  const row = (id: string, labelKey: string, value: string | undefined) => ({
    id,
    labelKey,
    value: status && value !== undefined ? value : "--",
  });
  return [
    row(
      "gpsStatusState",
      "settings.speed.connection_state",
      status
        ? CONNECTION_STATE_KEYS[status.connection_state]
          ? t(CONNECTION_STATE_KEYS[status.connection_state])
          : status.connection_state
        : undefined,
    ),
    row("gpsStatusDevice", "settings.speed.device", status?.device ?? "--"),
    row(
      "gpsStatusLastUpdate",
      "settings.speed.last_update",
      status
        ? (ageText(status.last_update_age_s, t) ??
            t("settings.speed.last_update_never"))
        : undefined,
    ),
    row(
      "gpsStatusRawSpeed",
      "settings.speed.raw_speed",
      status ? formatSpeed(status.raw_speed_kmh, unit, t, 1) : undefined,
    ),
    row(
      "gpsStatusEffectiveSpeed",
      "settings.speed.effective_speed",
      status ? formatSpeed(status.effective_speed_kmh, unit, t, 1) : undefined,
    ),
    row(
      "gpsStatusLastError",
      "settings.speed.last_error",
      status?.last_error ?? "--",
    ),
    row(
      "gpsStatusReconnect",
      "settings.speed.reconnect_in",
      status?.reconnect_delay_s != null
        ? `${fmt(status.reconnect_delay_s, 1)}s`
        : "--",
    ),
    row(
      "gpsStatusFallback",
      "settings.speed.fallback_active",
      status ? yesNo(status.fallback_active, t) : undefined,
    ),
  ];
}

const OBD_POLL_MODE_KEYS: Record<string, string> = {
  rpm_only: "settings.speed.obd_mode_rpm_only",
  rpm_only_backoff: "settings.speed.obd_mode_rpm_only_backoff",
  rpm_priority: "settings.speed.obd_mode_rpm_priority",
  rpm_priority_backoff: "settings.speed.obd_mode_rpm_priority_backoff",
};

export function obdDiagnostics(
  obd: ObdStatusPayload | null,
  t: Translate,
): DiagnosticRow[] {
  const value = (text: string | null | undefined) =>
    obd && text != null ? text : "--";
  const target = obd?.rpm_target_interval_ms;
  return [
    {
      id: "obdStatusConfiguredDevice",
      labelKey: "settings.speed.obd_configured_device",
      value: obd
        ? configuredDeviceText(
            obd.configured_device_mac,
            obd.configured_device_name,
            t,
          )
        : "--",
    },
    {
      id: "obdStatusPairing",
      labelKey: "settings.speed.obd_paired",
      value: value(obd && yesNo(obd.paired, t)),
    },
    {
      id: "obdStatusTrusted",
      labelKey: "settings.speed.obd_trusted",
      value: value(obd && yesNo(obd.trusted, t)),
    },
    {
      id: "obdStatusConnected",
      labelKey: "settings.speed.obd_connected",
      value: value(obd && yesNo(obd.connected, t)),
    },
    {
      id: "obdStatusRfcommChannel",
      labelKey: "settings.speed.obd_rfcomm_channel",
      value: value(
        obd?.rfcomm_channel != null ? String(obd.rfcomm_channel) : null,
      ),
    },
    {
      id: "obdStatusLastRpm",
      labelKey: "settings.speed.obd_last_rpm",
      value: value(obd?.last_rpm != null ? fmt(obd.last_rpm, 0) : null),
    },
    {
      id: "obdStatusRpmAge",
      labelKey: "settings.speed.obd_rpm_age",
      value: value(obd ? ageText(obd.rpm_sample_age_s, t) : null),
    },
    {
      id: "obdStatusTargetCadence",
      labelKey: "settings.speed.obd_target_cadence",
      value: value(
        target != null && target > 0
          ? `${fmt(1000 / target, 1)} Hz (${fmt(target, 0)} ms)`
          : null,
      ),
    },
    {
      id: "obdStatusEffectiveCadence",
      labelKey: "settings.speed.obd_effective_cadence",
      value: value(
        obd?.rpm_effective_hz != null
          ? `${fmt(obd.rpm_effective_hz, 1)} Hz`
          : null,
      ),
    },
    {
      id: "obdStatusRequestRtt",
      labelKey: "settings.speed.obd_request_rtt",
      value: value(
        obd?.request_rtt_ms != null ? `${fmt(obd.request_rtt_ms, 0)} ms` : null,
      ),
    },
    {
      id: "obdStatusTimeouts",
      labelKey: "settings.speed.obd_timeouts",
      value: value(obd ? String(obd.timeout_count) : null),
    },
    {
      id: "obdStatusErrors",
      labelKey: "settings.speed.obd_errors",
      value: value(obd ? String(obd.error_count) : null),
    },
    {
      id: "obdStatusMode",
      labelKey: "settings.speed.obd_mode",
      value: value(
        obd?.poll_mode != null
          ? OBD_POLL_MODE_KEYS[obd.poll_mode]
            ? t(OBD_POLL_MODE_KEYS[obd.poll_mode])
            : obd.poll_mode
          : null,
      ),
    },
    {
      id: "obdStatusBackoff",
      labelKey: "settings.speed.obd_backoff_active",
      value: value(obd && yesNo(obd.backoff_active, t)),
    },
    {
      id: "obdStatusRawResponse",
      labelKey: "settings.speed.obd_raw_response",
      value: value(obd?.last_raw_response),
    },
    {
      id: "obdStatusDebugHint",
      labelKey: "settings.speed.obd_debug_hint",
      value: value(obd?.debug_hint),
    },
  ];
}
