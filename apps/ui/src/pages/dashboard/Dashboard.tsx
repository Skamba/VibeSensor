import type { ComponentChildren } from "preact";

import { t } from "../../i18n";
import type { RecordingModel, SummaryAction } from "./dashboard_model";
import {
  health,
  openSummaryTarget,
  overview,
  recording,
  speedReadout,
  startRecording,
  stopRecording,
} from "./dashboard_store";

function Stat(props: {
  id?: string;
  labelKey: string;
  children: ComponentChildren;
}) {
  return (
    <div id={props.id} class="stat">
      <div class="stat__label">{t(props.labelKey)}</div>
      <div class="stat__value" data-value>
        {props.children}
      </div>
    </div>
  );
}

function Overview() {
  const model = overview.value;
  const runHealth = health.value;
  return (
    <>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">{t("dashboard.live_overview")}</div>
          <div class="card__subtle">{t("dashboard.live_overview_hint")}</div>
        </div>
        <div
          id="liveRunHealth"
          class="pill"
          data-variant={runHealth.variant}
          hidden={!runHealth.showOverviewPill}
          aria-live="polite"
        >
          {runHealth.text}
        </div>
      </div>
      <div class="stat-grid live-overview__stats">
        <Stat id="liveConnectedSensors" labelKey="dashboard.connected_sensors">
          {model.connectedText}
        </Stat>
        <Stat id="liveActiveCar" labelKey="dashboard.active_car">
          {model.activeCarText}
        </Stat>
        <Stat id="liveRecordingState" labelKey="dashboard.recording_state">
          {model.recordingStateText}
        </Stat>
        <Stat id="liveDataFreshness" labelKey="dashboard.data_freshness">
          {model.freshnessText}
        </Stat>
        <Stat id="liveStrongestSignal" labelKey="dashboard.strongest_signal">
          {model.strongestText}
        </Stat>
        <div class="stat">
          <div class="stat__label">{t("dashboard.current_speed")}</div>
          <div id="speed" class="stat__value speed" aria-live="polite">
            {speedReadout.value}
          </div>
        </div>
      </div>
      <div class="live-sensor-roster__header">
        <div class="mini-label">{t("dashboard.sensor_coverage")}</div>
      </div>
      <div id="liveSensorRoster" class="live-sensor-roster">
        {model.sensors.length > 0 ? (
          model.sensors.map((sensor) => {
            const statusText = t(
              sensor.connected ? "status.online" : "status.offline",
            );
            return (
              <article
                key={sensor.id}
                class="live-sensor-card"
                data-strongest={sensor.strongest ? "true" : undefined}
              >
                <div class="live-sensor-card__header">
                  <strong>{sensor.label}</strong>
                  <span
                    class="live-sensor-card__status-dot"
                    data-status={sensor.connected ? "online" : "offline"}
                    role="img"
                    aria-label={statusText}
                    title={statusText}
                  />
                </div>
              </article>
            );
          })
        ) : (
          <div class="subtle">{t("settings.sensors.no_sensors")}</div>
        )}
      </div>
    </>
  );
}

