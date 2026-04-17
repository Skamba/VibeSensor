import { render } from "preact";

import { useUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import { inlineStateActionClass } from "./dom_helpers";
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

function RealtimeLoggingSummary(props: {
  summaryText: ReadonlySignal<string>;
  summaryPanel: ReadonlySignal<RealtimeLoggingSummaryPanelModel | null>;
  onAction: ((action: RealtimeLoggingSummaryAction) => void) | null;
}) {
  const summaryAction = useComputed(() => props.summaryPanel.value?.action ?? null);
  const hidden = useComputed(() =>
    props.summaryText.value === "" && props.summaryPanel.value === null
  );
  const summaryLayout = useComputed(() =>
    props.summaryPanel.value ? "panel" : undefined
  );

  return (
    <div
      id="loggingSummary"
      class="card__subtle"
      hidden={hidden}
      data-summary-layout={summaryLayout}
    >
      {props.summaryPanel.value
        ? (
          <div class={`empty-state empty-state--inline${summaryAction.value ? " empty-state--actionable" : ""}`}>
            <strong class="empty-state__title">{props.summaryPanel.value.titleText}</strong>
            <span class="empty-state__body">{props.summaryPanel.value.bodyText}</span>
            {props.summaryPanel.value.detailText
              ? <span class="empty-state__detail">{props.summaryPanel.value.detailText}</span>
              : null}
            {summaryAction.value
              ? (
                <div class="empty-state__actions">
                  <button
                    type="button"
                    class={inlineStateActionClass(summaryAction.value.variant)}
                    data-inline-state-action={summaryAction.value.action}
                    onClick={() => props.onAction?.(summaryAction.value!.action)}
                  >
                    {summaryAction.value.labelText}
                  </button>
                </div>
              )
              : null}
          </div>
        )
        : props.summaryText}
    </div>
  );
}

function RealtimeLoggingChecklist(props: {
  checklist: ReadonlySignal<RealtimeCaptureReadinessChecklistModel | null>;
}) {
  const hidden = useComputed(() => props.checklist.value === null);

  return (
    <div id="loggingChecklist" class="capture-readiness" hidden={hidden}>
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

function RealtimeLoggingPanel(props: {
  actions: ReadonlySignal<RealtimeLoggingPanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<RealtimeLoggingPanelRenderModel> | null>;
}) {
  const titleText = useUiText("dashboard.run_recording", "Run Recording");
  const runProgressLabel = useUiText("dashboard.recording_progress", "Run progress");
  const runPhaseLabel = useUiText("dashboard.recording_phase", "Run phase");
  const elapsedLabel = useUiText("dashboard.recording_elapsed", "Elapsed");
  const samplesLabel = useUiText("dashboard.recording_samples", "Samples recorded");
  const startLabel = useUiText("dashboard.start_recording", "Start Recording");
  const stopLabel = useUiText("dashboard.stop_recording", "Stop Recording");
  const actions = useComputed(() => props.actions.value);
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_PANEL_MODEL);
  const {
    checklist,
    elapsedText,
    phaseText,
    pillText,
    pillVariant,
    runIdText,
    samplesText,
    setupMode,
    showPill,
    showStart,
    showStop,
    startDisabled,
    stopDisabled,
    summaryPanel,
    summaryText,
  } = useSignalProperties(model, REALTIME_LOGGING_PANEL_MODEL_KEYS);
  const shellLayout = useComputed(() => setupMode.value ? "setup" : undefined);
  const loggingRowHidden = useComputed(() => !showPill.value && runIdText.value === "");
  const pillHidden = useComputed(() => !showPill.value);
  const runIdHidden = useComputed(() => runIdText.value === "");
  const showProgressSection = useComputed(() => !setupMode.value || checklist.value !== null);
  const startHidden = useComputed(() => !showStart.value);
  const stopHidden = useComputed(() => !showStop.value);
  const handleSummaryAction = (action: RealtimeLoggingSummaryAction) => {
    actions.value?.onSummaryAction(action);
  };
  const handleStartLogging = () => {
    actions.value?.onStartLogging();
  };
  const handleStopLogging = () => {
    actions.value?.onStopLogging();
  };

  return (
    <div class="realtime-logging-shell" data-layout={shellLayout}>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {titleText}
          </div>
          <RealtimeLoggingSummary
            summaryText={summaryText}
            summaryPanel={summaryPanel}
            onAction={handleSummaryAction}
          />
        </div>
      </div>
      <div class="logging-row" hidden={loggingRowHidden}>
        <span
          id="loggingStatus"
          class="pill"
          data-variant={pillVariant}
          hidden={pillHidden}
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
            <RealtimeLoggingChecklist checklist={checklist} />
          </>
        )
        : null}
      <div class="logging-actions">
        <button
          id="startLoggingBtn"
          class="btn btn--primary"
          type="button"

          hidden={startHidden}
          disabled={startDisabled}
          onClick={handleStartLogging}
        >
          {startLabel}
        </button>
        <button
          id="stopLoggingBtn"
          class="btn btn--danger-quiet"
          type="button"

          hidden={stopHidden}
          disabled={stopDisabled}
          onClick={handleStopLogging}
        >
          {stopLabel}
        </button>
      </div>
    </div>
  );
}

export function mountRealtimeLoggingPanel(
  host: HTMLElement,
  view: RealtimeLoggingPanelBridge,
): void {
  render(<RealtimeLoggingPanel actions={view.actions} model={view.model} />, host);
}
