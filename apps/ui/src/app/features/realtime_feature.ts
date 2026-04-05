import type { UiCarsDom } from "../dom/cars_dom";
import type { UiRealtimeDom } from "../dom/realtime_dom";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { UiShellDom } from "../dom/shell_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import { deriveCarSelectionState } from "../car_selection_state";
import type { RealtimeState, SettingsState, SpectrumState } from "../ui_app_state";
import type { LocationOption, LoggingStatusPayload } from "../../api/types";
import type { AdaptedClient } from "../../server_payload";
import {
  getClientLocations,
  getLoggingStatus,
  identifyClient as identifyClientApi,
  removeClient as removeClientApi,
  setClientLocation as setClientLocationApi,
  startLoggingRun,
  stopLoggingRun,
} from "../../api";
import { defaultLocationCodes } from "../../constants";
import {
  getInlineStateAction,
  renderInlineStatePanel,
  type InlineStateActionVariant,
} from "../views/dom_helpers";
import {
  getRealtimeSensorTableClickAction,
  getRealtimeSensorTableLocationChange,
  renderRealtimeSensorOverview,
  renderRealtimeSensorTable,
} from "../views/realtime_sensor_table_view";
import { createPollingController } from "./polling_controller";
import { classifyDataFreshness } from "./data_freshness";
import { createRealtimeSensorState } from "./realtime_sensor_state";

export interface RealtimeFeatureDeps extends FeatureDepsBase {
  dom: UiRealtimeDom;
  shellDom: Pick<UiShellDom, "menuButtons">;
  settingsDom: Pick<UiSettingsDom, "settingsTabs">;
  carsDom: Pick<UiCarsDom, "addCarBtn">;
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  getLanguage: () => string;
  formatInt: (value: number) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
  sendSelection: () => void;
  onRecordingStatusChanged: () => Promise<void>;
}

