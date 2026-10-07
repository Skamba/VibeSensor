import type { ComponentChildren } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";

import { CAPABILITY_MARK_SYMBOL } from "../../capabilities";
import { FeedbackBlock } from "../../components/feedback";
import { t } from "../../i18n";
import type {
  ActionBarButton,
  GuidedStep,
  RecordingModel,
  SummaryAction,
} from "./dashboard_model";
import {
  actionBar,
  advanceGuidedTest,
  alerts,
  capabilities,
  confirmAndStopRecording,
  guidedTest,
  hasLiveSignal,
  openSummaryTarget,
  overview,
  recording,
  setup,
  speedReadout,
  startRecording,
} from "./dashboard_store";

function Stat(props: {
  id?: string;
  labelKey: string;
  /** A long value (a car name, a location and level): the full row on a phone. */
  wide?: boolean;
  children: ComponentChildren;
}) {
  return (
    <div id={props.id} class={props.wide ? "stat stat--wide" : "stat"}>
      <div class="stat__label">{t(props.labelKey)}</div>
      <div class="stat__value" data-value>
        {props.children}
      </div>
    </div>
  );
}

function Overview() {
  const model = overview.value;
  return (
    <>
      <div class="card__header">
        <div>
          <div class="card__title">{t("dashboard.live_overview")}</div>
          <div class="card__subtle">{t("dashboard.live_overview_hint")}</div>
        </div>
      </div>
      <div class="stat-grid live-overview__stats">
        <Stat id="liveConnectedSensors" labelKey="dashboard.connected_sensors">
          {model.connectedText}
        </Stat>
        <Stat id="liveActiveCar" labelKey="dashboard.active_car" wide>
          {model.activeCarText}
        </Stat>
        <Stat id="liveRecordingState" labelKey="dashboard.recording_state">
          {model.recordingStateText}
        </Stat>
        <Stat id="liveDataFreshness" labelKey="dashboard.data_freshness">
          {model.freshnessText}
        </Stat>
        <Stat
          id="liveStrongestSignal"
          labelKey="dashboard.strongest_signal"
          wide
        >
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

function CapabilityLine() {
  const model = capabilities.value;
  if (!model) {
    return null;
  }
  return (
    <section id="captureCapabilities" class="capture-capabilities">
      <div class="capture-readiness__title">
        {t("dashboard.capabilities.title")}
      </div>
      <ul class="capture-capabilities__list">
        {model.items.map((item) => (
          <li
            key={item.family}
            class="capture-capabilities__item"
            data-capability={item.family}
            data-capability-mark={item.mark}
          >
            <span class="capture-capabilities__mark" aria-hidden="true">
              {CAPABILITY_MARK_SYMBOL[item.mark]}
            </span>
            <span class="capture-capabilities__label">{item.label}</span>
            {item.note ? (
              <span class="capture-capabilities__note">{item.note}</span>
            ) : null}
            {item.fix ? (
              <button
                type="button"
                class="btn capture-capabilities__fix"
                onClick={() =>
                  openSummaryTarget(
                    item.fix?.target === "cars"
                      ? "open-cars"
                      : "open-speed-source",
                  )
                }
              >
                {item.fix.label}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {model.manualNote ? (
        <p id="captureManualSpeedNote" class="capture-capabilities__caveat">
          {model.manualNote}{" "}
          <button
            type="button"
            class="btn capture-capabilities__fix"
            onClick={() => openSummaryTarget("open-speed-source")}
          >
            {t("dashboard.capabilities.fix.manual_speed")}
          </button>
        </p>
      ) : null}
      {model.layoutNote ? (
        <p id="captureLayoutNote" class="capture-capabilities__layout">
          {model.layoutNote}
        </p>
      ) : null}
    </section>
  );
}

function GuidedSteps(props: { steps: GuidedStep[]; preview: boolean }) {
  return (
    <ol class="guided-test__steps">
      {props.steps.map((step) => (
        <li
          key={step.phase}
          class="guided-test__step"
          data-guided-step={step.phase}
          data-step-state={step.state}
          aria-current={step.state === "current" ? "step" : undefined}
        >
          <div class="guided-test__step-label">{step.label}</div>
          <strong>{step.title}</strong>
          {props.preview || step.state === "current" ? (
            <div class="guided-test__instruction">{step.instruction}</div>
          ) : null}
          {step.progress ? (
            <div class="guided-test__progress" data-guided-progress>
              {step.progress}
            </div>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** No guided step can be checked on a typed-in speed: say so, with the way out. */
function GuidedTypedInNote(props: { note: string }) {
  return (
    <p id="guidedTypedInNote" class="guided-test__typed-in">
      {props.note}{" "}
      <button
        type="button"
        class="btn capture-capabilities__fix"
        onClick={() => openSummaryTarget("open-speed-source")}
      >
        {t("dashboard.capabilities.fix.manual_speed")}
      </button>
    </p>
  );
}

/**
 * The guided test drive in the recording card: a preview of its steps while
 * parked, and the full instructions while a run records. The step in progress
 * and its Next button sit in the card at the top of Live (`GuidedStepCard`),
 * away from Stop.
 */
function GuidedTest() {
  const model = guidedTest.value;
  if (model.mode === "preview") {
    return (
      <details id="guidedPreview" class="guided-test guided-test--preview">
        <summary class="guided-test__title">
          {t("dashboard.guided.preview.summary")}
        </summary>
        <div class="guided-test__hint">{model.hint}</div>
        {model.typedInNote ? (
          <GuidedTypedInNote note={model.typedInNote} />
        ) : (
          <div class="guided-test__hint">
            {t("dashboard.guided.preview.note")}
          </div>
        )}
        <GuidedSteps steps={model.steps} preview />
      </details>
    );
  }
  if (model.mode !== "active") {
    return null;
  }
  const action = model.action;
  return (
    <section id="guidedTest" class="guided-test" aria-live="polite">
      <div class="guided-test__title">{t("dashboard.guided.title")}</div>
      <div class="guided-test__hint">{model.hint}</div>
      {model.typedInNote ? (
        <GuidedTypedInNote note={model.typedInNote} />
      ) : null}
      <GuidedSteps steps={model.steps} preview={false} />
      {model.finished ? (
        <div class="guided-test__done">{t("dashboard.guided.done")}</div>
      ) : null}
      {action ? (
        <button
          id="guidedTestBtn"
          class="btn btn--secondary"
          type="button"
          disabled={model.disabled}
          onClick={() => void advanceGuidedTest(action.phase)}
        >
          {action.label}
        </button>
      ) : null}
    </section>
  );
}

/** The guided step in progress, short enough to read at a glance, with Next. */
function GuidedStepCard() {
  const model = guidedTest.value;
  const step = model.current;
  if (!step) {
    return null;
  }
  return (
    <section
      id="guidedStepCard"
      class="guided-step-card"
      data-guided-step={step.phase}
      aria-live="polite"
    >
      <div class="guided-step-card__label">
        {step.label} · <strong>{step.title}</strong>
      </div>
      <div class="guided-step-card__text">{step.short}</div>
      {step.progress ? (
        <div class="guided-step-card__progress" data-guided-progress>
          {step.progress}
        </div>
      ) : null}
      <button
        id="guidedNextBtn"
        class="btn btn--primary guided-step-card__next"
        type="button"
        disabled={model.disabled}
        onClick={() => void advanceGuidedTest(step.action.phase)}
      >
        {step.action.label}
      </button>
    </section>
  );
}

/**
 * The first-run checklist at the top of Live: car, speed source, sensors, each
 * with its status and the button that fixes it. Gone once all three are set.
 */
function SetupCard(props: { onAction: (action: SummaryAction) => void }) {
  const model = setup.value;
  if (!model) {
    return null;
  }
  return (
    <section
      id="liveSetup"
      class="panel card live-setup"
      aria-labelledby="liveSetupTitle"
    >
      <div id="liveSetupTitle" class="card__title">
        {t("dashboard.setup.title")}
      </div>
      <div class="card__subtle">{t("dashboard.setup.hint")}</div>
      <ol class="live-setup__steps">
        {model.steps.map((step) => (
          <li
            key={step.key}
            class="live-setup__step"
            data-setup-step={step.key}
            data-step-state={step.state}
            aria-current={step.state === "current" ? "step" : undefined}
          >
            <span class="live-setup__mark" aria-hidden="true">
              {step.state === "done" ? "✓" : ""}
            </span>
            <div class="live-setup__text">
              <strong class="live-setup__title">{step.title}</strong>
              <span class="live-setup__status">{step.status}</span>
            </div>
            {step.action ? (
              <button
                type="button"
                class={
                  step.state === "current"
                    ? "btn btn--primary live-setup__action"
                    : "btn live-setup__action"
                }
                data-setup-action={step.action.action}
                onClick={() =>
                  step.action && props.onAction(step.action.action)
                }
              >
                {step.action.label}
              </button>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function BarButton(props: {
  button: ActionBarButton;
  primary: boolean;
  onAction: (action: SummaryAction) => void;
}) {
  const { button } = props;
  const tone = props.primary ? "btn--primary" : "btn--muted";
  if (button.kind === "start") {
    return (
      <button
        id="startLoggingBtn"
        class={`btn ${tone}`}
        type="button"
        disabled={button.disabled}
        onClick={() => void startRecording()}
      >
        {button.label}
      </button>
    );
  }
  if (button.kind === "stop") {
    return (
      <button
        id="stopLoggingBtn"
        class="btn btn--danger"
        type="button"
        disabled={button.disabled}
        onClick={() => void confirmAndStopRecording()}
      >
        {button.label}
      </button>
    );
  }
  const action = button.kind === "history" ? "open-history" : button.action;
  return (
    <button
      id={button.kind === "history" ? "liveOpenHistoryBtn" : "liveNextStepBtn"}
      class={`btn ${tone}`}
      type="button"
      data-bar-action={action}
      onClick={() => props.onAction(action)}
    >
      {button.label}
    </button>
  );
}

/**
 * The one next action: fixed to the bottom of a phone screen, within thumb
 * reach wherever the page is scrolled; at the end of the recording card on a
 * wide screen. While recording it turns red with the elapsed time and Stop.
 */
function ActionBar(props: { onAction: (action: SummaryAction) => void }) {
  const model = actionBar.value;
  // In the bar, so it is on screen right after the Start tap on a phone.
  const { keepAwakeHint } = alerts.value;
  const ref = useRef<HTMLDivElement>(null);
  // Live keeps room below its content for the bar, however tall it gets.
  useLayoutEffect(() => {
    const element = ref.current;
    const root = element?.closest<HTMLElement>(".live-dashboard");
    if (!element || !root || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => {
      root.style.setProperty(
        "--action-bar-height",
        `${element.getBoundingClientRect().height}px`,
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      id="liveActionBar"
      class="action-bar"
      data-state={model.state}
      ref={ref}
    >
      {keepAwakeHint ? (
        <details id="keepAwakeHint" class="action-bar__hint">
          <summary class="action-bar__hint-summary">
            {keepAwakeHint.body}{" "}
            <span class="action-bar__hint-more">
              {t("dashboard.logging.keep_awake_how")}
            </span>
          </summary>
          <p class="action-bar__hint-detail">{keepAwakeHint.detail}</p>
        </details>
      ) : null}
      <div class="action-bar__row">
        <div class="action-bar__status" aria-live="polite">
          <span class="action-bar__title">
            {model.state === "recording" ? (
              <span class="action-bar__dot" aria-hidden="true" />
            ) : null}
            {model.title}
            {model.elapsed ? (
              <span id="liveActionElapsed" class="action-bar__elapsed">
                {model.elapsed}
              </span>
            ) : null}
          </span>
          {model.detail ? (
            <span
              id="liveActionDetail"
              class="action-bar__detail"
              data-error={model.error ? "true" : undefined}
            >
              {model.detail}
            </span>
          ) : null}
        </div>
        <div class="action-bar__actions">
          {model.secondary ? (
            <BarButton
              button={model.secondary}
              primary={false}
              onAction={props.onAction}
            />
          ) : null}
          <BarButton button={model.primary} primary onAction={props.onAction} />
        </div>
      </div>
    </div>
  );
}

function Recording(props: { onAction: (action: SummaryAction) => void }) {
  const model = recording.value;
  return (
    <div
      class="realtime-logging-shell"
      data-layout={model.setupMode ? "setup" : undefined}
    >
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">{t("dashboard.run_recording")}</div>
          <Summary model={model} onAction={props.onAction} />
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
      <CapabilityLine />
      <GuidedTest />
      <ActionBar onAction={props.onAction} />
      {model.blockedReason ? (
        <p id="startBlockedReason" class="card__subtle logging-start-hint">
          {model.blockedReason}
        </p>
      ) : null}
      {model.showStop || model.startDisabled ? null : (
        <p id="startHint" class="card__subtle logging-start-hint">
          {t("dashboard.logging.start_hint")}
        </p>
      )}
    </div>
  );
}

/**
 * What a driver must see at a glance, in the sticky header so it stays on
 * screen wherever the page is scrolled: a quiet sensor while recording (on
 * every view), and on Live why the last run stopped by itself and the guided
 * step in progress.
 */
export function DriveAlerts(props: { onLive: boolean }) {
  const { sensorSilent } = alerts.value;
  const stopNotice = props.onLive ? alerts.value.stopNotice : null;
  const guidedStep = props.onLive && guidedTest.value.current !== null;
  if (!sensorSilent && !stopNotice && !guidedStep) {
    return null;
  }
  return (
    <div class="site-header__alerts">
      {sensorSilent ? (
        <div id="sensorSilentNotice" role="alert">
          <FeedbackBlock message={sensorSilent} />
        </div>
      ) : null}
      {stopNotice ? (
        <div id="autoStopNotice" role="alert">
          <FeedbackBlock message={stopNotice} />
        </div>
      ) : null}
      {guidedStep ? <GuidedStepCard /> : null}
    </div>
  );
}

/**
 * The Live view, in the same order in every state: setup (until done),
 * overview, spectrum (passed in by the shell) and recording. Without a live
 * sensor the overview and the spectrum have nothing to show and stay hidden.
 */
export function Dashboard(props: {
  spectrum: ComponentChildren;
  onAddCar: () => void;
}) {
  const onAction = (action: SummaryAction) => {
    if (action === "open-add-car") {
      props.onAddCar();
    } else {
      openSummaryTarget(action);
    }
  };
  const live = hasLiveSignal.value;
  return (
    <div class="live-dashboard">
      <SetupCard onAction={onAction} />
      <div class="dashboard-grid">
        <div class="panel card dashboard-grid__overview" hidden={!live}>
          <Overview />
        </div>
        <div class="panel card dashboard-grid__main" hidden={!live}>
          {props.spectrum}
        </div>
        <div class="panel card dashboard-grid__controls">
          <Recording onAction={onAction} />
        </div>
      </div>
    </div>
  );
}
