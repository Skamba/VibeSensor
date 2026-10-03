import { describe, expect, test } from "vitest";

import type { ObdDevicePayload, ObdStatusPayload } from "../src/api/types";
import {
  activeSourceLabel,
  activeSpeedKph,
  checkSave,
  choiceState,
  compareDevices,
  configuredDeviceText,
  deviceActionLabel,
  deviceBadges,
  gpsDiagnostics,
  obdDiagnostics,
  speedText,
} from "../src/pages/speed_source/speed_source_model";

const t = (key: string, vars?: Record<string, unknown>) =>
  vars ? `${key}:${JSON.stringify(vars)}` : key;

function device(overrides: Partial<ObdDevicePayload> = {}): ObdDevicePayload {
  return {
    connected: false,
    mac_address: "00:1D:A5:00:00:01",
    name: null,
    paired: false,
    rfcomm_channel: null,
    trusted: false,
    ...overrides,
  };
}

describe("speed source save validation", () => {
  const draft = {
    source: "gps" as const,
    manualSpeed: "",
    staleTimeout: "10",
    obdDeviceMac: null,
  };

  test("saves the configured source with an optional manual fallback speed", () => {
    expect(checkSave(draft)).toEqual({
      ok: true,
      request: {
        manual_speed_kph: null,
        speed_source: "gps",
        stale_timeout_s: 10,
      },
    });
    expect(checkSave({ ...draft, manualSpeed: " 72.5 " })).toMatchObject({
      ok: true,
      request: { manual_speed_kph: 72.5 },
    });
  });

  test("rejects manual speeds outside 0.1-500 km/h", () => {
    for (const manualSpeed of ["0", "-3", "500.1", "abc"]) {
      expect(checkSave({ ...draft, manualSpeed })).toEqual({
        ok: false,
        problem: "manual_speed",
      });
    }
    expect(checkSave({ ...draft, source: "manual", manualSpeed: "" })).toEqual({
      ok: false,
      problem: "manual_speed",
    });
    expect(checkSave({ ...draft, manualSpeed: "500" }).ok).toBe(true);
  });

  test("requires a 3-120 s stale timeout unless manual is selected", () => {
    for (const staleTimeout of ["", "2", "121", "x"]) {
      expect(checkSave({ ...draft, staleTimeout })).toEqual({
        ok: false,
        problem: "stale_timeout",
      });
    }
    expect(
      checkSave({
        ...draft,
        source: "manual",
        manualSpeed: "80",
        staleTimeout: "",
      }),
    ).toEqual({
      ok: true,
      request: { manual_speed_kph: 80, speed_source: "manual" },
    });
  });

  test("requires a paired adapter for OBD-II", () => {
    expect(checkSave({ ...draft, source: "obd2" })).toEqual({
      ok: false,
      problem: "obd_device",
    });
    expect(
      checkSave({ ...draft, source: "obd2", obdDeviceMac: "00:1D:A5:00:00:01" })
        .ok,
    ).toBe(true);
  });
});

describe("speed source summary", () => {
  test("labels the source in effect, including a manual fallback", () => {
    const gps = {
      speedSource: "gps" as const,
      manualSpeedKph: 80,
      resolvedSpeedSource: null,
    };
    expect(activeSourceLabel(gps, t)).toBe("settings.speed.gps");
    expect(
      activeSourceLabel({ ...gps, resolvedSpeedSource: "fallback_manual" }, t),
    ).toBe("settings.speed.current_source_fallback_manual");
    expect(activeSourceLabel({ ...gps, speedSource: "manual" }, t)).toBe(
      "settings.speed.current_source_manual_override",
    );
    expect(activeSourceLabel({ ...gps, resolvedSpeedSource: "obd2" }, t)).toBe(
      "dashboard.rotational.source.obd2",
    );
    expect(
      activeSpeedKph({ ...gps, resolvedSpeedSource: "fallback_manual" }, 52),
    ).toBe(80);
    expect(activeSpeedKph(gps, 52)).toBe(52);
  });

  test("formats speeds in the selected unit", () => {
    expect(speedText(36, "kmh", t)).toBe("36.0 speed.unit.kmh");
    expect(speedText(36, "mps", t)).toBe("10.0 speed.unit.mps");
    expect(speedText(null, "kmh", t)).toBe("--");
  });

  test("marks the saved card active and a different draft as pending", () => {
    expect(
      choiceState({ active: true, pending: false, error: false, t }),
    ).toEqual({
      selected: true,
      state: "active",
      badge: "settings.speed.choice_active",
    });
    expect(
      choiceState({ active: false, pending: true, error: false, t }),
    ).toEqual({
      selected: false,
      state: "draft",
      badge: "settings.speed.choice_pending",
    });
    expect(
      choiceState({ active: false, pending: true, error: true, t }).state,
    ).toBe("error");
  });
});

