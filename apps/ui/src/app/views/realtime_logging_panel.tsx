import { render } from "preact";

import { getUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import { inlineStateActionClass } from "./inline_state_panel_models";
import { type DeferredModelSignal } from "./view_model_binding";
import type {
  RealtimeCaptureReadinessChecklistModel,
  RealtimeLoggingSummaryAction,
  RealtimeLoggingSummaryPanelModel,
} from "./realtime_logging_view_models";

export interface RealtimeLoggingPanelRenderModel {
  pillVariant: "muted" | "ok" | "warn" | "bad";
  pillText: string;
  showPill: boolean;
  summaryText: string;
  summaryPanel: RealtimeLoggingSummaryPanelModel | null;
  runIdText: string;
  phaseText: string;
  elapsedText: string;
  samplesText: string;
  checklist: RealtimeCaptureReadinessChecklistModel | null;
  showStart: boolean;
  showStop: boolean;
  startDisabled: boolean;
  stopDisabled: boolean;
  setupMode: boolean;
}

export interface RealtimeLoggingPanelActionHandlers {
  onStartLogging: () => void;
  onStopLogging: () => void;
  onSummaryAction: (action: RealtimeLoggingSummaryAction) => void;
}

export interface RealtimeLoggingPanelBridge {
  actions: Signal<RealtimeLoggingPanelActionHandlers | null>;
  model: DeferredModelSignal<RealtimeLoggingPanelRenderModel>;
}

const DEFAULT_PANEL_MODEL: RealtimeLoggingPanelRenderModel = {
  pillVariant: "muted",
  pillText: "Stopped",
  showPill: true,
  summaryText: "Connect sensors to begin a trustworthy run.",
  summaryPanel: null,
  runIdText: "",
  phaseText: "--",
  elapsedText: "--",
  samplesText: "0",
  checklist: null,
  showStart: true,
  showStop: false,
  startDisabled: false,
  stopDisabled: true,
  setupMode: false,
};

const REALTIME_LOGGING_PANEL_MODEL_KEYS = [
  "checklist",
  "elapsedText",
  "phaseText",
  "pillText",
  "pillVariant",
  "runIdText",
  "samplesText",
  "setupMode",
  "showPill",
  "showStart",
  "showStop",
  "startDisabled",
  "stopDisabled",
  "summaryPanel",
  "summaryText",
] as const;

function RealtimeLoggingSummarySection(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { summaryPanel, summaryText } = useSignalProperties(
    props.model,
    ["summaryPanel", "summaryText"] as const,
  );
  const summaryAction = useComputed(() => summaryPanel.value?.action ?? null);
  const hidden = useComputed(() =>
    summaryText.value === "" && summaryPanel.value === null
  );
  const summaryLayout = useComputed(() =>
    summaryPanel.value ? "panel" : undefined
  );
  const handleAction = (action: RealtimeLoggingSummaryAction) => {
    props.actions.value?.onSummaryAction(action);
  };

  return (
    <div
      id="loggingSummary"
      class="card__subtle"
      hidden={hidden.value}
      data-summary-layout={summaryLayout.value}
    >
      {summaryPanel.value
        ? (
          <div class={`empty-state empty-state--inline${summaryAction.value ? " empty-state--actionable" : ""}`}>
            <strong class="empty-state__title">{summaryPanel.value.titleText}</strong>
            <span class="empty-state__body">{summaryPanel.value.bodyText}</span>
            {summaryPanel.value.detailText
              ? <span class="empty-state__detail">{summaryPanel.value.detailText}</span>
              : null}
            {summaryAction.value
              ? (
                <div class="empty-state__actions">
                  <button
                    type="button"
                    class={inlineStateActionClass(summaryAction.value.variant)}
                    data-inline-state-action={summaryAction.value.action}
                    onClick={() => handleAction(summaryAction.value!.action)}
                  >
                    {summaryAction.value.labelText}
                  </button>
                </div>
              )
              : null}
          </div>
        )
        : summaryText.value}
    </div>
  );
}

function RealtimeLoggingChecklist(props: {
  checklist: ReadonlySignal<RealtimeCaptureReadinessChecklistModel | null>;
}) {
  const hidden = useComputed(() => props.checklist.value === null);

  return (
    <div id="loggingChecklist" class="capture-readiness" hidden={hidden.value}>
      {props.checklist.value
        ? (
          <>
            <div class="capture-readiness__title">{props.checklist.value.titleText}</div>
            <div class="capture-readiness__list">
              {props.checklist.value.items.map((item) => (
                <div
                  key={item.checkKey}
                  class="capture-readiness__item"
                  data-readiness-state={item.state}
                >
                  <div class="capture-readiness__row">
                    <span class="capture-readiness__label">{item.labelText}</span>
                    <span class="capture-readiness__state">{item.stateText}</span>
                  </div>
                  <div class="capture-readiness__detail">{item.detailText}</div>
                </div>
              ))}
            </div>
          </>
        )
        : null}
    </div>
  );
}

function RealtimeLoggingStatusRow(props: {
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { pillText, pillVariant, runIdText, showPill } = useSignalProperties(
    props.model,
    ["pillText", "pillVariant", "runIdText", "showPill"] as const,
  );
  const loggingRowHidden = useComputed(() => !showPill.value && runIdText.value === "");
  const pillHidden = useComputed(() => !showPill.value);
  const runIdHidden = useComputed(() => runIdText.value === "");

  return (
    <div class="logging-row" hidden={loggingRowHidden.value}>
      <span
        id="loggingStatus"
        class="pill"
        data-variant={pillVariant.value}
        hidden={pillHidden.value}
        aria-live="polite"
      >
        {pillText.value}
      </span>
      <span id="loggingRunId" class="subtle" hidden={runIdHidden.value}>
        {runIdText.value}
      </span>
    </div>
  );
}

function RealtimeLoggingProgressSection(props: {
  labels: {
    elapsedLabel: string;
    runPhaseLabel: string;
    runProgressLabel: string;
    samplesLabel: string;
  };
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { checklist, elapsedText, phaseText, samplesText, setupMode } = useSignalProperties(
    props.model,
    ["checklist", "elapsedText", "phaseText", "samplesText", "setupMode"] as const,
  );
  const showProgressSection = useComputed(() => !setupMode.value || checklist.value !== null);

  if (!showProgressSection.value) {
    return null;
  }

  return (
    <>
      <div class="mini-label">
        {props.labels.runProgressLabel}
      </div>
      <div class="stat-grid stat-grid--compact">
        <div id="loggingPhase" class="stat stat--compact" hidden>
          <div class="stat__label">
            {props.labels.runPhaseLabel}
          </div>
          <div class="stat__value" data-value>
            {phaseText.value}
          </div>
        </div>
        <div id="loggingElapsed" class="stat stat--compact">
          <div class="stat__label">
            {props.labels.elapsedLabel}
          </div>
          <div class="stat__value" data-value>
            {elapsedText.value}
          </div>
        </div>
        <div id="loggingSamples" class="stat stat--compact">
          <div class="stat__label">
            {props.labels.samplesLabel}
          </div>
          <div class="stat__value" data-value>
            {samplesText.value}
          </div>
        </div>
      </div>
      <RealtimeLoggingChecklist checklist={checklist} />
    </>
  );
}

function RealtimeLoggingActionRow(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  labels: {
    startLabel: string;
    stopLabel: string;
  };
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { showStart, showStop, startDisabled, stopDisabled } = useSignalProperties(
    props.model,
    ["showStart", "showStop", "startDisabled", "stopDisabled"] as const,
  );
  const startHidden = useComputed(() => !showStart.value);
  const stopHidden = useComputed(() => !showStop.value);
  const handleStartLogging = () => {
    props.actions.value?.onStartLogging();
  };
  const handleStopLogging = () => {
    props.actions.value?.onStopLogging();
  };

  return (
    <div class="logging-actions">
      <button
        id="startLoggingBtn"
        class="btn btn--primary"
        type="button"
        hidden={startHidden.value}
        disabled={startDisabled.value}
        onClick={handleStartLogging}
      >
        {props.labels.startLabel}
      </button>
      <button
        id="stopLoggingBtn"
        class="btn btn--danger-quiet"
        type="button"
        hidden={stopHidden.value}
        disabled={stopDisabled.value}
        onClick={handleStopLogging}
      >
        {props.labels.stopLabel}
      </button>
    </div>
  );
}

function RealtimeLoggingPanel(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<RealtimeLoggingPanelRenderModel> | null>;
}) {
  const actions = useComputed(() => props.actions.value);
  const labels = useComputed(() => ({
    elapsedLabel: getUiText("dashboard.recording_elapsed", "Elapsed"),
    runPhaseLabel: getUiText("dashboard.recording_phase", "Run phase"),
    runProgressLabel: getUiText("dashboard.recording_progress", "Run progress"),
    samplesLabel: getUiText("dashboard.recording_samples", "Samples recorded"),
    startLabel: getUiText("dashboard.start_recording", "Start Recording"),
    stopLabel: getUiText("dashboard.stop_recording", "Stop Recording"),
    titleText: getUiText("dashboard.run_recording", "Run Recording"),
  }));
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_PANEL_MODEL);
  const { setupMode } = useSignalProperties(model, ["setupMode"] as const);
  const shellLayout = useComputed(() => setupMode.value ? "setup" : undefined);
  const labelTexts = labels.value;

  return (
    <div class="realtime-logging-shell" data-layout={shellLayout.value}>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {labelTexts.titleText}
          </div>
          <RealtimeLoggingSummarySection actions={actions} model={model} />
        </div>
      </div>
      <RealtimeLoggingStatusRow model={model} />
      <RealtimeLoggingProgressSection
        labels={{
          elapsedLabel: labelTexts.elapsedLabel,
          runPhaseLabel: labelTexts.runPhaseLabel,
          runProgressLabel: labelTexts.runProgressLabel,
          samplesLabel: labelTexts.samplesLabel,
        }}
        model={model}
      />
      <RealtimeLoggingActionRow
        actions={actions}
        labels={{
          startLabel: labelTexts.startLabel,
          stopLabel: labelTexts.stopLabel,
        }}
        model={model}
      />
    </div>
  );
}

export function mountRealtimeLoggingPanel(
  host: HTMLElement,
  view: RealtimeLoggingPanelBridge,
): void {
  render(<RealtimeLoggingPanel actions={view.actions} model={view.model} />, host);
}