export interface RealtimeFeature {
  bindHandlers(): void;
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  maybeRenderSensorsSettingsList(force?: boolean): void;
  updateClientSelection(): void;
  locationCodeForClient(client: AdaptedClient): string;
  renderStatus(clientRow?: AdaptedClient): void;
  renderLoggingStatus(): void;
  refreshLoggingStatus(): Promise<void>;
  startLogging(): Promise<void>;
  stopLogging(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

type CaptureReadinessPayload = NonNullable<LoggingStatusPayload["capture_readiness"]>;
type CaptureReadinessCheckPayload = CaptureReadinessPayload["checks"][number];

export function createRealtimeFeature(ctx: RealtimeFeatureDeps): RealtimeFeature {
  const {
    realtime,
    settings,
    spectrum,
    dom: els,
    shellDom,
    settingsDom,
    carsDom,
    t,
    escapeHtml,
    formatInt,
    setPillState,
  } = ctx;
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  const LOGGING_STATUS_IDLE_POLL_MS = 2_000;
  const LOGGING_STATUS_ACTIVE_POLL_MS = 2_000;
  const LOGGING_STATUS_ERROR_POLL_MS = 5_000;
  let handlersBound = false;
  let pendingLoggingAction: "starting" | "stopping" | null = null;
  let loggingElapsedTimer: ReturnType<typeof setInterval> | null = null;
  let lastCompletedElapsedText = "--";
  let renderedLoggingSummarySignature: string | null = null;
  let idleCaptureReadinessRefreshInFlight = false;
  let lastIdleCaptureReadinessSignature: string | null = null;

  const CAPTURE_READINESS_ORDER = [
    "sensors_ready",
    "reference_ready",
    "speed_stable",
    "capture_ready",
  ] as const;

  const sensorState = createRealtimeSensorState({
    realtime,
    settings,
    spectrum,
    getLanguage: ctx.getLanguage,
    t,
    formatInt,
  });
  const {
    activeCarDisplayState,
    assignedClientCount,
    buildLocationOptions,
    computeLiveHealth,
    connectedClients,
    hasActiveCarSelection,
    locationCodeForClient,
    strongestSignal,
    strongestSignalText,
  } = sensorState;

  function applyLocationCodes(codes: string[]): void {
    realtime.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
    realtime.locationOptions = buildLocationOptions(realtime.locationCodes);
  }

  function renderActiveCarStat(): void {
    const container = els.liveActiveCar;
    const valueEl = container?.querySelector<HTMLElement>("[data-value]");
    if (!container || !valueEl) {
      return;
    }
    const state = activeCarDisplayState();
    container.classList.toggle("stat--warn", state.isWarning);
    valueEl.classList.toggle("stat__value--warn", state.isWarning);
    valueEl.classList.toggle("stat__value--with-icon", state.isWarning);
    valueEl.replaceChildren();
    if (state.isWarning) {
      const iconEl = document.createElement("span");
      iconEl.className = "stat__value-icon stat__value-icon--warn";
      iconEl.setAttribute("aria-hidden", "true");
      iconEl.textContent = "!";
      const textEl = document.createElement("span");
      textEl.textContent = state.text;
      valueEl.append(iconEl, textEl);
      return;
    }
    valueEl.textContent = state.text;
  }

  function dataFreshnessText(): string {
    const connected = connectedClients();
    const ages = connected
      .map((client) => client.last_seen_age_ms)
      .filter((age): age is number => typeof age === "number" && Number.isFinite(age));
    if (!ages.length) {
      return t("dashboard.data_freshness_none");
    }
    const captureReadiness = realtime.loggingStatus.capture_readiness ?? null;
    const referenceCheck = captureReadinessCheck(captureReadiness, "reference_ready");
    const referenceReason = referenceCheck?.reason_key ?? "";
    if (
      referenceCheck
      && referenceCheck.state !== "pass"
      && [
        "speed_source_missing",
        "speed_source_not_live",
        "speed_source_fallback_active",
        "speed_sample_missing",
        "speed_sample_stale",
      ].includes(referenceReason)
    ) {
      return t("dashboard.data_freshness_sensors_only");
    }
    const ageMs = Math.max(...ages.map((age) => Math.max(0, age)));
    const ageText = t("status.age_ms_ago", { value: formatInt(ageMs) });
    const freshness = classifyDataFreshness(ageMs, connected);
    if (freshness === "fresh") {
      return t("dashboard.data_freshness_fresh", { age: ageText });
    }
    if (freshness === "delayed") {
      return t("dashboard.data_freshness_delayed", { age: ageText });
    }
    return t("dashboard.data_freshness_stale", { age: ageText });
  }

  type RecordingPanelState = {
    pillVariant: "muted" | "ok" | "warn" | "bad";
    pillText: string;
    phaseText: string;
    summaryText: string;
    summaryPanel: RecordingSummaryPanel | null;
    runIdText: string;
    elapsedText: string;
    samplesText: string;
    showStart: boolean;
    showStop: boolean;
    startDisabled: boolean;
    stopDisabled: boolean;
    showPill: boolean;
    captureReadiness: CaptureReadinessPayload | null;
    showCaptureChecklist: boolean;
    setupMode: boolean;
  };

  type RecordingSummaryAction = {
    action: "open-history" | "open-cars" | "open-add-car" | "open-sensors" | "open-speed-source";
    label: string;
    variant?: InlineStateActionVariant;
  };

  type RecordingSummaryPanel = {
    title: string;
    body: string;
    detail?: string;
    action?: RecordingSummaryAction;
  };

  function setDashboardPillState(
    el: HTMLElement | null,
    variant: "muted" | "ok" | "warn" | "bad",
    text: string,
    { hidden = false }: { hidden?: boolean } = {},
  ): void {
    setPillState(el, variant, text);
    if (el) {
      el.hidden = hidden;
    }
  }

  function computeCurrentLiveHealth() {
    return computeLiveHealth(captureReadinessSummaryText);
  }

  function renderLiveSensorRoster(): void {
    if (!els.liveSensorRoster) return;
    const signal = strongestSignal();
    renderRealtimeSensorOverview(els.liveSensorRoster, {
      clients: realtime.clients,
      locationOptions: realtime.locationOptions,
      locationCodeForClient,
      strongestClientId: signal?.client.id ?? null,
      t,
      escapeHtml,
    });
  }

  function renderLiveOverviewStats(): void {
    const signal = strongestSignal();
    const totalClients = realtime.clients.length;
    ctx.setStatValue(els.liveConnectedSensors, `${formatInt(connectedClients().length)} / ${formatInt(totalClients)}`);
    renderActiveCarStat();
    ctx.setStatValue(els.liveRecordingState, computeRecordingPanelState().phaseText);
    ctx.setStatValue(els.liveDataFreshness, dataFreshnessText());
    ctx.setStatValue(els.liveStrongestSignal, strongestSignalText(signal));
    els.liveStrongestSignal?.classList.remove("stat--spotlight");
  }

  function renderLiveHealth(): void {
    const health = computeCurrentLiveHealth();
    setDashboardPillState(els.liveRunHealth, health.variant, health.text, { hidden: !health.showOverviewPill });
    setPillState(els.shellLiveStatus, health.variant, health.text);
  }

  function sensorsSettingsSignature(): string {
    const clientPart = realtime.clients
      .map((client) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}|${client.location_code || ""}`;
      })
      .join("||");
    const locationPart = realtime.locationOptions.map((loc) => `${loc.code}|${loc.label}`).join("||");
    return `${clientPart}##${locationPart}`;
  }

  function maybeRenderSensorsSettingsList(force = false): void {
    const nextSig = sensorsSettingsSignature();
    if (!force && nextSig === realtime.sensorsSettingsSignature) return;
    realtime.sensorsSettingsSignature = nextSig;
    renderSensorsSettingsList();
    renderLiveSensorRoster();
  }

  function updateClientSelection(): void {
    const firstConnected = realtime.clients.find((c) => Boolean(c.connected));
    if (!realtime.selectedClientId && realtime.clients.length > 0) {
      realtime.selectedClientId = firstConnected ? firstConnected.id : realtime.clients[0].id;
    }
    if (realtime.selectedClientId && !realtime.clients.some((c) => c.id === realtime.selectedClientId)) {
      realtime.selectedClientId = firstConnected
        ? firstConnected.id
        : realtime.clients.length ? realtime.clients[0].id : null;
    }
  }

  function renderSensorsSettingsList(): void {
    if (!els.sensorsSettingsBody) return;
    renderRealtimeSensorTable(els.sensorsSettingsBody, {
      clients: realtime.clients,
      locationOptions: realtime.locationOptions,
      locationCodeForClient,
      t,
      escapeHtml,
    });
  }

  function renderStatus(clientRow?: AdaptedClient): void {
    void clientRow;
    renderLiveOverviewStats();
  }

  function clearLoggingElapsedTimer(): void {
    if (loggingElapsedTimer === null) return;
    clearInterval(loggingElapsedTimer);
    loggingElapsedTimer = null;
  }

  function formatElapsed(startTimeUtc: string | null | undefined): string {
    if (!startTimeUtc) return "--";
    const startMs = Date.parse(startTimeUtc);
    if (!Number.isFinite(startMs)) return "--";
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function syncLoggingElapsedTimer(): void {
    const shouldTick = handlersBound && Boolean(realtime.loggingStatus.enabled && realtime.loggingStatus.start_time_utc);
    if (!shouldTick) {
      clearLoggingElapsedTimer();
      return;
    }
    if (loggingElapsedTimer !== null) return;
    loggingElapsedTimer = setInterval(() => {
      ctx.setStatValue(els.loggingElapsed, formatElapsed(realtime.loggingStatus.start_time_utc));
    }, 1_000);
  }

  function recordingRunIdText(status = realtime.loggingStatus): string {
    if (status.enabled && status.run_id) {
      return t("dashboard.logging.run_id", { runId: status.run_id });
    }
    if (status.last_completed_run_id) {
      return t("dashboard.logging.last_run_id", { runId: status.last_completed_run_id });
    }
    return "";
  }

  function activatePrimaryView(viewId: string): void {
    shellDom.menuButtons.find((button) => button.dataset.view === viewId)?.click();
  }

  function activateSettingsTab(tabId: string): void {
    settingsDom.settingsTabs.find((button) => button.getAttribute("data-settings-tab") === tabId)?.click();
  }

  function openSettingsView(tabId: string): void {
    activatePrimaryView("settingsView");
    activateSettingsTab(tabId);
  }

  function openCarsView({ openWizard = false }: { openWizard?: boolean } = {}): void {
    openSettingsView("carTab");
    if (openWizard) {
      carsDom.addCarBtn.click();
    }
  }

  function renderRecordingSummaryPanel(panel: RecordingSummaryPanel): string {
    return renderInlineStatePanel({
      titleHtml: escapeHtml(panel.title),
      bodyHtml: escapeHtml(panel.body),
      detailHtml: panel.detail ? escapeHtml(panel.detail) : undefined,
      action: panel.action
        ? {
          action: panel.action.action,
          labelHtml: escapeHtml(panel.action.label),
          variant: panel.action.variant,
        }
        : undefined,
    });
  }

  function loggingSummarySignature(summaryText: string, summaryPanel: RecordingSummaryPanel | null): string {
    if (summaryPanel === null) {
      return `text:${summaryText}`;
    }
    const actionSignature = summaryPanel.action
      ? `${summaryPanel.action.action}|${summaryPanel.action.label}|${summaryPanel.action.variant ?? ""}`
      : "";
    return `panel:${summaryPanel.title}|${summaryPanel.body}|${summaryPanel.detail ?? ""}|${actionSignature}`;
  }

  function renderLoggingSummaryContent(summaryText: string, summaryPanel: RecordingSummaryPanel | null): void {
    if (!els.loggingSummary) {
      return;
    }
    const loggingSummary = els.loggingSummary;
    const nextSignature = loggingSummarySignature(summaryText, summaryPanel);

    loggingSummary.hidden = summaryText === "" && summaryPanel === null;
    if (renderedLoggingSummarySignature !== nextSignature) {
      if (summaryPanel) {
        loggingSummary.innerHTML = renderRecordingSummaryPanel(summaryPanel);
      } else {
        loggingSummary.textContent = summaryText;
      }
      renderedLoggingSummarySignature = nextSignature;
    }
    loggingSummary.classList.toggle("logging-summary--panel", summaryPanel !== null);
  }

  function blockedRecordingPanel(): RecordingSummaryPanel {
    const selection = deriveCarSelectionState(settings);
    if (selection.kind === "no_cars") {
      return {
        title: t("dashboard.logging.blocked.no_cars.title"),
        body: t("dashboard.logging.blocked.no_cars.body"),
        detail: t("dashboard.logging.blocked.no_cars.detail"),
        action: {
          action: "open-add-car",
          label: t("dashboard.logging.blocked.no_cars.action"),
          variant: "success",
        },
      };
    }
    return {
      title: t("dashboard.logging.blocked.no_active.title"),
      body: t("dashboard.logging.blocked.no_active.body"),
      detail: t("dashboard.logging.blocked.no_active.detail"),
      action: {
        action: "open-cars",
        label: t("dashboard.logging.blocked.no_active.action"),
      },
    };
  }

  function setupRecordingAction(check: CaptureReadinessCheckPayload): RecordingSummaryAction | undefined {
    if (check.check_key === "sensors_ready") {
      return {
        action: "open-sensors",
        label: t("dashboard.logging.blocked.setup.action.sensors"),
      };
    }
    if (check.check_key === "reference_ready") {
      if (check.reason_key === "active_car_missing" || check.reason_key === "order_reference_incomplete") {
        return {
          action: "open-cars",
          label: t("dashboard.logging.blocked.setup.action.cars"),
        };
      }
      return {
        action: "open-speed-source",
        label: t("dashboard.logging.blocked.setup.action.speed_source"),
      };
    }
    if (check.check_key === "speed_stable" && check.reason_key === "speed_sample_missing") {
      return {
        action: "open-speed-source",
        label: t("dashboard.logging.blocked.setup.action.speed_source"),
      };
    }
    return undefined;
  }

  function setupRecordingPanel(readiness: CaptureReadinessPayload | null): RecordingSummaryPanel | null {
    if (!readiness || readiness.is_ready) {
      return null;
    }
    const primaryCheck = readiness.checks.find((check) => (
      check.state === "fail" && check.check_key !== "capture_ready"
    )) ?? captureReadinessCheck(readiness, "capture_ready");
    if (!primaryCheck) {
      return null;
    }
    return {
      title: t("dashboard.logging.blocked.setup.title"),
      body: captureReadinessDetailText(primaryCheck),
      detail: undefined,
      action: setupRecordingAction(primaryCheck),
    };
  }

  function postRunSummaryPanel(kind: "processing" | "saved", runId: string): RecordingSummaryPanel {
    if (kind === "processing") {
      return {
        title: t("dashboard.logging.processing.title", { runId }),
        body: t("dashboard.logging.processing.body"),
        detail: t("dashboard.logging.processing.detail"),
        action: {
          action: "open-history",
          label: t("dashboard.logging.processing.action"),
        },
      };
    }
    return {
      title: t("dashboard.logging.saved.title", { runId }),
      body: t("dashboard.logging.saved.body"),
      detail: t("dashboard.logging.saved.detail"),
      action: {
        action: "open-history",
        label: t("dashboard.logging.saved.action"),
      },
    };
  }

  function captureReadinessCheck(
    readiness: CaptureReadinessPayload | null,
    checkKey: CaptureReadinessCheckPayload["check_key"],
  ): CaptureReadinessCheckPayload | null {
    return readiness?.checks.find((check) => check.check_key === checkKey) ?? null;
  }

  function captureReadinessDetailNumber(
    check: CaptureReadinessCheckPayload | null,
    key: string,
  ): number | null {
    const value = check?.details?.[key];
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function captureReadinessStateText(state: CaptureReadinessCheckPayload["state"]): string {
    return t(`dashboard.capture_readiness.state.${state}`);
  }

  function captureReadinessCheckLabel(checkKey: CaptureReadinessCheckPayload["check_key"]): string {
    return t(`dashboard.capture_readiness.${checkKey}.label`);
  }

  function captureReadinessDetailText(check: CaptureReadinessCheckPayload): string {
    if (check.check_key === "sensors_ready") {
      const liveSensorCount = Math.max(
        0,
        Math.ceil(captureReadinessDetailNumber(check, "live_sensor_count") ?? 0),
      );
      const unassignedSensorCount = Math.max(
        0,
        Math.ceil(captureReadinessDetailNumber(check, "unassigned_sensor_count") ?? 0),
      );
      const quietPeriodRemaining = Math.max(
        0,
        Math.ceil(captureReadinessDetailNumber(check, "quiet_period_remaining_s") ?? 0),
      );
      if (check.reason_key === "no_live_sensors") {
        return t("dashboard.capture_readiness.sensors_ready.no_live_sensors");
      }
      if (check.reason_key === "sensor_locations_missing") {
        return t("dashboard.capture_readiness.sensors_ready.sensor_locations_missing", {
          count: formatInt(unassignedSensorCount),
        });
      }
      if (check.reason_key === "recent_integrity_events") {
        return t("dashboard.capture_readiness.sensors_ready.recent_integrity_events", {
          seconds: formatInt(quietPeriodRemaining),
        });
      }
      if (check.reason_key === "limited_sensor_coverage") {
        return t("dashboard.capture_readiness.sensors_ready.limited_sensor_coverage", {
          count: formatInt(liveSensorCount),
        });
      }
      return t("dashboard.capture_readiness.sensors_ready.ready", {
        count: formatInt(liveSensorCount),
      });
    }

    if (check.check_key === "reference_ready") {
      if (check.reason_key === "active_car_missing") {
        return t("dashboard.capture_readiness.reference_ready.active_car_missing");
      }
      if (check.reason_key === "order_reference_incomplete") {
        return t("dashboard.capture_readiness.reference_ready.order_reference_incomplete");
      }
      if (check.reason_key === "speed_source_missing") {
        return t("dashboard.capture_readiness.reference_ready.speed_source_missing");
      }
      if (check.reason_key === "speed_source_not_live") {
        return t("dashboard.capture_readiness.reference_ready.speed_source_not_live");
      }
      if (check.reason_key === "speed_source_fallback_active") {
        return t("dashboard.capture_readiness.reference_ready.speed_source_fallback_active");
      }
      if (check.reason_key === "speed_sample_stale") {
        return t("dashboard.capture_readiness.reference_ready.speed_sample_stale");
      }
      if (check.reason_key === "speed_sample_missing") {
        return t("dashboard.capture_readiness.reference_ready.speed_sample_missing");
      }
      if (check.reason_key === "obd_rpm_missing") {
        return t("dashboard.capture_readiness.reference_ready.obd_rpm_missing");
      }
      if (check.reason_key === "obd_rpm_stale") {
        return t("dashboard.capture_readiness.reference_ready.obd_rpm_stale");
      }
      return t("dashboard.capture_readiness.reference_ready.ready");
    }

    if (check.check_key === "speed_stable") {
      const dwellRemaining = Math.max(
        0,
        Math.ceil(captureReadinessDetailNumber(check, "dwell_remaining_s") ?? 0),
      );
      const minimumSpeed = Math.max(
        0,
        Math.ceil(captureReadinessDetailNumber(check, "minimum_speed_kmh") ?? 20),
      );
      if (check.reason_key === "speed_sample_missing") {
        return t("dashboard.capture_readiness.speed_stable.speed_sample_missing");
      }
      if (check.reason_key === "speed_too_low") {
        return t("dashboard.capture_readiness.speed_stable.speed_too_low", {
          minimumSpeed: formatInt(minimumSpeed),
        });
      }
      if (check.reason_key === "speed_stabilizing") {
        return t("dashboard.capture_readiness.speed_stable.speed_stabilizing", {
          seconds: formatInt(dwellRemaining),
        });
      }
      if (check.reason_key === "speed_variation_high") {
        return t("dashboard.capture_readiness.speed_stable.speed_variation_high");
      }
      return t("dashboard.capture_readiness.speed_stable.ready");
    }

    if (check.check_key === "capture_ready") {
      if (check.reason_key === "capture_blocked") {
        return t("dashboard.capture_readiness.capture_ready.capture_blocked");
      }
      if (check.reason_key === "ready_with_warnings") {
        return t("dashboard.capture_readiness.capture_ready.ready_with_warnings");
      }
      return t("dashboard.capture_readiness.capture_ready.ready");
    }

    return captureReadinessCheckLabel(check.check_key);
  }

  function captureReadinessSummaryText(readiness: CaptureReadinessPayload | null): string {
    if (!readiness) {
      return "";
    }
    const primaryCheck = readiness.is_ready
      ? readiness.checks.find((check) => check.state === "warn" && check.check_key !== "capture_ready")
      : readiness.checks.find((check) => check.state === "fail" && check.check_key !== "capture_ready");
    if (primaryCheck) {
      return captureReadinessDetailText(primaryCheck);
    }
    if (readiness.is_ready) {
      return "";
    }
    const overallCheck = captureReadinessCheck(readiness, "capture_ready");
    return overallCheck ? captureReadinessDetailText(overallCheck) : "";
  }

  function idleCaptureReadinessSignature(): string {
    const clientsSignature = realtime.clients
      .map((client) => [
        client.id,
        client.connected ? "1" : "0",
        locationCodeForClient(client),
      ].join(":"))
      .sort()
      .join("|");
    return `${settings.activeCarId ?? ""}##${clientsSignature}`;
  }

  function requestIdleCaptureReadinessRefresh(): void {
    if (!handlersBound || isDemoMode || pendingLoggingAction !== null) {
      return;
    }
    if (
      realtime.loggingStatus.enabled
      || realtime.loggingStatus.analysis_in_progress
      || Boolean(realtime.loggingStatus.last_completed_run_id)
    ) {
      return;
    }
    const signature = idleCaptureReadinessSignature();
    if (idleCaptureReadinessRefreshInFlight || lastIdleCaptureReadinessSignature === signature) {
      return;
    }
    lastIdleCaptureReadinessSignature = signature;
    idleCaptureReadinessRefreshInFlight = true;
    void refreshLoggingStatus().finally(() => {
      idleCaptureReadinessRefreshInFlight = false;
    });
  }

  function renderCaptureReadinessChecklist(panelState: RecordingPanelState): void {
    if (!els.loggingChecklist) {
      return;
    }
    const { captureReadiness, showCaptureChecklist } = panelState;
    els.loggingChecklist.hidden = !showCaptureChecklist || captureReadiness === null;
    if (!showCaptureChecklist || captureReadiness === null) {
      els.loggingChecklist.innerHTML = "";
      return;
    }
    const relevantChecks = CAPTURE_READINESS_ORDER
      .filter((checkKey) => checkKey !== "capture_ready")
      .map((checkKey) => captureReadinessCheck(captureReadiness, checkKey))
      .filter((check): check is CaptureReadinessCheckPayload => (
        check !== null && (!panelState.setupMode || check.state !== "pass")
      ));
    if (!relevantChecks.length) {
      els.loggingChecklist.hidden = true;
      els.loggingChecklist.innerHTML = "";
      return;
    }
    const rows = relevantChecks.map((check) => {
      return `
        <div class="capture-readiness__item capture-readiness__item--${check.state}">
          <div class="capture-readiness__row">
            <span class="capture-readiness__label">${escapeHtml(captureReadinessCheckLabel(check.check_key))}</span>
            <span class="capture-readiness__state">${escapeHtml(captureReadinessStateText(check.state))}</span>
          </div>
          <div class="capture-readiness__detail">${escapeHtml(captureReadinessDetailText(check))}</div>
        </div>
      `;
    }).join("");
    els.loggingChecklist.innerHTML = `
      <div class="capture-readiness__title">${escapeHtml(t("dashboard.capture_readiness.title"))}</div>
      <div class="capture-readiness__list">${rows}</div>
    `;
  }

  function computeRecordingPanelState(): RecordingPanelState {
    const status = realtime.loggingStatus;
    const on = Boolean(status.enabled);
    const captureReadiness = status.capture_readiness ?? null;
    const recordingReady = Boolean(captureReadiness?.is_ready);
    const hasActiveCar = hasActiveCarSelection();
    const connectedCount = formatInt(connectedClients().length);
    const assignedCount = formatInt(assignedClientCount());
    const liveHealth = computeCurrentLiveHealth();
    const runIdText = recordingRunIdText(status);
    const elapsedText = on ? formatElapsed(status.start_time_utc) : "--";
    const samplesText = formatInt(status.samples_written ?? 0);
    const readinessSummary = captureReadinessSummaryText(captureReadiness);

    if (on) {
      lastCompletedElapsedText = elapsedText;
    } else if (!status.analysis_in_progress && !status.last_completed_run_id) {
      lastCompletedElapsedText = "--";
    }

    if (pendingLoggingAction === "starting") {
      return {
        pillVariant: "muted",
        pillText: t("dashboard.recording_phase.starting"),
        phaseText: t("dashboard.recording_phase.starting"),
        summaryText: t("dashboard.logging.starting"),
        summaryPanel: null,
        runIdText,
        elapsedText: "--",
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: true,
        stopDisabled: true,
        showPill: true,
        captureReadiness: null,
        showCaptureChecklist: false,
        setupMode: false,
      };
    }

    if (pendingLoggingAction === "stopping") {
      return {
        pillVariant: "warn",
        pillText: t("dashboard.recording_phase.stopping"),
        phaseText: t("dashboard.recording_phase.stopping"),
        summaryText: t("dashboard.logging.stopping"),
        summaryPanel: null,
        runIdText,
        elapsedText,
        samplesText,
        showStart: false,
        showStop: true,
        startDisabled: true,
        stopDisabled: true,
        showPill: true,
        captureReadiness: null,
        showCaptureChecklist: false,
        setupMode: false,
      };
    }

    if (on) {
      return {
        pillVariant: status.write_error ? "bad" : "ok",
        pillText: status.write_error || t("dashboard.recording_phase.recording"),
        phaseText: status.write_error ? t("dashboard.health.attention") : t("dashboard.recording_phase.recording"),
        summaryText: liveHealth.variant === "ok"
          ? t("dashboard.logging.running", { connected: connectedCount, assigned: assignedCount })
          : liveHealth.summary,
        summaryPanel: null,
        runIdText,
        elapsedText,
        samplesText,
        showStart: false,
        showStop: true,
        startDisabled: true,
        stopDisabled: false,
        showPill: Boolean(status.write_error),
        captureReadiness: null,
        showCaptureChecklist: false,
        setupMode: false,
      };
    }

    if (status.analysis_in_progress) {
      const runId = status.last_completed_run_id ?? t("status.unavailable");
      return {
        pillVariant: "warn",
        pillText: t("dashboard.recording_phase.processing"),
        phaseText: t("dashboard.recording_phase.processing"),
        summaryText: "",
        summaryPanel: postRunSummaryPanel("processing", runId),
        runIdText,
        elapsedText: lastCompletedElapsedText,
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: !recordingReady,
        stopDisabled: true,
        showPill: false,
        captureReadiness: null,
        showCaptureChecklist: false,
        setupMode: false,
      };
    }

    if (status.last_completed_run_id) {
      return {
        pillVariant: "ok",
        pillText: t("dashboard.recording_phase.saved"),
        phaseText: t("dashboard.recording_phase.saved"),
        summaryText: "",
        summaryPanel: postRunSummaryPanel("saved", status.last_completed_run_id),
        runIdText,
        elapsedText: lastCompletedElapsedText,
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: !recordingReady,
        stopDisabled: true,
        showPill: false,
        captureReadiness: null,
        showCaptureChecklist: false,
        setupMode: false,
      };
    }

    if (!hasActiveCar) {
      return {
        pillVariant: "warn",
        pillText: t("dashboard.recording_phase.blocked"),
        phaseText: t("dashboard.recording_phase.blocked"),
        summaryText: readinessSummary,
        summaryPanel: blockedRecordingPanel(),
        runIdText,
        elapsedText: "--",
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: true,
        stopDisabled: true,
        showPill: false,
        captureReadiness,
        showCaptureChecklist: captureReadiness !== null,
        setupMode: true,
      };
    }

    const waitingOnReadiness = captureReadiness !== null && !captureReadiness.is_ready;
    return {
      pillVariant: waitingOnReadiness ? "muted" : "ok",
      pillText: waitingOnReadiness
        ? t("dashboard.recording_phase.preparing")
        : t("dashboard.recording_phase.ready"),
      phaseText: waitingOnReadiness
        ? t("dashboard.recording_phase.preparing")
        : t("dashboard.recording_phase.ready"),
      summaryText: waitingOnReadiness ? "" : readinessSummary || liveHealth.summary,
      summaryPanel: waitingOnReadiness ? setupRecordingPanel(captureReadiness) : null,
      runIdText,
      elapsedText: "--",
      samplesText,
      showStart: true,
      showStop: false,
      startDisabled: !recordingReady,
      stopDisabled: true,
      showPill: false,
      captureReadiness,
      showCaptureChecklist: captureReadiness !== null,
      setupMode: waitingOnReadiness,
    };
  }

  function renderLoggingStatus(): void {
    const panelState = computeRecordingPanelState();
    const dashboardGrid = els.loggingSummary?.closest<HTMLElement>(".dashboard-grid");
    dashboardGrid?.classList.toggle("dashboard-grid--setup", panelState.setupMode);
    renderLiveOverviewStats();
    setDashboardPillState(els.loggingStatus, panelState.pillVariant, panelState.pillText, {
      hidden: !panelState.showPill,
    });
    ctx.setStatValue(els.loggingPhase, panelState.phaseText);
    ctx.setStatValue(els.loggingElapsed, panelState.elapsedText);
    ctx.setStatValue(els.loggingSamples, panelState.samplesText);
    if (els.loggingPhase) {
      els.loggingPhase.hidden = true;
    }
    renderLoggingSummaryContent(panelState.summaryText, panelState.summaryPanel);
    renderCaptureReadinessChecklist(panelState);
    if (els.loggingRunId) {
      els.loggingRunId.hidden = panelState.runIdText === "";
      els.loggingRunId.textContent = panelState.runIdText;
    }
    const loggingRow = els.loggingStatus?.parentElement;
    if (loggingRow) {
      loggingRow.hidden = !panelState.showPill && panelState.runIdText === "";
    }
    if (els.startLoggingBtn) {
      els.startLoggingBtn.hidden = !panelState.showStart;
      els.startLoggingBtn.disabled = panelState.startDisabled;
    }
    if (els.stopLoggingBtn) {
      els.stopLoggingBtn.hidden = !panelState.showStop;
      els.stopLoggingBtn.disabled = panelState.stopDisabled;
    }
    syncLoggingElapsedTimer();
    renderLiveHealth();
    requestIdleCaptureReadinessRefresh();
  }

  async function refreshLoggingStatus(): Promise<void> {
    if (isDemoMode && pendingLoggingAction === null) {
      renderLoggingStatus();
      return;
    }
    try {
      realtime.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      pendingLoggingAction = null;
      clearLoggingElapsedTimer();
      setDashboardPillState(els.loggingStatus, "bad", t("status.unavailable"));
      renderLoggingSummaryContent(t("status.unavailable"), null);
      if (els.loggingChecklist) {
        els.loggingChecklist.hidden = true;
        els.loggingChecklist.innerHTML = "";
      }
      if (els.loggingRunId) {
        els.loggingRunId.hidden = true;
        els.loggingRunId.textContent = "";
      }
      ctx.setStatValue(els.loggingPhase, t("status.unavailable"));
      ctx.setStatValue(els.loggingElapsed, "--");
      ctx.setStatValue(els.loggingSamples, "--");
      if (els.loggingPhase) {
        els.loggingPhase.hidden = true;
      }
      const loggingRow = els.loggingStatus?.parentElement;
      if (loggingRow) {
        loggingRow.hidden = false;
      }
      if (els.startLoggingBtn) {
        els.startLoggingBtn.hidden = false;
        els.startLoggingBtn.disabled = true;
      }
      if (els.stopLoggingBtn) {
        els.stopLoggingBtn.hidden = true;
        els.stopLoggingBtn.disabled = true;
      }
      const dashboardGrid = els.loggingSummary?.closest<HTMLElement>(".dashboard-grid");
      dashboardGrid?.classList.remove("dashboard-grid--setup");
    }
  }

  async function startLogging(): Promise<void> {
    if (pendingLoggingAction) return;
    pendingLoggingAction = "starting";
    renderLoggingStatus();
    try {
      realtime.loggingStatus = await startLoggingRun();
      await ctx.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      pendingLoggingAction = null;
      setDashboardPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
      renderLoggingSummaryContent(msg || t("status.unavailable"), null);
      return;
    }
    pendingLoggingAction = null;
    renderLoggingStatus();
  }

  async function stopLogging(): Promise<void> {
    if (pendingLoggingAction) return;
    pendingLoggingAction = "stopping";
    renderLoggingStatus();
    try {
      realtime.loggingStatus = await stopLoggingRun();
      await ctx.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      pendingLoggingAction = null;
      setDashboardPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
      renderLoggingSummaryContent(msg || t("status.unavailable"), null);
      return;
    }
    pendingLoggingAction = null;
    renderLoggingStatus();
  }

  const loggingStatusPolling = createPollingController({
    poll: async () => {
      await refreshLoggingStatus();
      return realtime.loggingStatus.enabled || realtime.loggingStatus.analysis_in_progress
        ? LOGGING_STATUS_ACTIVE_POLL_MS
        : LOGGING_STATUS_IDLE_POLL_MS;
    },
    onErrorDelayMs: LOGGING_STATUS_ERROR_POLL_MS,
  });

  async function refreshLocationOptions(): Promise<void> {
    try {
      const payload = await getClientLocations();
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row) => row.code).filter((code): code is string => typeof code === "string")
        : [];
      applyLocationCodes(codes);
    } catch (_err) {
      applyLocationCodes([]);
    }
    maybeRenderSensorsSettingsList(true);
    renderStatus();
    renderLoggingStatus();
  }

  async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
    if (!clientId) return;
    const existing = realtime.clients.find((c) => c.id === clientId);
    const existingLocationCode = String(existing?.location_code || "").trim();
    if (existing && existingLocationCode === locationCode) return;
    try {
      await setClientLocationApi(clientId, locationCode);
    } catch (err) {
      ctx.showError(err instanceof Error ? err.message : t("actions.set_location_failed"));
      return;
    }
    const client = realtime.clients.find((c) => c.id === clientId);
    if (client) {
      client.location_code = locationCode;
      maybeRenderSensorsSettingsList();
      renderStatus();
      await refreshLoggingStatus();
    }
  }

  async function identifyClient(clientId: string): Promise<void> {
    if (!clientId) return;
    await identifyClientApi(clientId); // uses API default of 1500 ms
  }

  async function removeClient(clientId: string): Promise<void> {
    if (!clientId) return;
    const ok = window.confirm(t("actions.remove_client_confirm", { id: clientId }));
    if (!ok) return;
    try {
      await removeClientApi(clientId);
    } catch (err) {
      ctx.showError(err instanceof Error ? err.message : t("actions.remove_client_failed"));
      return;
    }
    const prevSelected = realtime.selectedClientId;
    realtime.clients = realtime.clients.filter((c) => c.id !== clientId);
    if (realtime.selectedClientId === clientId) realtime.selectedClientId = null;
    updateClientSelection();
    maybeRenderSensorsSettingsList();
    renderLoggingStatus();
    renderStatus();
    if (prevSelected !== realtime.selectedClientId) ctx.sendSelection();
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    if (!isDemoMode) {
      loggingStatusPolling.start();
    }
    syncLoggingElapsedTimer();
    els.startLoggingBtn?.addEventListener("click", () => void startLogging());
    els.stopLoggingBtn?.addEventListener("click", () => void stopLogging());
    els.loggingSummary?.addEventListener("click", (event) => {
      const action = getInlineStateAction(event.target);
      if (!action) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      if (action === "open-history") {
        activatePrimaryView("historyView");
        return;
      }
      if (action === "open-add-car") {
        openCarsView({ openWizard: true });
        return;
      }
      if (action === "open-cars") {
        openCarsView();
        return;
      }
      if (action === "open-sensors") {
        openSettingsView("sensorsTab");
        return;
      }
      if (action === "open-speed-source") {
        openSettingsView("speedSourceTab");
      }
    });
    els.sensorsSettingsBody?.addEventListener("change", (event) => {
      const change = getRealtimeSensorTableLocationChange(event.target);
      if (!change) {
        return;
      }
      void setClientLocation(change.clientId, change.locationCode);
    });
    els.sensorsSettingsBody?.addEventListener("click", (event) => {
      const action = getRealtimeSensorTableClickAction(event.target);
      if (!action) {
        return;
      }
      if (action.type === "identify") {
        void identifyClient(action.clientId);
        return;
      }
      void removeClient(action.clientId);
    });
  }

  return {
    bindHandlers,
    buildLocationOptions,
    maybeRenderSensorsSettingsList,
    updateClientSelection,
    locationCodeForClient,
    renderStatus,
    renderLoggingStatus,
    refreshLoggingStatus,
    startLogging,
    stopLogging,
    refreshLocationOptions,
  };
}
