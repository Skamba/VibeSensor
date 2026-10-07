import { describe, expect, test } from "vitest";

import type {
  ObdDevicePayload,
  ObdStatusPayload,
  SpeedSourceStatusPayload,
} from "../src/api/types";
import {
  checkSave,
  choiceState,
  compareDevices,
  configuredDeviceText,
  deviceActionLabel,
  deviceBadges,
  gpsDiagnostics,
  liveSourceText,
  manualSpeedFieldValue,
  maxManualSpeed,
  obdDiagnostics,
  selectedSourceLabel,
} from "../src/pages/speed_source/speed_source_model";
import {
  deriveSpeedReadoutLabelKey,
  fallbackReasonKey,
  gpsFixWaitS,
  gpsReceiverMissing,
  isManualEffectiveSpeedSource,
  resolveEffectiveSpeedSource,
  type SpeedSourceSnapshot,
} from "../src/speed_source";

// Pure speed-source logic. The page journeys (save, validation feedback,
// failed save, OBD scan/pair, double-click) live in smoke.speed_source.spec.ts.

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

describe("effective speed source", () => {
  test.each<
    [
      string,
      SpeedSourceSnapshot,
      {
        label: string;
        effective: string | null;
        manual: boolean;
      },
    ]
  >([
    [
      "a resolved manual fallback wins over the gps setting",
      {
        speedSource: "gps",
        manualSpeedKph: 80,
        resolvedSpeedSource: "fallback_manual",
      },
      {
        label: "speed.fallback",
        effective: "fallback_manual",
        manual: true,
      },
    ],
    [
      "gps stays selected when gps is resolved",
      { speedSource: "gps", manualSpeedKph: 80, resolvedSpeedSource: "gps" },
      { label: "speed.gps", effective: "gps", manual: false },
    ],
    [
      "a manual setting shows before live status arrives",
      { speedSource: "manual", manualSpeedKph: 45, resolvedSpeedSource: null },
      {
        label: "speed.override",
        effective: "manual",
        manual: true,
      },
    ],
    [
      "unavailable gps does not invent manual mode",
      { speedSource: "gps", manualSpeedKph: null, resolvedSpeedSource: "none" },
      { label: "speed.gps", effective: "none", manual: false },
    ],
    [
      "a resolved OBD-II source reads as OBD",
      {
        speedSource: "obd2",
        manualSpeedKph: null,
        resolvedSpeedSource: "obd2",
      },
      { label: "speed.obd2", effective: "obd2", manual: false },
    ],
  ])("%s", (_name, settings, expected) => {
    expect(deriveSpeedReadoutLabelKey(settings)).toBe(expected.label);
    expect(resolveEffectiveSpeedSource(settings)).toBe(expected.effective);
    expect(isManualEffectiveSpeedSource(settings)).toBe(expected.manual);
  });

  test("the live runtime source applies until the server resolves one", () => {
    const settings: SpeedSourceSnapshot = {
      speedSource: "gps",
      manualSpeedKph: 80,
      resolvedSpeedSource: null,
    };
    expect(deriveSpeedReadoutLabelKey(settings, "fallback_manual")).toBe(
      "speed.fallback",
    );
    expect(isManualEffectiveSpeedSource(settings, "fallback_manual")).toBe(
      true,
    );
    expect(
      deriveSpeedReadoutLabelKey(
        { ...settings, resolvedSpeedSource: "obd2" },
        "fallback_manual",
      ),
    ).toBe("speed.obd2");
  });
});

