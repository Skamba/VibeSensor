import { render } from "preact";

import { useUiTranslation } from "../ui_i18n";
import { signal, type ReadonlySignal } from "../ui_signals";
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

interface RealtimeLoggingPanelBridgeState {
  actions: RealtimeLoggingPanelActionHandlers | null;
  model: ReadonlySignal<RealtimeLoggingPanelRenderModel> | null;
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

const DEFAULT_PANEL_STATE: RealtimeLoggingPanelBridgeState = {
  actions: null,
  model: null,
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
  state: ReadonlySignal<RealtimeLoggingPanelBridgeState>;
}) {
  const state = props.state.value;
  const model = state.model?.value ?? DEFAULT_PANEL_MODEL;
  const t = useUiTranslation();
  const loggingRowHidden = !model.showPill && model.runIdText === "";
  const showProgressSection = !model.setupMode || model.checklist !== null;

  return (
    <div class="realtime-logging-shell" data-layout={model.setupMode ? "setup" : undefined}>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {t("dashboard.run_recording", "Run Recording")}
          </div>
          <RealtimeLoggingSummary
            summaryText={model.summaryText}
            summaryPanel={model.summaryPanel}
            onAction={state.actions?.onSummaryAction ?? null}
          />
        </div>
      </div>
      <div class="logging-row" hidden={loggingRowHidden}>
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
      {showProgressSection
        ? (
          <>
            <div class="mini-label">
              {t("dashboard.recording_progress", "Run progress")}
            </div>
            <div class="stat-grid stat-grid--compact">
              <div id="loggingPhase" class="stat stat--compact" hidden>
                <div class="stat__label">
                  {t("dashboard.recording_phase", "Run phase")}
                </div>
                <div class="stat__value" data-value>
                  {model.phaseText}
                </div>
              </div>
              <div id="loggingElapsed" class="stat stat--compact">
                <div class="stat__label">
                  {t("dashboard.recording_elapsed", "Elapsed")}
                </div>
                <div class="stat__value" data-value>
                  {model.elapsedText}
                </div>
              </div>
              <div id="loggingSamples" class="stat stat--compact">
                <div class="stat__label">
                  {t("dashboard.recording_samples", "Samples recorded")}
                </div>
                <div class="stat__value" data-value>
                  {model.samplesText}
                </div>
              </div>
            </div>
            <RealtimeLoggingChecklist checklist={model.checklist} />
          </>
        )
        : null}
      <div class="logging-actions">
        <button
          id="startLoggingBtn"
          class="btn btn--primary"
          type="button"

          hidden={!model.showStart}
          disabled={model.startDisabled}
          onClick={() => state.actions?.onStartLogging()}
        >
          {t("dashboard.start_recording", "Start Recording")}
        </button>
        <button
          id="stopLoggingBtn"
          class="btn btn--danger-quiet"
          type="button"

          hidden={!model.showStop}
          disabled={model.stopDisabled}
          onClick={() => state.actions?.onStopLogging()}
        >
          {t("dashboard.stop_recording", "Stop Recording")}
        </button>
      </div>
    </div>
  );
}

export function mountRealtimeLoggingPanel(host: HTMLElement): RealtimeLoggingPanelBridge {
  const state = signal<RealtimeLoggingPanelBridgeState>({ ...DEFAULT_PANEL_STATE });
  render(<RealtimeLoggingPanel state={state} />, host);

  return {
    bindModel(model: ReadonlySignal<RealtimeLoggingPanelRenderModel>): void {
      state.value = { ...state.value, model };
    },
    bindActions(handlers: RealtimeLoggingPanelActionHandlers): void {
      state.value = { ...state.value, actions: handlers };
    },
  };
}
