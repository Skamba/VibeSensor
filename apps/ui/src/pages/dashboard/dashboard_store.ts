import { batch, computed, effect, signal } from "@preact/signals";

import {
  getLoggingStatus,
  markGuidedPhase,
  startLoggingRun,
  stopLoggingRun,
} from "../../api/logging";
import type { GuidedPhase, LoggingStatusPayload } from "../../api/types";
import { errorMessage, isDemoMode, navigate, speedUnit } from "../../app_store";
import { fmt, formatIntLocale } from "../../format";
import { lang, t } from "../../i18n";
import {
  clients,
  locationChoices,
  locationOf,
  rotationalSpeeds,
  runsChanged,
  spectra,
  speedMps,
} from "../../live_store";
import { poll } from "../../poll";
import {
  carSelection,
  carSettings,
  speedSourceSnapshot,
} from "../../settings_store";
import { deriveSpeedReadoutLabelKey } from "../../speed_source";
import {
  activeCarText,
  formatElapsed,
  freshnessText,
  guidedTestModel,
  IDLE_STATUS,
  isIdle,
  liveHealth,
  type LoggingError,
  type PendingAction,
  recordingModel,
  runsAffected,
  sensorLabel,
  speedText,
  strongestSensor,
  type SummaryAction,
  withLoggingError,
} from "./dashboard_model";

const STATUS_POLL_MS = 2_000;

const status = signal<LoggingStatusPayload>(IDLE_STATUS);
const pending = signal<PendingAction>(null);
const loggingError = signal<LoggingError | null>(null);
const nowMs = signal(Date.now());
/** Elapsed time of the current run, kept once it stops until the next idle. */
const lastRunElapsed = signal("--");
const guidedBusy = signal(false);

const formatInt = (value: number) => formatIntLocale(value, lang.value);

function applyStatus(next: LoggingStatusPayload): void {
  const previous = status.peek();
  status.value = next;
  if (runsAffected(previous, next)) {
    runsChanged.value += 1;
  }
}

/** Sensors, their locations, and the active car: readiness depends on these. */
const readinessInputs = computed(() => {
  const sensors = clients.value
    .map((client) =>
      [client.id, client.connected ? "1" : "0", locationOf(client)].join(":"),
    )
    .sort()
    .join("|");
  return `${carSettings.activeCarId.value ?? ""}##${sensors}`;
});
let checkedReadinessInputs: string | null = null;

const statusPoll = poll({
  active: signal(!isDemoMode()),
  intervalMs: STATUS_POLL_MS,
  load: () => {
    checkedReadinessInputs = readinessInputs.peek();
    return getLoggingStatus();
  },
  onData: (next) => {
    batch(() => {
      applyStatus(next);
      loggingError.value = null;
    });
  },
  onError: () => {
    batch(() => {
      pending.value = null;
      loggingError.value = {
        kind: "unavailable",
        message: t("status.unavailable"),
      };
    });
  },
});

// While idle, re-check readiness as soon as sensors or the car change rather
// than waiting for the next poll.
effect(() => {
  const inputs = readinessInputs.value;
  const idle = isIdle(status.value) && pending.value === null;
  if (!isDemoMode() && idle && inputs !== checkedReadinessInputs) {
    void statusPoll.refresh();
  }
});

const runningSince = computed(() =>
  status.value.enabled ? (status.value.start_time_utc ?? null) : null,
);
effect(() => {
  if (!runningSince.value) {
    return;
  }
  nowMs.value = Date.now();
  const timer = setInterval(() => {
    nowMs.value = Date.now();
  }, 1_000);
  return () => clearInterval(timer);
});
effect(() => {
  const current = status.value;
  if (current.enabled) {
    lastRunElapsed.value = formatElapsed(current.start_time_utc, nowMs.value);
  } else if (isIdle(current)) {
    lastRunElapsed.value = "--";
  }
});

async function runAction(
  action: Exclude<PendingAction, null>,
  request: () => Promise<LoggingStatusPayload>,
): Promise<void> {
  if (pending.peek()) {
    return;
  }
  checkedReadinessInputs = readinessInputs.peek();
  batch(() => {
    pending.value = action;
    loggingError.value = null;
  });
  try {
    const next = await request();
    batch(() => {
      applyStatus(next);
      pending.value = null;
    });
    // Drops any status poll that was already in flight with the old state.
    void statusPoll.refresh();
  } catch (error) {
    batch(() => {
      pending.value = null;
      loggingError.value = {
        kind: "error",
        message: errorMessage(error, t("status.unavailable")),
      };
    });
  }
}