function Summary(props: {
  model: RecordingModel;
  onAction: (action: SummaryAction) => void;
}) {
  const { summaryPanel: panel, summaryText } = props.model;
  return (
    <div
      id="loggingSummary"
      class="card__subtle"
      hidden={summaryText === "" && panel === null}
      data-summary-layout={panel ? "panel" : undefined}
    >
      {panel ? (
        <div
          class={`empty-state empty-state--inline${panel.action ? " empty-state--actionable" : ""}`}
        >
          <strong class="empty-state__title">{panel.title}</strong>
          <span class="empty-state__body">{panel.body}</span>
          {panel.detail ? (
            <span class="empty-state__detail">{panel.detail}</span>
          ) : null}
          {panel.action ? (
            <div class="empty-state__actions">
              <button
                type="button"
                class={`btn btn--${panel.action.variant}`}
                data-inline-state-action={panel.action.action}
                onClick={() =>
                  panel.action && props.onAction(panel.action.action)
                }
              >
                {panel.action.label}
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        summaryText
      )}
    </div>
  );
}

function Progress(props: { model: RecordingModel }) {
  const { model } = props;
  if (model.setupMode && model.checklist === null) {
    return null;
  }
  return (
    <>
      <div class="mini-label">{t("dashboard.recording_progress")}</div>
      <div class="stat-grid stat-grid--compact">
        <div id="loggingPhase" class="stat stat--compact" hidden>
          <div class="stat__label">{t("dashboard.recording_phase")}</div>
          <div class="stat__value" data-value>
            {model.phaseText}
          </div>
        </div>
        <div id="loggingElapsed" class="stat stat--compact">
          <div class="stat__label">{t("dashboard.recording_elapsed")}</div>
          <div class="stat__value" data-value>
            {model.elapsedText}
          </div>
        </div>
        <div id="loggingSamples" class="stat stat--compact">
          <div class="stat__label">{t("dashboard.recording_samples")}</div>
          <div class="stat__value" data-value>
            {model.samplesText}
          </div>
        </div>
      </div>
      <div
        id="loggingChecklist"
        class="capture-readiness"
        hidden={model.checklist === null}
      >
        {model.checklist ? (
          <>
            <div class="capture-readiness__title">
              {t("dashboard.capture_readiness.title")}
            </div>
            <div class="capture-readiness__list">
              {model.checklist.map((item) => (
                <div
                  key={item.checkKey}
                  class="capture-readiness__item"
                  data-readiness-state={item.state}
                >
                  <div class="capture-readiness__row">
                    <span class="capture-readiness__label">{item.label}</span>
                    <span class="capture-readiness__state">
                      {item.stateText}
                    </span>
                  </div>
                  <div class="capture-readiness__detail">{item.detail}</div>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

function Recording(props: { onAddCar: () => void }) {
  const model = recording.value;
  const onAction = (action: SummaryAction) => {
    if (action === "open-add-car") {
      props.onAddCar();
    } else {
      openSummaryTarget(action);
    }
  };
  return (
    <div
      class="realtime-logging-shell"
      data-layout={model.setupMode ? "setup" : undefined}
    >
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">{t("dashboard.run_recording")}</div>
          <Summary model={model} onAction={onAction} />
        </div>
      </div>
      <div
        class="logging-row"
        hidden={!model.showPill && model.runIdText === ""}
      >
        <span
          id="loggingStatus"
          class="pill"
          data-variant={model.pillVariant}
          hidden={!model.showPill}
          aria-live="polite"
        >
          {model.pillText}
        </span>
        <span id="loggingRunId" class="subtle" hidden={model.runIdText === ""}>
          {model.runIdText}
        </span>
      </div>
      <Progress model={model} />
      <div class="logging-actions">
        <button
          id="startLoggingBtn"
          class="btn btn--primary"
          type="button"
          hidden={model.showStop}
          disabled={model.startDisabled}
          onClick={() => void startRecording()}
        >
          {t("dashboard.start_recording")}
        </button>
        <button
          id="stopLoggingBtn"
          class="btn btn--danger-quiet"
          type="button"
          hidden={!model.showStop}
          disabled={model.stopDisabled}
          onClick={() => void stopRecording()}
        >
          {t("dashboard.stop_recording")}
        </button>
      </div>
    </div>
  );
}

/** The Live view: overview, spectrum (passed in by the shell), and recording. */
export function Dashboard(props: {
  spectrum: ComponentChildren;
  onAddCar: () => void;
}) {
  return (
    <div class="dashboard-grid">
      <div class="panel card dashboard-grid__overview">
        <Overview />
      </div>
      <div class="panel card dashboard-grid__main">{props.spectrum}</div>
      <div class="panel card dashboard-grid__controls">
        <Recording onAddCar={props.onAddCar} />
      </div>
    </div>
  );
}