describe("speed source save validation", () => {
  const draft = {
    source: "gps" as const,
    manualSpeed: "",
    speedUnit: "kmh" as const,
    staleTimeout: "10",
    obdDeviceMac: null,
  };

  test("saves the configured source with an optional, trimmed manual fallback speed", () => {
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

  test("accepts manual speeds within 0.1-500 km/h only", () => {
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

  test("takes the manual speed in m/s and saves it in km/h to 0.1 km/h", () => {
    const mps = { ...draft, speedUnit: "mps" as const };
    expect(checkSave({ ...mps, manualSpeed: "25" })).toMatchObject({
      request: { manual_speed_kph: 90 },
    });
    expect(maxManualSpeed("mps")).toBe(138.8);
    expect(checkSave({ ...mps, manualSpeed: "138.8" }).ok).toBe(true);
    expect(checkSave({ ...mps, manualSpeed: "139" }).ok).toBe(false);
    // The field's two decimals read back as the saved km/h.
    for (const kph of [80, 100, 72.5, 0.1, 500]) {
      const shown = manualSpeedFieldValue(kph, "mps");
      expect(checkSave({ ...mps, manualSpeed: shown })).toMatchObject({
        request: { manual_speed_kph: kph },
      });
    }
    expect(manualSpeedFieldValue(80, "mps")).toBe("22.22");
    expect(manualSpeedFieldValue(80, "kmh")).toBe("80");
    expect(manualSpeedFieldValue(null, "mps")).toBe("");
  });

  test("requires a 3-120 s stale timeout unless manual is selected", () => {
    for (const staleTimeout of ["", "2", "121", "x"]) {
      expect(checkSave({ ...draft, staleTimeout })).toEqual({
        ok: false,
        problem: "stale_timeout",
      });
    }
    for (const staleTimeout of ["3", "120"]) {
      expect(checkSave({ ...draft, staleTimeout }).ok).toBe(true);
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
  test("names the saved choice apart from where the speed comes from right now", () => {
    const gps: SpeedSourceSnapshot = {
      speedSource: "gps",
      manualSpeedKph: 80,
      resolvedSpeedSource: null,
    };
    const live = (settings: SpeedSourceSnapshot, liveSpeedKph: number | null) =>
      liveSourceText({ settings, status: null, liveSpeedKph, unit: "kmh" }, t);
    expect(selectedSourceLabel("gps", t)).toBe("settings.speed.gps");
    expect(selectedSourceLabel("obd2", t)).toBe("settings.speed.obd");
    expect(selectedSourceLabel("manual", t)).toBe("settings.speed.manual");

    // The live source with its speed, or waiting for its first reading.
    expect(live({ ...gps, resolvedSpeedSource: "gps" }, 52)).toBe(
      'settings.speed.live_source:{"source":"settings.speed.gps","speed":"52.0 speed.unit.kmh"}',
    );
    expect(live(gps, null)).toBe(
      'settings.speed.live_waiting:{"source":"settings.speed.gps"}',
    );
    // The typed-in speed, chosen or standing in for a live source (and why).
    expect(live({ ...gps, speedSource: "manual" }, 52)).toBe(
      'settings.speed.live_manual:{"speed":"80.0 speed.unit.kmh"}',
    );
    expect(live({ ...gps, resolvedSpeedSource: "fallback_manual" }, 52)).toBe(
      'settings.speed.live_fallback:{"reason":"speed.fallback_reason.gps_no_fix","speed":"80.0 speed.unit.kmh"}',
    );
    // A live source that gives no speed and has no typed-in fallback.
    expect(
      live(
        {
          speedSource: "obd2",
          manualSpeedKph: null,
          resolvedSpeedSource: "none",
        },
        null,
      ),
    ).toBe('settings.speed.live_none:{"reason":"speed.fallback_reason.obd2"}');
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
        fix_wait_s: null,
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

test("GPS without a receiver: gpsd on, but never a device or a reading", () => {
  const gpsd: SpeedSourceStatusPayload = {
    connection_state: "connected",
    device: null,
    fix_wait_s: null,
    effective_speed_kmh: null,
    epv_m: null,
    epx_m: null,
    epy_m: null,
    fallback_active: false,
    fix_dimension: "none",
    fix_mode: null,
    gps_enabled: true,
    last_error: null,
    last_update_age_s: null,
    raw_speed_kmh: null,
    reconnect_delay_s: null,
    speed_confidence: "low",
    speed_source: "none",
    stale_timeout_s: 10,
  };
  expect(gpsReceiverMissing("gps", gpsd)).toBe(true);
  expect(gpsReceiverMissing("gps", { ...gpsd, device: "/dev/ttyACM0" })).toBe(
    false,
  );
  expect(gpsReceiverMissing("gps", { ...gpsd, last_update_age_s: 4 })).toBe(
    false,
  );
  expect(gpsReceiverMissing("obd2", gpsd)).toBe(false);
  expect(gpsReceiverMissing("gps", null)).toBe(false);

  // A plugged-in receiver without a fix reports how long it has waited.
  const waiting = { ...gpsd, device: "/dev/ttyACM0", fix_wait_s: 31.5 };
  expect(gpsFixWaitS("gps", waiting)).toBe(31.5);
  expect(gpsFixWaitS("gps", gpsd)).toBeNull();
  expect(gpsFixWaitS("obd2", waiting)).toBeNull();
  expect(gpsFixWaitS("gps", { ...waiting, gps_enabled: false })).toBeNull();

  // The fallback speed stands in for the chosen source, and the UI says why.
  const gps: SpeedSourceSnapshot = {
    speedSource: "gps",
    manualSpeedKph: 50,
    resolvedSpeedSource: "fallback_manual",
  };
  expect(fallbackReasonKey(gps, gpsd)).toBe("speed.gps_no_receiver.title");
  expect(fallbackReasonKey(gps, { ...gpsd, device: "/dev/ttyACM0" })).toBe(
    "speed.fallback_reason.gps_no_fix",
  );
  expect(fallbackReasonKey({ ...gps, speedSource: "obd2" }, null)).toBe(
    "speed.fallback_reason.obd2",
  );
  expect(fallbackReasonKey({ ...gps, resolvedSpeedSource: "gps" }, gpsd)).toBe(
    null,
  );
  expect(
    liveSourceText(
      { settings: gps, status: gpsd, liveSpeedKph: null, unit: "kmh" },
      t,
    ),
  ).toBe(
    'settings.speed.live_fallback:{"reason":"speed.gps_no_receiver.title","speed":"50.0 speed.unit.kmh"}',
  );
  expect(
    liveSourceText(
      {
        settings: { ...gps, resolvedSpeedSource: "none" },
        status: gpsd,
        liveSpeedKph: null,
        unit: "kmh",
      },
      t,
    ),
  ).toBe('settings.speed.live_none:{"reason":"speed.gps_no_receiver.title"}');
});
