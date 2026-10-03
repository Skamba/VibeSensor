import type {
  HealthStatusPayload,
  UpdateIssue,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../api/types";
import type {
  Readiness,
  ReadinessItem,
  Stage,
  StageState,
  StatusRow,
  Variant,
} from "../../components/maintenance";
import { formatEpochTimestamp } from "../../format";

/** Pure text and state derivations for the Internet and Update tabs. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;
export type Transport = UpdateStartRequestPayload["transport"];

export interface UpdateView {
  status: UpdateStatusPayload | null;
  health: HealthStatusPayload | null;
  internet: UsbInternetStatusPayload;
  /** The transport the user picked; the running job's transport wins. */
  transportChoice: Transport;
  ssid: string;
}

export interface Badge {
  text: string;
  variant: Variant;
}

export interface FailureSummary {
  phaseLabel: string;
  message: string | null;
  detail: string | null;
  recoveryTitle: string;
  recoveryDetail: string;
}

const STATE_VARIANTS: Record<UpdateStatusPayload["state"], Variant> = {
  idle: "muted",
  running: "warn",
  success: "ok",
  failed: "bad",
};
const ASSET_ISSUE_RE = /asset|artifacts|stale|hash|missing/i;
const WIFI_STAGES = [
  "validating",
  "stopping_hotspot",
  "connecting_wifi",
  "checking",
  "downloading",
  "installing",
  "restoring_hotspot",
  "done",
] as const;
const USB_STAGES = [
  "validating",
  "connecting_usb_internet",
  "checking",
  "downloading",
  "installing",
  "done",
] as const;
const RECOVERY_GUIDANCE: Record<string, string> = {
  stopping_hotspot: "wifi",
  connecting_wifi: "wifi",
  restoring_hotspot: "wifi",
  connecting_usb_internet: "usb",
  checking: "network",
  downloading: "network",
  installing: "install",
};
const HEALTH_VARIANTS: Record<HealthStatusPayload["status"], Variant> = {
  ok: "ok",
  warn: "warn",
  degraded: "warn",
};
const HEALTH_REASON_KEYS = new Set([
  "processing_failures",
  "frames_dropped",
  "queue_overflow_drops",
  "server_queue_drops",
  "parse_errors",
  "persistence_write_error",
]);
const SUBSYSTEM_RANK = { ready: 0, degraded: 1, unhealthy: 2 } as const;

export function offlineInternetStatus(t: Translate): UsbInternetStatusPayload {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: t("settings.internet.load_failed"),
  };
}

export function isRunning(view: UpdateView): boolean {
  return view.status?.state === "running";
}

