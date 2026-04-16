import { render, type ComponentChildren } from "preact";

import { useUiText } from "../ui_i18n";
import {
  computed,
  signal,
  useComputed,
  type ReadonlySignal,
} from "../ui_signals";
import type {
  UpdateCurrentStatusSectionModel,
  UpdateHealthSectionModel,
  UpdateIssuesSectionModel,
  UpdateJourneyFailureNoteModel,
  UpdateJourneySectionModel,
  UpdateJourneyStageModel,
  UpdateLatestAttemptSectionModel,
  UpdateLogEmptyStateModel,
  UpdateLogSectionModel,
  UpdateStatusBadgeModel,
  UpdateStatusPanelViewModel,
  UpdateStatusRowModel,
} from "./update_status_models";

export interface UpdatePanelRenderModel {
  cancelButtonDisabled: boolean;
  cancelButtonHidden: boolean;
  startButtonDisabled: boolean;
  startButtonHidden: boolean;
  startButtonLabelText: string;
  status: UpdateStatusPanelViewModel | null;
}

export interface UpdatePanelActionHandlers {
  onCancel(): void;
  onStart(): void;
}

export interface UpdatePanelView {
  bindActions(handlers: UpdatePanelActionHandlers): void;
  bindModel(model: ReadonlySignal<UpdatePanelRenderModel>): void;
}

const DEFAULT_UPDATE_PANEL_MODEL: UpdatePanelRenderModel = {
  cancelButtonDisabled: true,
  cancelButtonHidden: true,
  startButtonDisabled: true,
  startButtonHidden: false,
  startButtonLabelText: "Start Update",
  status: null,
};

function UpdateBadge(props: { badge: UpdateStatusBadgeModel }) {
  const { badge } = props;
  return (
    <span class="pill" data-variant={badge.variant}>
      {badge.text}
    </span>
  );
}

function StatusGrid(props: { rows: readonly UpdateStatusRowModel[] }) {
  const { rows } = props;
  return (
    <div class="status-grid">
      {rows.map((row) => (
        <div class="status-grid__row" key={`${row.labelText}:${row.valueText}`}>
          <span class="status-grid__label">{row.labelText}</span>
          <span>{row.valueText}</span>
        </div>
      ))}
    </div>
  );
}

function IssueDetail(props: { text: string }) {
  return <div class="issue-detail">{props.text}</div>;
}

function MaintenanceNote(props: {
  text: string;
  variant?: "bad";
}) {
  const className = props.variant
    ? `maintenance-note maintenance-note--${props.variant}`
    : "maintenance-note";
  return <div class={className}>{props.text}</div>;
}

function InlineEmptyState(props: {
  emptyState: UpdateLogEmptyStateModel;
}) {
  const { emptyState } = props;
  return (
    <div class="empty-state empty-state--inline">
      <strong class="empty-state__title">{emptyState.titleText}</strong>
      <span class="empty-state__body">{emptyState.bodyText}</span>
    </div>
  );
}

function MaintenanceCard(props: {
  badge?: UpdateStatusBadgeModel | null;
  children: ComponentChildren;
  subtitleText: string;
  titleText: string;
}) {
  const { badge, children, subtitleText, titleText } = props;
  return (
    <section class="maintenance-card">
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">{titleText}</div>
          <div class="subtle">{subtitleText}</div>
        </div>
        {badge ? <UpdateBadge badge={badge} /> : null}
      </div>
      <div class="maintenance-card__body">{children}</div>
    </section>
  );
}

function UpdateCurrentStatusCard(props: {
  model: UpdateCurrentStatusSectionModel;
}) {
  const { model } = props;
  return (
    <MaintenanceCard
      badge={model.badge}
      subtitleText={model.summaryText}
      titleText={model.titleText}
    >
      {model.rows.length > 0 ? (
        <StatusGrid rows={model.rows} />
      ) : (
        <MaintenanceNote text={model.emptyText ?? ""} />
      )}
    </MaintenanceCard>
  );
}

