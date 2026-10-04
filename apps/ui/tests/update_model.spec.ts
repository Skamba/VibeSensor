import { describe, expect, test } from "vitest";

import type {
  HealthStatusPayload,
  UpdateStatusPayload,
} from "../src/api/types";
import {
  activeTransport,
  canStart,
  currentStatusRows,
  failureSummary,
  formatDuration,
  healthRows,
  internetBadge,
  internetRows,
  journeyStages,
  logPlaceholder,
  rootSideFix,
  startLabel,
  startReadiness,
  type UpdateView,
  usbSummary,
} from "../src/pages/update/update_model";
import {
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUsbInternetStatus,
} from "./maintenance_payload_test_support";

function t(key: string, vars?: Record<string, unknown>): string {
  return vars && Object.keys(vars).length > 0
    ? `${key}:${JSON.stringify(vars)}`
    : key;
}

const USABLE_USB = createUsbInternetStatus({
  detected: true,
  usable: true,
  interface_name: "usb0",
  ipv4_addresses: ["192.168.42.17/24"],
  has_default_route: true,
  diagnostic: "USB internet ready",
});

const FAILED_USB_DOWNLOAD = createIdleUpdateStatus({
  state: "failed",
  phase: "downloading",
  transport: "usb_internet",
  uplink_interface: "usb0",
  issues: [
    {
      phase: "downloading",
      message: "GitHub release download timed out",
      detail: "Upstream connectivity dropped during fetch.",
    },
  ],
  started_at: 1,
  finished_at: 2,
  exit_code: 28,
});

function makeView(overrides: Partial<UpdateView> = {}): UpdateView {
  return {
    status: createIdleUpdateStatus(),
    health: createHealthyUpdateStatus(),
    internet: createUsbInternetStatus(),
    transportChoice: "wifi",
    ssid: "",
    ...overrides,
  };
}

function degradedHealth(): HealthStatusPayload {
  const healthy = createHealthyUpdateStatus();
  return {
    ...healthy,
    status: "degraded",
    degradation_reasons: [
      "persistence_write_error",
      "processing_state:stalled",
    ],
    persistence: { ...healthy.persistence, write_error: "disk full" },
  };
}

describe("update readiness", () => {
  test("Wi-Fi without an SSID is blocked", () => {
    const view = makeView();
    expect(activeTransport(view)).toBe("wifi");
    expect(canStart(view, t)).toBe(false);
    expect(startLabel(view, t)).toBe("settings.update.start");
    const readiness = startReadiness(view, t);
    expect(readiness.summary).toBe("settings.update.readiness.summary_blocked");
    expect(readiness.items).toContainEqual({
      label: "settings.update.readiness.item.connection",
      detail: "settings.update.readiness.item.connection_wifi_blocked",
      state: "blocked",
    });
    expect(canStart(makeView({ ssid: "Workshop" }), t)).toBe(true);
  });

  test("USB is only chosen while the uplink is usable", () => {
    expect(activeTransport(makeView({ transportChoice: "usb_internet" }))).toBe(
      "wifi",
    );
    const view = makeView({
      transportChoice: "usb_internet",
      internet: USABLE_USB,
    });
    expect(activeTransport(view)).toBe("usb_internet");
    expect(canStart(view, t)).toBe(true);
    expect(usbSummary(USABLE_USB, t)).toContain(
      "settings.update.transport.usb_summary_interface",
    );
  });

  test("a running job keeps its own transport", () => {
    const view = makeView({
      status: createIdleUpdateStatus({
        state: "running",
        transport: "usb_internet",
      }),
      transportChoice: "wifi",
    });
    expect(activeTransport(view)).toBe("usb_internet");
    expect(canStart(view, t)).toBe(false);
    expect(startReadiness(view, t).summary).toBe(
      "settings.update.readiness.summary_running",
    );
  });

  test("degraded background services block a fresh update", () => {
    const view = makeView({ ssid: "Workshop", health: degradedHealth() });
    expect(canStart(view, t)).toBe(false);
    expect(startReadiness(view, t).items.at(-1)).toMatchObject({
      label: "settings.update.readiness.item.health",
      state: "blocked",
    });
  });

  test("a failed update offers a retry with recovery guidance", () => {
    const view = makeView({
      status: FAILED_USB_DOWNLOAD,
      internet: USABLE_USB,
      transportChoice: "usb_internet",
    });
    expect(canStart(view, t)).toBe(true);
    expect(startLabel(view, t)).toBe("settings.update.retry");
    expect(failureSummary(FAILED_USB_DOWNLOAD, t)).toEqual({
      phaseLabel: "downloading",
      message: "GitHub release download timed out",
      detail: "Upstream connectivity dropped during fetch.",
      recoveryTitle: "settings.update.recovery.network.title",
      recoveryDetail: "settings.update.recovery.network.detail",
    });
    expect(startReadiness(view, t).title).toBe(
      "settings.update.recovery.title",
    );
  });

  test("retry stays enabled when the recovery checklist is blocked", () => {
    const view = makeView({
      status: FAILED_USB_DOWNLOAD,
      health: degradedHealth(),
      transportChoice: "usb_internet",
    });
    expect(canStart(view, t)).toBe(true);
    expect(activeTransport(view)).toBe("wifi");
    const readiness = startReadiness(view, t);
    expect(readiness.summary).toBe("settings.update.recovery.summary_blocked");
    expect(readiness.items).toContainEqual({
      label: "settings.update.recovery.item.next_step",
      detail: "settings.update.recovery.item.next_step_blocked",
      state: "blocked",
    });
  });
});

