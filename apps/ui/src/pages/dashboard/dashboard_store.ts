import { batch, computed, effect, signal } from "@preact/signals";

import {
  getLoggingStatus,
  markGuidedPhase,
  startLoggingRun,
  stopLoggingRun,
} from "../../api/logging";
import type { GuidedPhase, LoggingStatusPayload } from "../../api/types";
import {
  errorMessage,
  isDemoMode,
  navigate,
  requestConfirmation,
  speedUnit,
} from "../../app_store";
import { reportClock } from "../../clock_report";
import { fmt, formatIntLocale, formatSpeed } from "../../format";
import { lang, t } from "../../i18n";
import { keepAwakeMode, startKeepAwake, stopKeepAwake } from "../../keep_awake";
import {
  clients,
  liveSensorLayout,
  locationOf,
  rotationalSpeeds,
  runsChanged,
  spectra,
  speedMps,
} from "../../live_store";
import { poll } from "../../poll";
import { layoutConsequence } from "../../sensor_layout";
import { sensorLabel } from "../../sensor_locations";
import {
  activeCar,
  carSelection,
  carSettings,
  speedSettings,
  speedSourceSnapshot,
  speedStatus,
} from "../../settings_store";
import {
  deriveSpeedReadoutLabelKey,
  fallbackReasonKey,
  gpsFixWaitS,
  gpsReceiverMissing,
} from "../../speed_source";
import {
  actionBarModel,
  activeCarText,
  driveAlerts,
  formatElapsed,
  freshnessText,
  guidedTestModel,
  IDLE_STATUS,
  isIdle,
  liveHealth,
  liveSpeedHint,
  type LoggingError,
  type PendingAction,
  recordingModel,
  runsAffected,
  setupModel,
  speedText,
  stopConfirmation,
  strongestSensor,
  type SummaryAction,
  withLoggingError,
} from "./dashboard_model";
import { capabilityModel } from "./readiness";

const STATUS_POLL_MS = 2_000;

const status = signal<LoggingStatusPayload>(IDLE_STATUS);
const pending = signal<PendingAction>(null);
const loggingError = signal<LoggingError | null>(null);
const nowMs = signal(Date.now());
/** When `status` arrived, by the browser clock: its `elapsed_s` was true then. */
const statusReceivedAtMs = signal(Date.now());
/** Elapsed time of the current run, kept once it stops until the next idle. */
const lastRunElapsed = signal("--");
const guidedBusy = signal(false);

const formatInt = (value: number) => formatIntLocale(value, lang.value);