function JourneyFailureStack(props: {
  failure: UpdateJourneyFailureNoteModel;
}) {
  const { failure } = props;
  return (
    <div class="maintenance-stack maintenance-stack--tight">
      <div class="maintenance-note maintenance-note--bad">
        <strong>{failure.summaryText}</strong>
        {failure.detailText ? <IssueDetail text={failure.detailText} /> : null}
      </div>
      <div class="maintenance-note">
        <strong>{failure.recoveryTitleText}</strong>
        <IssueDetail text={failure.recoveryDetailText} />
      </div>
    </div>
  );
}

function JourneyStageItem(props: {
  stage: UpdateJourneyStageModel;
}) {
  const { stage } = props;
  return (
    <li
      class="maintenance-stage"
      data-stage-phase={stage.phase}
      data-stage-state={stage.state}
      aria-current={stage.current ? "step" : undefined}
    >
      <span class="maintenance-stage__marker">{stage.markerText}</span>
      <div class="maintenance-stage__body">
        <div class="maintenance-stage__title">{stage.titleText}</div>
        <div class="maintenance-stage__detail">{stage.detailText}</div>
      </div>
      <span class="maintenance-stage__state">{stage.stateText}</span>
    </li>
  );
}

function UpdateJourneyCard(props: {
  model: UpdateJourneySectionModel;
}) {
  const { model } = props;
  return (
    <MaintenanceCard
      subtitleText={model.subtitleText}
      titleText={model.titleText}
    >
      <div class="maintenance-journey">
        {model.failureNote ? (
          <JourneyFailureStack failure={model.failureNote} />
        ) : null}
        <ol class="maintenance-stage-list">
          {model.stages.map((stage) => (
            <JourneyStageItem key={stage.phase} stage={stage} />
          ))}
        </ol>
      </div>
    </MaintenanceCard>
  );
}

function UpdateIssuesCard(props: {
  model: UpdateIssuesSectionModel;
}) {
  const { model } = props;
  return (
    <MaintenanceCard
      subtitleText={model.subtitleText}
      titleText={model.titleText}
    >
      <ul class="issue-list">
        {model.items.map((item, index) => (
          <li class="issue-item" key={`${item.phaseText}:${index}`}>
            <div class="issue-phase">{item.phaseText}</div>
            <div>
              <strong>{item.messageText}</strong>
              {item.detailText ? <IssueDetail text={item.detailText} /> : null}
            </div>
          </li>
        ))}
      </ul>
    </MaintenanceCard>
  );
}

function UpdateLatestAttemptCard(props: {
  model: UpdateLatestAttemptSectionModel;
}) {
  const { model } = props;
  return (
    <MaintenanceCard
      badge={model.badge}
      subtitleText={model.subtitleText}
      titleText={model.titleText}
    >
      <StatusGrid rows={model.rows} />
      {model.failureNote ? (
        <div class="maintenance-note maintenance-note--bad">
          <strong>{model.failureNote.summaryText}</strong>
          {model.failureNote.detailText ? (
            <IssueDetail text={model.failureNote.detailText} />
          ) : null}
        </div>
      ) : null}
    </MaintenanceCard>
  );
}

function UpdateHealthCard(props: {
  model: UpdateHealthSectionModel;
}) {
  const { model } = props;
  return (
    <MaintenanceCard
      badge={model.badge}
      subtitleText={model.summaryText}
      titleText={model.titleText}
    >
      <StatusGrid rows={model.rows} />
    </MaintenanceCard>
  );
}

function UpdateLogCard(props: {
  model: UpdateLogSectionModel;
}) {
  const { model } = props;
  const logBody = model.lines.map((line) => `${line}\n`).join("");
  return (
    <MaintenanceCard
      subtitleText={model.subtitleText}
      titleText={model.titleText}
    >
      {model.emptyState ? (
        <InlineEmptyState emptyState={model.emptyState} />
      ) : (
        <>
          {model.noteText ? <MaintenanceNote text={model.noteText} /> : null}
          <pre class="log-pre">{logBody}</pre>
        </>
      )}
    </MaintenanceCard>
  );
}