describe("update status", () => {
  test("keeps runtime asset verification visible for asset-related failures", () => {
    const status = createIdleUpdateStatus({
      state: "failed",
      phase: "installing",
      issues: [
        {
          phase: "installing",
          message: "static assets hash mismatch",
          detail: "Packaged artifacts are stale",
        },
      ],
    });
    status.runtime = { ...status.runtime, assets_verified: false };
    expect(currentStatusRows(status, t)).toContainEqual({
      label: "settings.update.runtime_assets_check",
      value: "settings.update.runtime_assets_bad",
    });
    const unrelated: UpdateStatusPayload = {
      ...status,
      issues: [{ phase: "downloading", message: "timeout", detail: "" }],
    };
    expect(
      currentStatusRows(unrelated, t).map((row) => row.label),
    ).not.toContain("settings.update.runtime_assets_check");
  });

  test("a failed Wi-Fi journey marks the failed stage and points at Wi-Fi recovery", () => {
    const status = createIdleUpdateStatus({
      state: "failed",
      phase: "restore",
      issues: [
        {
          phase: "restoring_hotspot",
          message: "Hotspot restart timed out",
          detail: "NetworkManager is still reconnecting to the uplink.",
        },
      ],
    });
    expect(failureSummary(status, t)?.recoveryTitle).toBe(
      "settings.update.recovery.wifi.title",
    );
    const stages = journeyStages(status, makeView({ status }), t);
    expect(stages.map((stage) => stage.phase)).toContain("stopping_hotspot");
    expect(
      stages.find((stage) => stage.phase === "restoring_hotspot")?.state,
    ).toBe("attention");
  });

  test("a running USB journey marks earlier stages done", () => {
    const status = createIdleUpdateStatus({
      state: "running",
      phase: "downloading",
      transport: "usb_internet",
    });
    const stages = journeyStages(status, makeView({ status }), t);
    expect(stages.map((stage) => stage.phase)).not.toContain(
      "stopping_hotspot",
    );
    expect(
      stages.find((stage) => stage.phase === "connecting_usb_internet")?.state,
    ).toBe("done");
    expect(stages.find((stage) => stage.phase === "downloading")?.state).toBe(
      "active",
    );
  });

  test("an empty log shows a state-specific placeholder", () => {
    expect(
      logPlaceholder(createIdleUpdateStatus({ state: "running" }), t),
    ).toEqual({
      title: "settings.update.log_running_title",
      body: "settings.update.log_running_body",
    });
    expect(
      logPlaceholder(createIdleUpdateStatus({ log_tail: ["line"] }), t),
    ).toBeNull();
  });

  test("health rows explain degradation and affected subsystems", () => {
    const health = degradedHealth();
    health.subsystems = {
      ...health.subsystems,
      database: { reason_codes: ["locked"], status: "unhealthy" },
      recorder: { reason_codes: [], status: "degraded" },
    };
    const rows = healthRows(health, t);
    expect(rows).toContainEqual({
      label: "settings.update.health.reasons",
      value:
        "settings.update.health.reason.persistence_write_error, settings.update.health.reason.processing_state stalled",
    });
    expect(rows).toContainEqual({
      label: "settings.update.health.subsystems",
      value:
        "database: settings.update.health.subsystem_state.unhealthy (locked); recorder: settings.update.health.subsystem_state.degraded",
    });
    expect(rows).toContainEqual({
      label: "settings.update.health.persistence",
      value: "disk full",
    });
  });

  test("formats durations compactly", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(42.9)).toBe("42s");
    expect(formatDuration(125)).toBe("2m 5s");
    expect(formatDuration(3725)).toBe("1h 2m 5s");
  });
});

