import { render } from "preact";

import { useUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import { inlineStateActionClass } from "./inline_state_panel_models";
import { type DeferredModelSignal, useDeferredModel } from "./view_model_binding";
import type {
  RealtimeCaptureReadinessChecklistModel,
  RealtimeLoggingSummaryAction,
  RealtimeLoggingSummaryPanelModel,
} from "./realtime_logging_view_models";

export interface RealtimeLoggingPanelRenderModel {
  pillVariant: "muted" | "ok" | "warn" | "bad";
  pillText: string;
  showPill: boolean;
  pillHidden: boolean;
  summaryText: string;
  summaryPanel: RealtimeLoggingSummaryPanelModel | null;
  summaryAction: RealtimeLoggingSummaryPanelModel["action"] | null;
  summaryHidden: boolean;
  summaryLayout: "panel" | undefined;
  runIdText: string;
  runIdHidden: boolean;
  loggingRowHidden: boolean;
  phaseText: string;
  elapsedText: string;
  samplesText: string;
  checklist: RealtimeCaptureReadinessChecklistModel | null;
  checklistHidden: boolean;
  showProgressSection: boolean;
  showStart: boolean;
  startHidden: boolean;
  showStop: boolean;
  stopHidden: boolean;
  startDisabled: boolean;
  stopDisabled: boolean;
  setupMode: boolean;
  shellLayout: "setup" | undefined;
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
  pillHidden: false,
  summaryText: "Connect sensors to begin a trustworthy run.",
  summaryPanel: null,
  summaryAction: null,
  summaryHidden: false,
  summaryLayout: undefined,
  runIdText: "",
  runIdHidden: true,
  loggingRowHidden: false,
  phaseText: "--",
  elapsedText: "--",
  samplesText: "0",
  checklist: null,
  checklistHidden: true,
  showProgressSection: true,
  showStart: true,
  startHidden: false,
  showStop: false,
  stopHidden: true,
  startDisabled: false,
  stopDisabled: true,
  setupMode: false,
  shellLayout: undefined,
};

const REALTIME_LOGGING_PANEL_MODEL_KEYS = [
  "checklist",
  "checklistHidden",
  "elapsedText",
  "loggingRowHidden",
  "phaseText",
  "pillHidden",
  "pillText",
  "pillVariant",
  "runIdHidden",
  "runIdText",
  "samplesText",
  "shellLayout",
  "setupMode",
  "showProgressSection",
  "showPill",
  "showStart",
  "showStop",
  "startDisabled",
  "startHidden",
  "stopHidden",
  "stopDisabled",
  "summaryAction",
  "summaryHidden",
  "summaryLayout",
  "summaryPanel",
  "summaryText",
] as const;

function RealtimeLoggingSummarySection(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const {
    summaryAction,
    summaryHidden,
    summaryLayout,
    summaryPanel,
    summaryText,
  } = useSignalProperties(
    props.model,
    ["summaryAction", "summaryHidden", "summaryLayout", "summaryPanel", "summaryText"] as const,
  );
  const handleAction = (action: RealtimeLoggingSummaryAction) => {
    props.actions.peek()?.onSummaryAction(action);
  };

  return (
    <div
      id="loggingSummary"
      class="card__subtle"
      hidden={summaryHidden.value}
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
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { checklist, checklistHidden } = useSignalProperties(
    props.model,
    ["checklist", "checklistHidden"] as const,
  );

  return (
    <div id="loggingChecklist" class="capture-readiness" hidden={checklistHidden.value}>
      {checklist.value
        ? (
          <>
            <div class="capture-readiness__title">{checklist.value.titleText}</div>
            <div class="capture-readiness__list">
              {checklist.value.items.map((item) => (
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
  const {
    loggingRowHidden,
    pillHidden,
    pillText,
    pillVariant,
    runIdHidden,
    runIdText,
  } = useSignalProperties(
    props.model,
    ["loggingRowHidden", "pillHidden", "pillText", "pillVariant", "runIdHidden", "runIdText"] as const,
  );

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
    elapsedLabel: ReadonlySignal<string>;
    runPhaseLabel: ReadonlySignal<string>;
    runProgressLabel: ReadonlySignal<string>;
    samplesLabel: ReadonlySignal<string>;
  };
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { elapsedText, phaseText, samplesText, showProgressSection } = useSignalProperties(
    props.model,
    ["elapsedText", "phaseText", "samplesText", "showProgressSection"] as const,
  );

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
      <RealtimeLoggingChecklist model={props.model} />
    </>
  );
}

function RealtimeLoggingActionRow(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  labels: {
    startLabel: ReadonlySignal<string>;
    stopLabel: ReadonlySignal<string>;
  };
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const { startDisabled, startHidden, stopDisabled, stopHidden } = useSignalProperties(
    props.model,
    ["startDisabled", "startHidden", "stopDisabled", "stopHidden"] as const,
  );
  const handleStartLogging = () => {
    props.actions.peek()?.onStartLogging();
  };
  const handleStopLogging = () => {
    props.actions.peek()?.onStopLogging();
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
  const elapsedLabel = useUiText("dashboard.recording_elapsed", "Elapsed");
  const runPhaseLabel = useUiText("dashboard.recording_phase", "Run phase");
  const runProgressLabel = useUiText("dashboard.recording_progress", "Run progress");
  const samplesLabel = useUiText("dashboard.recording_samples", "Samples recorded");
  const startLabel = useUiText("dashboard.start_recording", "Start Recording");
  const stopLabel = useUiText("dashboard.stop_recording", "Stop Recording");
  const titleText = useUiText("dashboard.run_recording", "Run Recording");
  const model = useDeferredModel(props.model, DEFAULT_PANEL_MODEL);
  const { shellLayout } = useSignalProperties(model, ["shellLayout"] as const);

  return (
    <div class="realtime-logging-shell" data-layout={shellLayout.value}>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {titleText}
          </div>
          <RealtimeLoggingSummarySection actions={actions} model={model} />
        </div>
      </div>
      <RealtimeLoggingStatusRow model={model} />
      <RealtimeLoggingProgressSection
        labels={{
          elapsedLabel,
          runPhaseLabel,
          runProgressLabel,
          samplesLabel,
        }}
        model={model}
      />
      <RealtimeLoggingActionRow
        actions={actions}
        labels={{
          startLabel,
          stopLabel,
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