describe("OBD adapters", () => {
  test("sorts connected, paired, then named adapters first", () => {
    const unnamed = device({ mac_address: "00:00:00:00:00:09" });
    const macAlias = device({
      mac_address: "00:00:00:00:00:08",
      name: "00:00:00:00:00:08",
    });
    const named = device({ mac_address: "00:00:00:00:00:07", name: "Vgate" });
    const paired = device({ mac_address: "00:00:00:00:00:06", paired: true });
    const connected = device({
      mac_address: "00:00:00:00:00:05",
      connected: true,
    });
    expect(
      [unnamed, macAlias, named, paired, connected]
        .sort(compareDevices)
        .map((item) => item.mac_address),
    ).toEqual([
      "00:00:00:00:00:05",
      "00:00:00:00:00:06",
      "00:00:00:00:00:07",
      "00:00:00:00:00:08",
      "00:00:00:00:00:09",
    ]);
  });

  test("badges and actions reflect pairing state", () => {
    const trusted = device({ paired: true, trusted: true, connected: true });
    expect(
      deviceBadges(trusted, trusted.mac_address, t).map((badge) => badge.label),
    ).toEqual([
      "settings.speed.obd_configured_badge",
      "settings.speed.obd_paired_badge",
      "settings.speed.obd_trusted_badge",
      "settings.speed.obd_connected_badge",
    ]);
    expect(deviceActionLabel(trusted, null, t)).toBe("settings.speed.obd_use");
    expect(deviceActionLabel(device(), null, t)).toBe(
      "settings.speed.obd_pair_and_use",
    );
    expect(deviceActionLabel(trusted, trusted.mac_address, t)).toBe(
      "settings.speed.obd_pairing",
    );
    expect(configuredDeviceText("AA", "Link", t)).toBe("Link (AA)");
    expect(configuredDeviceText(null, null, t)).toBe(
      "settings.speed.obd_not_configured",
    );
  });
});

describe("diagnostics", () => {
  test("shows placeholders until the first status arrives", () => {
    expect(
      gpsDiagnostics(null, "kmh", t).every((row) => row.value === "--"),
    ).toBe(true);
    expect(obdDiagnostics(null, t).every((row) => row.value === "--")).toBe(
      true,
    );
  });

  test("formats GPS and OBD status values", () => {
    const gps = gpsDiagnostics(
      {
        connection_state: "connected",
        device: "/dev/ttyACM0",
        effective_speed_kmh: 50,
        epv_m: null,
        epx_m: null,
        epy_m: null,
        fallback_active: false,
        fix_dimension: "3d",
        fix_mode: 3,
        gps_enabled: true,
        last_error: null,
        last_update_age_s: null,
        raw_speed_kmh: 49.5,
        reconnect_delay_s: 2.5,
        speed_confidence: "high",
        speed_source: "gps",
        stale_timeout_s: 10,
      },
      "kmh",
      t,
    );
    expect(Object.fromEntries(gps.map((row) => [row.id, row.value]))).toEqual({
      gpsStatusState: "settings.speed.state_connected",
      gpsStatusDevice: "/dev/ttyACM0",
      gpsStatusLastUpdate: "settings.speed.last_update_never",
      gpsStatusRawSpeed: "49.5 speed.unit.kmh",
      gpsStatusEffectiveSpeed: "50.0 speed.unit.kmh",
      gpsStatusLastError: "--",
      gpsStatusReconnect: "2.5s",
      gpsStatusFallback: "settings.speed.fallback_no",
    });
    const obd: ObdStatusPayload = {
      backoff_active: true,
      configured_device_mac: "AA",
      configured_device_name: null,
      connected: true,
      connection_state: "connected",
      debug_hint: null,
      device_mac: "AA",
      device_name: null,
      error_count: 2,
      last_error: null,
      last_raw_response: "41 0D 32",
      last_rpm: 812.4,
      last_sample_age_s: 0.2,
      last_speed_kmh: 50,
      paired: true,
      poll_mode: "rpm_priority_backoff",
      reconnect_delay_s: null,
      request_rtt_ms: 41.6,
      rfcomm_channel: 1,
      rpm_effective_hz: 3.96,
      rpm_sample_age_s: null,
      rpm_target_interval_ms: 250,
      timeout_count: 1,
      trusted: true,
    };
    const rows = Object.fromEntries(
      obdDiagnostics(obd, t).map((row) => [row.id, row.value]),
    );
    expect(rows).toMatchObject({
      obdStatusConfiguredDevice: "AA",
      obdStatusLastRpm: "812",
      obdStatusRpmAge: "--",
      obdStatusTargetCadence: "4.0 Hz (250 ms)",
      obdStatusEffectiveCadence: "4.0 Hz",
      obdStatusRequestRtt: "42 ms",
      obdStatusMode: "settings.speed.obd_mode_rpm_priority_backoff",
      obdStatusBackoff: "settings.speed.fallback_yes",
      obdStatusRawResponse: "41 0D 32",
      obdStatusDebugHint: "--",
    });
  });
});