function UpdateOverviewContent(props: {
  status: UpdateStatusPanelViewModel | null;
}) {
  const { status } = props;
  if (!status) {
    return null;
  }
  return (
    <div class="maintenance-pair-grid maintenance-pair-grid--summary">
      <UpdateCurrentStatusCard model={status.currentStatus} />
      <UpdateHealthCard model={status.health} />
    </div>
  );
}

function UpdateStatusContent(props: {
  status: UpdateStatusPanelViewModel | null;
}) {
  const { status } = props;
  if (!status) {
    return null;
  }
  return (
    <>
      <div class="maintenance-pair-grid maintenance-pair-grid--focus">
        <UpdateJourneyCard model={status.journey} />
        <UpdateLogCard model={status.log} />
      </div>
      {status.latestAttempt ? (
        <UpdateLatestAttemptCard model={status.latestAttempt} />
      ) : null}
      {status.issues ? <UpdateIssuesCard model={status.issues} /> : null}
    </>
  );
}

function UpdatePanel(props: {
  actions: ReadonlySignal<UpdatePanelActionHandlers | null>;
  model: ReadonlySignal<UpdatePanelRenderModel>;
}) {
  const titleText = useUiText("settings.update.title", "System Update");
  const hintText = useUiText(
    "settings.update.hint",
    "Use either temporary Wi-Fi credentials or an already-connected USB internet uplink to update from GitHub. The hotspot only pauses for the Wi-Fi path.",
  );
  const reconnectNote = useUiText(
    "settings.update.reconnect_note",
    "Note: The page may disconnect while the hotspot is down for the Wi-Fi path. It will reconnect automatically.",
  );
  const cancelLabel = useUiText("settings.update.cancel", "Cancel Update");
  const status = useComputed(() => props.model.value.status);
  const startButtonHidden = useComputed(() => props.model.value.startButtonHidden);
  const startButtonDisabled = useComputed(() => props.model.value.startButtonDisabled);
  const startButtonLabelText = useComputed(() => props.model.value.startButtonLabelText);
  const cancelButtonHidden = useComputed(() => props.model.value.cancelButtonHidden);
  const cancelButtonDisabled = useComputed(() => props.model.value.cancelButtonDisabled);
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <section class="maintenance-card maintenance-card--hero">
          <div class="maintenance-card__header">
            <div>
              <div class="maintenance-card__title">
                {titleText}
              </div>
              <div class="subtle">
                {hintText}
              </div>
            </div>
          </div>
          <div class="maintenance-card__body maintenance-card__body--hero">
            <div class="maintenance-note">
              {reconnectNote}
            </div>
            <div
              id="updateOverviewPanel"
              class="maintenance-stack maintenance-stack--tight"
              aria-live="polite"
            >
              <UpdateOverviewContent status={status.value} />
            </div>
            <div class="maintenance-action-row">
              <button
                type="button"
                id="updateStartBtn"
                class="btn btn--success"
                hidden={startButtonHidden}
                disabled={startButtonDisabled}
                onClick={() => props.actions.value?.onStart()}
              >
                {startButtonLabelText}
              </button>
              <button
                type="button"
                id="updateCancelBtn"
                class="btn btn--danger"
                hidden={cancelButtonHidden}
                disabled={cancelButtonDisabled}
                onClick={() => props.actions.value?.onCancel()}
              >
                {cancelLabel}
              </button>
            </div>
          </div>
        </section>

        <div
          id="updateStatusPanel"
          class="maintenance-stack maintenance-stack--tight"
          aria-live="polite"
        >
          <UpdateStatusContent status={status.value} />
        </div>
      </div>
    </div>
  );
}

export function mountUpdatePanel(host: HTMLElement): UpdatePanelView {
  const actions = signal<UpdatePanelActionHandlers | null>(null);
  const modelSource = signal<ReadonlySignal<UpdatePanelRenderModel> | null>(null);
  const model = computed<UpdatePanelRenderModel>(() => modelSource.value?.value ?? DEFAULT_UPDATE_PANEL_MODEL);
  render(<UpdatePanel actions={actions} model={model} />, host);

  return {
    bindActions(handlers) {
      actions.value = handlers;
    },
    bindModel(model) {
      modelSource.value = model;
    },
  };
}