function applyStatus(next: LoggingStatusPayload): void {
  const previous = status.peek();
  status.value = next;
  statusReceivedAtMs.value = Date.now();
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

const runningRunId = computed(() =>
  status.value.enabled ? status.value.run_id : null,
);
effect(() => {
  if (!runningRunId.value) {
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
    lastRunElapsed.value = formatElapsed(
      current.elapsed_s,
      statusReceivedAtMs.value,
      nowMs.value,
    );
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

/**
 * Starts a run. The browser clock goes first, so a Pi clock that no browser
 * has set yet (it has no RTC) is set before the run is stamped.
 */
export function startRecording(): Promise<void> {
  // Inside the tap: iOS only starts the keep-awake video from a user gesture.
  startKeepAwake();
  return runAction("starting", async () => {
    await reportClock();
    return await startLoggingRun();
  });
}

/**
 * Stops the run, then reports the browser clock: the server never steps the
 * clock under a recording, so a run the browser first saw mid-recording gets
 * its true time once it has stopped.
 */
function stopRecording(): Promise<void> {
  return runAction("stopping", async () => {
    const stopped = await stopLoggingRun();
    void reportClock();
    return stopped;
  });
}

/**
 * The Stop button: asks first while a guided step is in progress, so a tap
 * meant for Next does not end the run.
 */
export async function confirmAndStopRecording(): Promise<void> {
  const message = stopConfirmation(guidedTest.peek(), t);
  if (message !== null && !(await requestConfirmation(message))) {
    return;
  }
  await stopRecording();
}

// Keep the screen on for the whole run however it started (also after a
// reload mid-run), and let it lock again once the run stops for any reason.
const keepScreenOn = computed(
  () => status.value.enabled || pending.value === "starting",
);
effect(() => {
  if (keepScreenOn.value) {
    startKeepAwake();
  } else {
    stopKeepAwake();
  }
});

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

const gpsHints = computed(() => ({
  gpsReceiverMissing: gpsReceiverMissing(
    speedSettings.source.value,
    speedStatus.value,
  ),
  gpsFixWaitS: gpsFixWaitS(speedSettings.source.value, speedStatus.value),
}));

const connectedCount = computed(
  () => clients.value.filter((client) => client.connected).length,
);

/** The speed source when it gives a speed: "GPS", "OBD-II" or the typed-in speed. */
const speedDoneText = computed(() => {
  const source = speedSettings.source.value;
  return t(`dashboard.setup.speed.${source}`, {
    speed: formatSpeed(
      speedSettings.manualSpeedKph.value,
      speedUnit.value,
      t,
      0,
    ),
  });
});

/** Car, speed source and sensors still to set up; not shown while a run records. */
export const setup = computed(() => {
  const current = status.value;
  if (current.enabled || pending.value !== null) {
    return null;
  }
  const model = setupModel(
    {
      carSelection: carSelection.value,
      readiness: current.capture_readiness ?? null,
      connected: connectedCount.value,
      speedDoneText: speedDoneText.value,
      speedHint: liveSpeedHint(gpsHints.value, t, formatInt),
      speedUnit: speedUnit.value,
    },
    t,
    formatInt,
  );
  return model?.next ? model : null;
});

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
      setupIncomplete: setup.value !== null,
      health: health.value,
      speedUnit: speedUnit.value,
      ...gpsHints.value,
      connectedText: formatInt(connectedCount.value),
      assignedText: formatInt(
        clients.value.filter((client) => locationOf(client)).length,
      ),
      elapsedText: current.enabled
        ? formatElapsed(
            current.elapsed_s,
            statusReceivedAtMs.value,
            nowMs.value,
          )
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

/** The one next action on Live: a setup step, Start, Stop, or the run just recorded. */
export const actionBar = computed(() =>
  actionBarModel(
    {
      status: status.value,
      pending: pending.value,
      recording: recording.value,
      setup: setup.value,
      error: loggingError.value,
    },
    t,
  ),
);

/** Live data to show: a sensor is connected, or a run records. */
export const hasLiveSignal = computed(
  () => connectedCount.value > 0 || status.value.enabled,
);

/** What the next run can test, and what the sensor layout can localise; idle only. */
export const capabilities = computed(() => {
  const current = status.value;
  if (current.enabled) {
    return null;
  }
  const model = capabilityModel(
    current.capture_readiness?.capabilities ?? null,
    activeCar.value?.fuel_type ?? null,
    formatSpeed(speedSettings.manualSpeedKph.value, speedUnit.value, t, 0),
    fallbackReason.value,
    t,
  );
  if (!model) {
    return null;
  }
  const layout = liveSensorLayout.value;
  return {
    ...model,
    layoutNote: layout
      ? layoutConsequence(layout, activeCar.value?.fuel_type ?? null, t)
      : null,
  };
});

/** Sensor-silent warning, why the last run stopped, and the auto-lock hint. */
export const alerts = computed(() =>
  driveAlerts(
    { status: status.value, keepAwake: keepAwakeMode.value },
    t,
    formatInt,
  ),
);

export const guidedTest = computed(() =>
  guidedTestModel(
    status.value,
    speedUnit.value,
    guidedBusy.value || pending.value !== null,
    activeCar.value?.fuel_type ?? null,
    t,
    speedSourceSnapshot.value.speedSource === "manual",
  ),
);

export const overview = computed(() => {
  const list = clients.value;
  const strongest = strongestSensor(list, spectra.value);
  const label = (client: (typeof list)[number]) =>
    sensorLabel(client, locationOf(client), t);
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

/** Why the typed-in fallback speed is in use (translated), or null. */
const fallbackReason = computed(() => {
  const key = fallbackReasonKey(
    speedSourceSnapshot.value,
    speedStatus.value,
    rotationalSpeeds.value?.basis_speed_source,
  );
  return key ? t(key) : null;
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
    fallbackReason.value,
  ),
);
