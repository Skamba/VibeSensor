import { render } from "preact";

import { useUiText } from "../ui_i18n";
import {
  computed,
  signal,
  useComputed,
  type ReadonlySignal,
} from "../ui_signals";
import { inlineStateActionClass } from "./dom_helpers";
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
  bindModel(model: ReadonlySignal<RealtimeLoggingPanelRenderModel>): void;
  bindActions(handlers: RealtimeLoggingPanelActionHandlers): void;
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

function RealtimeLoggingSummary(props: {
  summaryText: string;
  summaryPanel: RealtimeLoggingSummaryPanelModel | null;
  onAction: ((action: RealtimeLoggingSummaryAction) => void) | null;
}) {
  const { summaryText, summaryPanel, onAction } = props;
  const summaryAction = summaryPanel?.action ?? null;

  return (
    <div
      id="loggingSummary"
      class="card__subtle"
      hidden={summaryText === "" && summaryPanel === null}
      data-summary-layout={summaryPanel ? "panel" : undefined}
    >
      {summaryPanel
        ? (
          <div class={`empty-state empty-state--inline${summaryAction ? " empty-state--actionable" : ""}`}>
            <strong class="empty-state__title">{summaryPanel.titleText}</strong>
            <span class="empty-state__body">{summaryPanel.bodyText}</span>
            {summaryPanel.detailText
              ? <span class="empty-state__detail">{summaryPanel.detailText}</span>
              : null}
            {summaryAction
              ? (
                <div class="empty-state__actions">
                  <button
                    type="button"
                    class={inlineStateActionClass(summaryAction.variant)}
                    data-inline-state-action={summaryAction.action}
                    onClick={() => onAction?.(summaryAction.action)}
                  >
                    {summaryAction.labelText}
                  </button>
                </div>
              )
              : null}
          </div>
        )
        : summaryText}
    </div>
  );
}

function RealtimeLoggingChecklist(props: {
  checklist: RealtimeCaptureReadinessChecklistModel | null;
}) {
  const { checklist } = props;

  return (
    <div id="loggingChecklist" class="capture-readiness" hidden={checklist === null}>
      {checklist
        ? (
          <>
            <div class="capture-readiness__title">{checklist.titleText}</div>
            <div class="capture-readiness__list">
              {checklist.items.map((item) => (
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

function RealtimeLoggingPanel(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
}) {
  const titleText = useUiText("dashboard.run_recording", "Run Recording");
  const runProgressLabel = useUiText("dashboard.recording_progress", "Run progress");
  const runPhaseLabel = useUiText("dashboard.recording_phase", "Run phase");
  const elapsedLabel = useUiText("dashboard.recording_elapsed", "Elapsed");
  const samplesLabel = useUiText("dashboard.recording_samples", "Samples recorded");
  const startLabel = useUiText("dashboard.start_recording", "Start Recording");
  const stopLabel = useUiText("dashboard.stop_recording", "Stop Recording");
  const pillVariant = useComputed(() => props.model.value.pillVariant);
  const pillText = useComputed(() => props.model.value.pillText);
  const showPill = useComputed(() => props.model.value.showPill);
  const summaryText = useComputed(() => props.model.value.summaryText);
  const summaryPanel = useComputed(() => props.model.value.summaryPanel);
  const runIdText = useComputed(() => props.model.value.runIdText);
  const phaseText = useComputed(() => props.model.value.phaseText);
  const elapsedText = useComputed(() => props.model.value.elapsedText);
  const samplesText = useComputed(() => props.model.value.samplesText);
  const checklist = useComputed(() => props.model.value.checklist);
  const showStart = useComputed(() => props.model.value.showStart);
  const showStop = useComputed(() => props.model.value.showStop);
  const startDisabled = useComputed(() => props.model.value.startDisabled);
  const stopDisabled = useComputed(() => props.model.value.stopDisabled);
  const setupMode = useComputed(() => props.model.value.setupMode);
  const shellLayout = useComputed(() => setupMode.value ? "setup" : undefined);
  const loggingRowHidden = useComputed(() => !showPill.value && runIdText.value === "");
  const showPillHidden = useComputed(() => !showPill.value);
  const runIdHidden = useComputed(() => runIdText.value === "");
  const showProgressSection = useComputed(() => !setupMode.value || checklist.value !== null);
  const showStartHidden = useComputed(() => !showStart.value);
  const showStopHidden = useComputed(() => !showStop.value);

  return (
    <div class="realtime-logging-shell" data-layout={shellLayout}>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {titleText}
          </div>
          <RealtimeLoggingSummary
            summaryText={summaryText.value}
            summaryPanel={summaryPanel.value}
            onAction={props.actions.value?.onSummaryAction ?? null}
          />
        </div>
      </div>
      <div class="logging-row" hidden={loggingRowHidden}>
        <span
          id="loggingStatus"
          class="pill"
          data-variant={pillVariant}
          hidden={showPillHidden}
          aria-live="polite"
        >
          {pillText}
        </span>
        <span id="loggingRunId" class="subtle" hidden={runIdHidden}>
          {runIdText}
        </span>
      </div>
      {showProgressSection.value
        ? (
          <>
            <div class="mini-label">
              {runProgressLabel}
            </div>
            <div class="stat-grid stat-grid--compact">
              <div id="loggingPhase" class="stat stat--compact" hidden>
                <div class="stat__label">
                  {runPhaseLabel}
                </div>
                <div class="stat__value" data-value>
                  {phaseText}
                </div>
              </div>
              <div id="loggingElapsed" class="stat stat--compact">
                <div class="stat__label">
                  {elapsedLabel}
                </div>
                <div class="stat__value" data-value>
                  {elapsedText}
                </div>
              </div>
              <div id="loggingSamples" class="stat stat--compact">
                <div class="stat__label">
                  {samplesLabel}
                </div>
                <div class="stat__value" data-value>
                  {samplesText}
                </div>
              </div>
            </div>
            <RealtimeLoggingChecklist checklist={checklist.value} />
          </>
        )
        : null}
      <div class="logging-actions">
        <button
          id="startLoggingBtn"
          class="btn btn--primary"
          type="button"

          hidden={showStartHidden}
          disabled={startDisabled}
          onClick={() => props.actions.value?.onStartLogging()}
        >
          {startLabel}
        </button>
        <button
          id="stopLoggingBtn"
          class="btn btn--danger-quiet"
          type="button"

          hidden={showStopHidden}
          disabled={stopDisabled}
          onClick={() => props.actions.value?.onStopLogging()}
        >
          {stopLabel}
        </button>
      </div>
    </div>
  );
}

export function mountRealtimeLoggingPanel(host: HTMLElement): RealtimeLoggingPanelBridge {
  const actions = signal<RealtimeLoggingPanelActionHandlers | null>(null);
  const modelSource = signal<ReadonlySignal<RealtimeLoggingPanelRenderModel> | null>(null);
  const model = computed<RealtimeLoggingPanelRenderModel>(() => modelSource.value?.value ?? DEFAULT_PANEL_MODEL);
  render(<RealtimeLoggingPanel actions={actions} model={model} />, host);

  return {
    bindModel(model: ReadonlySignal<RealtimeLoggingPanelRenderModel>): void {
      modelSource.value = model;
    },
    bindActions(handlers: RealtimeLoggingPanelActionHandlers): void {
      actions.value = handlers;
    },
  };
}