export function activeTransport(view: UpdateView): Transport {
  if (view.status?.state === "running") {
    return view.status.transport === "usb_internet" ? "usb_internet" : "wifi";
  }
  return view.internet.usable && view.transportChoice === "usb_internet"
    ? "usb_internet"
    : "wifi";
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) {
    return "—";
  }
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`;
  }
  return minutes > 0 ? `${minutes}m ${secs}s` : `${secs}s`;
}

function normalizePhase(phase: string | null | undefined): string {
  if (!phase) {
    return "idle";
  }
  return phase === "restore" ? "restoring_hotspot" : phase;
}

export function formatPhase(
  phase: string | null | undefined,
  t: Translate,
): string {
  const normalized = normalizePhase(phase);
  const key = `settings.update.phase.${normalized}`;
  const text = t(key);
  return text === key ? normalized : text;
}

/** The issue raised in the failed phase, else the most recent issue. */
function primaryIssue(status: UpdateStatusPayload): UpdateIssue | null {
  const phase = normalizePhase(status.phase);
  const latestFirst = [...status.issues].reverse();
  return (
    latestFirst.find((issue) => normalizePhase(issue.phase) === phase) ??
    latestFirst[0] ??
    null
  );
}

export function failureSummary(
  status: UpdateStatusPayload,
  t: Translate,
): FailureSummary | null {
  if (status.state !== "failed") {
    return null;
  }
  const issue = primaryIssue(status);
  const phase = issue?.phase ?? status.phase;
  const guidance = RECOVERY_GUIDANCE[normalizePhase(phase)] ?? "generic";
  return {
    phaseLabel: formatPhase(phase, t),
    message: issue?.message ?? null,
    detail: issue?.detail ?? null,
    recoveryTitle: t(`settings.update.recovery.${guidance}.title`),
    recoveryDetail: t(`settings.update.recovery.${guidance}.detail`),
  };
}

function healthBlocksUpdate(health: HealthStatusPayload | null): boolean {
  return (
    health !== null &&
    (health.status === "degraded" ||
      health.persistence.write_error != null ||
      health.startup_error != null ||
      health.db_corruption_detected === true)
  );
}

function readinessItems(view: UpdateView, t: Translate): ReadinessItem[] {
  const usingUsb = activeTransport(view) === "usb_internet";
  const ssid = view.ssid.trim();
  const items: ReadinessItem[] = [
    {
      label: t("settings.update.readiness.item.source"),
      detail: t(
        usingUsb
          ? "settings.update.readiness.item.source_usb"
          : "settings.update.readiness.item.source_wifi",
      ),
      state: "ready",
    },
    usingUsb
      ? {
          label: t("settings.update.readiness.item.connection"),
          detail: view.internet.usable
            ? t("settings.update.readiness.item.connection_usb_ready", {
                interface:
                  view.internet.interface_name ||
                  t("settings.update.transport.usb_title"),
              })
            : t("settings.update.readiness.item.connection_usb_blocked"),
          state: view.internet.usable ? "ready" : "blocked",
        }
      : {
          label: t("settings.update.readiness.item.connection"),
          detail: t(
            ssid
              ? "settings.update.readiness.item.connection_wifi_ready"
              : "settings.update.readiness.item.connection_wifi_blocked",
          ),
          state: ssid ? "ready" : "blocked",
        },
  ];
  if (healthBlocksUpdate(view.health)) {
    items.push({
      label: t("settings.update.readiness.item.health"),
      detail: t("settings.update.readiness.item.health_blocked"),
      state: "blocked",
    });
  }
  return items;
}

/** The start checklist, or the recovery checklist after a failed update. */
export function startReadiness(view: UpdateView, t: Translate): Readiness {
  const items = readinessItems(view, t);
  const blocked = items.some((item) => item.state === "blocked");
  const failure = view.status ? failureSummary(view.status, t) : null;
  if (failure) {
    const captured = failure.message
      ? failure.detail
        ? `${failure.message} — ${failure.detail}`
        : failure.message
      : failure.detail || failure.phaseLabel;
    return {
      title: t("settings.update.recovery.title"),
      summary: t(
        blocked
          ? "settings.update.recovery.summary_blocked"
          : "settings.update.recovery.summary_retry",
      ),
      stateLabel: t(
        blocked
          ? "maintenance.readiness.blocked"
          : "settings.update.state.failed",
      ),
      stateVariant: "bad",
      items: [
        {
          label: t("settings.update.recovery.item.failed_step"),
          detail: failure.phaseLabel,
          state: "attention",
        },
        {
          label: t("settings.update.recovery.item.captured_detail"),
          detail: captured,
          state: "attention",
        },
        {
          label: t("settings.update.recovery.item.next_step"),
          detail: blocked
            ? t("settings.update.recovery.item.next_step_blocked")
            : `${failure.recoveryTitle} — ${failure.recoveryDetail}`,
          state: blocked ? "blocked" : "attention",
        },
      ],
    };
  }
  const running = isRunning(view);
  const readiness = running ? "running" : blocked ? "blocked" : "ready";
  return {
    title: t("settings.update.readiness.title"),
    summary: t(`settings.update.readiness.summary_${readiness}`),
    stateLabel: t(`maintenance.readiness.${readiness}`),
    stateVariant: running ? "warn" : blocked ? "bad" : "ok",
    items,
  };
}

export function canStart(view: UpdateView, t: Translate): boolean {
  if (isRunning(view)) {
    return false;
  }
  const recovering = view.status?.state === "failed";
  return (
    recovering ||
    !readinessItems(view, t).some((item) => item.state === "blocked")
  );
}

export function startLabel(view: UpdateView, t: Translate): string {
  return t(
    view.status?.state === "failed"
      ? "settings.update.retry"
      : "settings.update.start",
  );
}

export function usbSummary(
  internet: UsbInternetStatusPayload,
  t: Translate,
): string {
  if (!internet.usable) {
    return t("settings.update.transport.usb_summary_unavailable");
  }
  return internet.interface_name
    ? t("settings.update.transport.usb_summary_interface", {
        interface: internet.interface_name,
      })
    : t("settings.update.transport.usb_summary");
}

export function internetBadge(
  internet: UsbInternetStatusPayload,
  t: Translate,
): Badge {
  const state = internet.usable
    ? "usable"
    : internet.detected
      ? "detected"
      : "not_detected";
  return {
    text: t(`settings.internet.state.${state}`),
    variant: internet.usable ? "ok" : internet.detected ? "warn" : "muted",
  };
}

export function internetSummary(
  internet: UsbInternetStatusPayload,
  t: Translate,
): string {
  const state = internet.usable
    ? "usable"
    : internet.detected
      ? "detected"
      : "not_detected";
  return t(`settings.internet.summary.${state}`);
}

export function internetRows(
  internet: UsbInternetStatusPayload,
  t: Translate,
): StatusRow[] {
  const yesNo = (value: boolean) =>
    t(value ? "settings.internet.bool.yes" : "settings.internet.bool.no");
  const optional: Array<[string, string | null | undefined]> = [
    ["settings.internet.interface", internet.interface_name],
    ["settings.internet.connection", internet.connection_name],
    ["settings.internet.driver", internet.driver],
    ["settings.internet.addresses", internet.ipv4_addresses.join(", ")],
    ["settings.internet.gateway", internet.gateway],
  ];
  return [
    { label: t("settings.internet.detected"), value: yesNo(internet.detected) },
    { label: t("settings.internet.usable"), value: yesNo(internet.usable) },
    ...optional
      .filter(([, value]) => Boolean(value))
      .map(([key, value]) => ({ label: t(key), value: value ?? "" })),
    {
      label: t("settings.internet.default_route"),
      value: yesNo(internet.has_default_route),
    },
    { label: t("settings.internet.diagnostic"), value: internet.diagnostic },
  ];
}

export function stateBadge(status: UpdateStatusPayload, t: Translate): Badge {
  return {
    text: t(`settings.update.state.${status.state}`),
    variant: STATE_VARIANTS[status.state] ?? "muted",
  };
}

function transportValue(status: UpdateStatusPayload, t: Translate): string {
  if (status.transport === "usb_internet") {
    return status.uplink_interface
      ? t("settings.update.transport_value.usb_interface", {
          interface: status.uplink_interface,
        })
      : t("settings.update.transport_value.usb");
  }
  return status.ssid
    ? t("settings.update.transport_value.wifi_ssid", { ssid: status.ssid })
    : t("settings.update.transport_value.wifi");
}

export function currentStatusSummary(
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  t: Translate,
): string {
  const kind =
    status.state === "idle"
      ? health.status !== "ok" || health.persistence.write_error
        ? "attention"
        : "ready"
      : status.state;
  return t(`settings.update.current_status_summary.${kind}`);
}

export function currentStatusRows(
  status: UpdateStatusPayload,
  t: Translate,
): StatusRow[] {
  const active = status.state !== "idle";
  const rows: StatusRow[] = [];
  const add = (key: string, value: string) =>
    rows.push({ label: t(key), value });
  if (status.transport === "usb_internet" || status.ssid) {
    add("settings.update.transport_label", transportValue(status, t));
  }
  if (active) {
    add("settings.update.phase_label", formatPhase(status.phase, t));
  }
  if (status.started_at != null) {
    add("settings.update.started_at", formatEpochTimestamp(status.started_at));
  }
  if (active && status.phase_started_at != null) {
    add(
      "settings.update.phase_started_at",
      formatEpochTimestamp(status.phase_started_at),
    );
  }
  if (active && status.phase_elapsed_s != null) {
    add(
      "settings.update.phase_elapsed",
      formatDuration(status.phase_elapsed_s),
    );
  }
  if (status.finished_at != null) {
    add(
      "settings.update.finished_at",
      formatEpochTimestamp(status.finished_at),
    );
  }
  if (status.last_success_at != null) {
    add(
      "settings.update.last_success",
      formatEpochTimestamp(status.last_success_at),
    );
  }
  const { runtime } = status;
  if (runtime.version && runtime.version !== "unknown") {
    add("settings.update.runtime_version", runtime.version);
  }
  if (runtime.commit) {
    add("settings.update.runtime_commit", runtime.commit.slice(0, 12));
  }
  if (runtime.static_assets_hash) {
    add(
      "settings.update.runtime_assets",
      runtime.static_assets_hash.slice(0, 12),
    );
    const assetIssue = status.issues.some((issue) =>
      ASSET_ISSUE_RE.test(`${issue.message} ${issue.detail}`),
    );
    if (status.state !== "failed" || assetIssue) {
      add(
        "settings.update.runtime_assets_check",
        t(
          runtime.assets_verified
            ? "settings.update.runtime_assets_ok"
            : "settings.update.runtime_assets_bad",
        ),
      );
    }
  }
  return rows;
}

export function healthBadge(health: HealthStatusPayload, t: Translate): Badge {
  return {
    text: t(`settings.update.health.state.${health.status}`),
    variant: health.persistence.write_error
      ? "bad"
      : HEALTH_VARIANTS[health.status],
  };
}

export function healthSummary(
  health: HealthStatusPayload,
  t: Translate,
): string {
  const kind =
    health.persistence.write_error || health.status === "degraded"
      ? "degraded"
      : health.status === "warn"
        ? "warn"
        : "ok";
  return t(`settings.update.health_card_summary.${kind}`);
}

function healthReason(reason: string, t: Translate): string {
  if (reason.startsWith("processing_state:")) {
    const state = reason.slice("processing_state:".length);
    return `${t("settings.update.health.reason.processing_state")} ${state}`;
  }
  return HEALTH_REASON_KEYS.has(reason)
    ? t(`settings.update.health.reason.${reason}`)
    : reason;
}

export function healthRows(
  health: HealthStatusPayload,
  t: Translate,
): StatusRow[] {
  const rows: StatusRow[] = [];
  const add = (key: string, value: string) =>
    rows.push({ label: t(key), value });
  add("settings.update.health.processing_state", health.processing_state);
  if (health.processing_failures > 0) {
    add(
      "settings.update.health.processing_failures",
      String(health.processing_failures),
    );
  }
  if (health.degradation_reasons.length) {
    add(
      "settings.update.health.reasons",
      health.degradation_reasons
        .map((reason) => healthReason(reason, t))
        .join(", "),
    );
  }
  const affected = Object.entries(health.subsystems)
    .filter(([, subsystem]) => subsystem.status !== "ready")
    .sort(
      ([leftName, left], [rightName, right]) =>
        SUBSYSTEM_RANK[right.status] - SUBSYSTEM_RANK[left.status] ||
        leftName.localeCompare(rightName),
    );
  if (affected.length) {
    add(
      "settings.update.health.subsystems",
      affected
        .map(([name, subsystem]) => {
          const state = t(
            `settings.update.health.subsystem_state.${subsystem.status}`,
          );
          const reasons = subsystem.reason_codes.length
            ? ` (${subsystem.reason_codes.join(", ")})`
            : "";
          return `${name.replaceAll("_", " ")}: ${state}${reasons}`;
        })
        .join("; "),
    );
  }
  const loss = health.data_loss;
  if (loss.affected_clients > 0) {
    add(
      "settings.update.health.affected_clients",
      `${loss.affected_clients}/${loss.tracked_clients}`,
    );
    add(
      "settings.update.health.data_loss",
      `frames=${loss.frames_dropped}, queue=${loss.queue_overflow_drops}, server=${loss.server_queue_drops}, parse=${loss.parse_errors}`,
    );
  }
  const persistence = health.persistence;
  const queueDepth = persistence.analysis_queue_depth ?? 0;
  if (
    persistence.analysis_in_progress ||
    persistence.write_error ||
    queueDepth > 0
  ) {
    add(
      "settings.update.health.persistence",
      persistence.write_error || t("settings.update.health.persistence_ok"),
    );
    if (persistence.analysis_in_progress) {
      add(
        "settings.update.health.analysis",
        t("settings.update.health.analysis_in_progress"),
      );
    }
    if (persistence.analysis_active_run_id) {
      add(
        "settings.update.health.analysis_run",
        persistence.analysis_active_run_id,
      );
    }
    if (persistence.analysis_started_at != null) {
      add(
        "settings.update.health.analysis_started_at",
        formatEpochTimestamp(persistence.analysis_started_at),
      );
    }
    if (persistence.analysis_elapsed_s != null) {
      add(
        "settings.update.health.analysis_elapsed",
        formatDuration(persistence.analysis_elapsed_s),
      );
    }
    if (queueDepth > 0) {
      add("settings.update.health.analysis_queue_depth", String(queueDepth));
    }
  }
  return rows;
}

function stageState(
  status: UpdateStatusPayload,
  current: number,
  index: number,
): StageState {
  if (status.state === "success") {
    return "done";
  }
  if (status.state === "idle" || current === -1 || index > current) {
    return "upcoming";
  }
  if (index < current) {
    return "done";
  }
  return status.state === "failed" ? "attention" : "active";
}

export function journeyStages(
  status: UpdateStatusPayload,
  view: UpdateView,
  t: Translate,
): Stage[] {
  const transport =
    status.state === "idle"
      ? activeTransport(view)
      : status.transport === "usb_internet"
        ? "usb_internet"
        : "wifi";
  const phases = transport === "usb_internet" ? USB_STAGES : WIFI_STAGES;
  const current = (phases as readonly string[]).indexOf(
    normalizePhase(status.phase),
  );
  return phases.map((phase, index) => {
    const state = stageState(status, current, index);
    return {
      phase,
      state,
      title: t(`settings.update.phase.${phase}`),
      detail: t(`settings.update.journey.detail.${phase}`),
      stateText: t(`maintenance.stage_state.${state}`),
    };
  });
}

export function latestAttemptRows(
  status: UpdateStatusPayload,
  t: Translate,
): StatusRow[] | null {
  if (status.state === "idle" || status.state === "running") {
    return null;
  }
  const rows: StatusRow[] = [];
  if (status.started_at != null) {
    rows.push({
      label: t("settings.update.started_at"),
      value: formatEpochTimestamp(status.started_at),
    });
  }
  if (status.finished_at != null) {
    rows.push({
      label: t("settings.update.finished_at"),
      value: formatEpochTimestamp(status.finished_at),
    });
  }
  rows.push({
    label: t("settings.update.transport_label"),
    value: transportValue(status, t),
  });
  if (status.exit_code != null) {
    rows.push({
      label: t("settings.update.exit_code"),
      value: String(status.exit_code),
    });
  }
  return rows;
}

/** Placeholder for the updater log while it has no lines yet. */
export function logPlaceholder(
  status: UpdateStatusPayload,
  t: Translate,
): { title: string; body: string } | null {
  if (status.log_tail.length > 0) {
    return null;
  }
  const kind =
    status.state === "running"
      ? "running"
      : status.state === "failed"
        ? "failed"
        : "empty";
  return {
    title: t(`settings.update.log_${kind}_title`),
    body: t(`settings.update.log_${kind}_body`),
  };
}