describe("root-side helpers", () => {
  function outdatedView(version: string): UpdateView {
    const healthy = createHealthyUpdateStatus();
    return makeView({
      ssid: "Workshop",
      status: createIdleUpdateStatus({
        runtime: { ...createIdleUpdateStatus().runtime, version },
      }),
      health: {
        ...healthy,
        subsystems: {
          ...healthy.subsystems,
          root_side: {
            status: "degraded",
            reason_codes: ["root_side_outdated"],
          },
        },
        root_side: { ...healthy.root_side, state: "outdated" },
      },
    });
  }

  test("an outdated root side names the release tag to reinstall from", () => {
    const fix = rootSideFix(outdatedView("2026.10.4.32"), t);
    const tag = { tag: "server-v2026.10.4.32" };
    expect(fix).toEqual({
      summary: `settings.update.root_side.summary:${JSON.stringify(tag)}`,
      imageStep: `settings.update.root_side.image_step:${JSON.stringify(tag)}`,
      gitStep: `settings.update.root_side.git_step:${JSON.stringify(tag)}`,
      runbookLabel: "settings.update.root_side.runbook",
    });
    expect(rootSideFix(outdatedView("unknown"), t)?.gitStep).toContain(
      "settings.update.root_side.this_release",
    );
  });

  test("an outdated root side shows as its subsystem without blocking the update", () => {
    const view = outdatedView("2026.10.4.32");
    expect(canStart(view, t)).toBe(true);
    if (!view.health) {
      throw new Error("outdatedView always has health");
    }
    expect(healthRows(view.health, t)).toContainEqual({
      label: "settings.update.health.subsystems",
      value:
        "root side: settings.update.health.subsystem_state.degraded (root_side_outdated)",
    });
  });

  test("a current or unmanaged root side shows no fix", () => {
    const healthy = createHealthyUpdateStatus();
    expect(rootSideFix(makeView(), t)).toBeNull();
    expect(
      rootSideFix(
        makeView({
          health: {
            ...healthy,
            root_side: { ...healthy.root_side, state: "not_installed" },
          },
        }),
        t,
      ),
    ).toBeNull();
  });
});

describe("USB internet status", () => {
  test("lists the uplink details that are present", () => {
    expect(internetBadge(USABLE_USB, t)).toEqual({
      text: "settings.internet.state.usable",
      variant: "ok",
    });
    expect(internetRows(USABLE_USB, t)).toEqual([
      {
        label: "settings.internet.detected",
        value: "settings.internet.bool.yes",
      },
      {
        label: "settings.internet.usable",
        value: "settings.internet.bool.yes",
      },
      { label: "settings.internet.interface", value: "usb0" },
      { label: "settings.internet.addresses", value: "192.168.42.17/24" },
      {
        label: "settings.internet.default_route",
        value: "settings.internet.bool.yes",
      },
      { label: "settings.internet.diagnostic", value: "USB internet ready" },
    ]);
    expect(
      internetBadge(createUsbInternetStatus({ detected: true }), t).variant,
    ).toBe("warn");
  });
});