export function startRecording(): Promise<void> {
  return runAction("starting", startLoggingRun);
}

export function stopRecording(): Promise<void> {
  return runAction("stopping", stopLoggingRun);
}

/** Starts the next guided test-drive step, or ends the guided test with `null`. */
export async function advanceGuidedTest(
  phase: GuidedPhase | null,
): Promise<void> {
  if (guidedBusy.peek()) {
    return;
  }
  guidedBusy.value = true;
  try {
    const next = await markGuidedPhase(phase);
    batch(() => {
      applyStatus(next);
      loggingError.value = null;
    });
  } catch (error) {
    loggingError.value = {
      kind: "error",
      message: errorMessage(error, t("status.unavailable")),
    };
  } finally {
    guidedBusy.value = false;
  }
}

/** Summary-panel actions except adding a car, which the shell handles. */
export function openSummaryTarget(
  action: Exclude<SummaryAction, "open-add-car">,
): void {
  if (action === "open-history") {
    navigate("historyView");
  } else if (action === "open-cars") {
    navigate("settingsView", "carTab");
  } else if (action === "open-sensors") {
    navigate("settingsView", "sensorsTab");
  } else {
    navigate("settingsView", "speedSourceTab");
  }
}

// --- View models -------------------------------------------------------------

/** Run health, also shown in the header outside the dashboard. */
export const health = computed(() =>
  liveHealth(
    {
      clients: clients.value,
      locationOf,
      status: status.value,
      carActive: carSelection.value.kind === "active",
      speedUnit: speedUnit.value,
    },
    t,
    formatInt,
  ),
);

const baseRecording = computed(() => {
  const current = status.value;
  const selection = carSelection.value.kind;
  return recordingModel(
    {
      status: current,
      pending: pending.value,
      carBlock:
        selection === "active"
          ? null
          : selection === "no_cars"
            ? "no_cars"
            : "no_active",
      health: health.value,
      speedUnit: speedUnit.value,
      connectedText: formatInt(
        clients.value.filter((client) => client.connected).length,
      ),
      assignedText: formatInt(
        clients.value.filter((client) => locationOf(client)).length,
      ),
      elapsedText: current.enabled
        ? formatElapsed(current.start_time_utc, nowMs.value)
        : lastRunElapsed.value,
      lastRunElapsedText: lastRunElapsed.value,
    },
    t,
    formatInt,
  );
});

export const recording = computed(() =>
  loggingError.value
    ? withLoggingError(baseRecording.value, loggingError.value, t)
    : baseRecording.value,
);

export const guidedTest = computed(() =>
  guidedTestModel(
    status.value,
    speedUnit.value,
    guidedBusy.value || pending.value !== null,
    t,
  ),
);

export const overview = computed(() => {
  const list = clients.value;
  const strongest = strongestSensor(list, spectra.value);
  const label = (client: (typeof list)[number]) =>
    sensorLabel(
      client,
      locationOf(client),
      locationChoices.value,
      t("dashboard.sensor_unassigned"),
    );
  return {
    connectedText: `${formatInt(list.filter((client) => client.connected).length)} / ${formatInt(list.length)}`,
    activeCarText: activeCarText(carSelection.value, t),
    recordingStateText: baseRecording.value.phaseText,
    freshnessText: freshnessText(
      list,
      status.value.capture_readiness ?? null,
      t,
      formatInt,
    ),
    strongestText: strongest
      ? `${label(strongest.client)} · ${formatInt(strongest.db)} dB`
      : t("dashboard.strongest_signal_none"),
    sensors: list.map((client) => ({
      id: client.id,
      label: label(client),
      connected: Boolean(client.connected),
      strongest: strongest?.client.id === client.id,
    })),
  };
});

export const speedReadout = computed(() =>
  speedText(
    speedMps.value,
    speedUnit.value,
    deriveSpeedReadoutLabelKey(
      speedSourceSnapshot.value,
      rotationalSpeeds.value?.basis_speed_source,
    ),
    t,
    fmt,
  ),
);
