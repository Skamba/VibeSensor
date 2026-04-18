import { render, type ComponentChildren } from "preact";

import { getUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import { type DeferredModelSignal } from "./view_model_binding";
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

const UPDATE_PANEL_MODEL_KEYS = [
  "cancelButtonDisabled",
  "cancelButtonHidden",
  "startButtonDisabled",
  "startButtonHidden",
  "startButtonLabelText",
  "status",
] as const;
const UPDATE_STATUS_BADGE_KEYS = ["text", "variant"] as const;
const UPDATE_CURRENT_STATUS_KEYS = [
  "badge",
  "emptyText",
  "rows",
  "summaryText",
  "titleText",
] as const;
const UPDATE_JOURNEY_KEYS = ["failureNote", "stages", "subtitleText", "titleText"] as const;
const UPDATE_ISSUES_KEYS = ["items", "subtitleText", "titleText"] as const;
const UPDATE_LATEST_ATTEMPT_KEYS = [
  "badge",
  "failureNote",
  "rows",
  "subtitleText",
  "titleText",
] as const;
const UPDATE_HEALTH_KEYS = ["badge", "rows", "summaryText", "titleText"] as const;
const UPDATE_LOG_KEYS = ["emptyState", "lines", "noteText", "subtitleText", "titleText"] as const;

export interface UpdatePanelView {
  actions: Signal<UpdatePanelActionHandlers | null>;
  model: DeferredModelSignal<UpdatePanelRenderModel>;
}

const DEFAULT_UPDATE_PANEL_MODEL: UpdatePanelRenderModel = {
  cancelButtonDisabled: true,
  cancelButtonHidden: true,
  startButtonDisabled: true,
  startButtonHidden: false,
  startButtonLabelText: "Start Update",
  status: null,
};

const DEFAULT_UPDATE_BADGE_MODEL: UpdateStatusBadgeModel = {
  text: "",
  variant: "muted",
};

const DEFAULT_UPDATE_CURRENT_STATUS_SECTION_MODEL: UpdateCurrentStatusSectionModel = {
  badge: DEFAULT_UPDATE_BADGE_MODEL,
  emptyText: null,
  rows: [],
  summaryText: "",
  titleText: "",
};

const DEFAULT_UPDATE_JOURNEY_SECTION_MODEL: UpdateJourneySectionModel = {
  failureNote: null,
  stages: [],
  subtitleText: "",
  titleText: "",
};

const DEFAULT_UPDATE_ISSUES_SECTION_MODEL: UpdateIssuesSectionModel = {
  items: [],
  subtitleText: "",
  titleText: "",
};

const DEFAULT_UPDATE_LATEST_ATTEMPT_SECTION_MODEL: UpdateLatestAttemptSectionModel = {
  badge: DEFAULT_UPDATE_BADGE_MODEL,
  failureNote: null,
  rows: [],
  subtitleText: "",
  titleText: "",
};

const DEFAULT_UPDATE_HEALTH_SECTION_MODEL: UpdateHealthSectionModel = {
  badge: DEFAULT_UPDATE_BADGE_MODEL,
  rows: [],
  summaryText: "",
  titleText: "",
};

const DEFAULT_UPDATE_LOG_SECTION_MODEL: UpdateLogSectionModel = {
  emptyState: null,
  lines: [],
  noteText: null,
  subtitleText: "",
  titleText: "",
};

function UpdateBadge(props: { badge: ReadonlySignal<UpdateStatusBadgeModel> }) {
  const { text, variant } = useSignalProperties(props.badge, UPDATE_STATUS_BADGE_KEYS);
  return (
    <span class="pill" data-variant={variant.value}>
      {text.value}
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
  badge?: ComponentChildren;
  children: ComponentChildren;
  subtitleText: string;
  titleText: string;
}) {
  const { children, subtitleText, titleText } = props;
  return (
    <section class="maintenance-card">
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">{titleText}</div>
          <div class="subtle">{subtitleText}</div>
        </div>
        {props.badge ?? null}
      </div>
      <div class="maintenance-card__body">{children}</div>
    </section>
  );
}

function UpdateCurrentStatusCard(props: {
  model: ReadonlySignal<UpdateCurrentStatusSectionModel | null>;
}) {
  const hasModel = useComputed(() => props.model.value !== null);
  const model = useComputed(
    () => props.model.value ?? DEFAULT_UPDATE_CURRENT_STATUS_SECTION_MODEL,
  );
  const { badge, emptyText, rows, summaryText, titleText } = useSignalProperties(
    model,
    UPDATE_CURRENT_STATUS_KEYS,
  );
  if (!hasModel.value) {
    return null;
  }
  return (
    <MaintenanceCard
      badge={<UpdateBadge badge={badge} />}
      subtitleText={summaryText.value}
      titleText={titleText.value}
    >
      {rows.value.length > 0 ? (
        <StatusGrid rows={rows.value} />
      ) : (
        <MaintenanceNote text={emptyText.value ?? ""} />
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
  model: ReadonlySignal<UpdateJourneySectionModel | null>;
}) {
  const hasModel = useComputed(() => props.model.value !== null);
  const model = useComputed(() => props.model.value ?? DEFAULT_UPDATE_JOURNEY_SECTION_MODEL);
  const { failureNote, stages, subtitleText, titleText } = useSignalProperties(
    model,
    UPDATE_JOURNEY_KEYS,
  );
  if (!hasModel.value) {
    return null;
  }
  return (
    <MaintenanceCard
      subtitleText={subtitleText.value}
      titleText={titleText.value}
    >
      <div class="maintenance-journey">
        {failureNote.value ? (
          <JourneyFailureStack failure={failureNote.value} />
        ) : null}
        <ol class="maintenance-stage-list">
          {stages.value.map((stage) => (
            <JourneyStageItem key={stage.phase} stage={stage} />
          ))}
        </ol>
      </div>
    </MaintenanceCard>
  );
}

function UpdateIssuesCard(props: {
  model: ReadonlySignal<UpdateIssuesSectionModel | null>;
}) {
  const hasModel = useComputed(() => props.model.value !== null);
  const model = useComputed(() => props.model.value ?? DEFAULT_UPDATE_ISSUES_SECTION_MODEL);
  const { items, subtitleText, titleText } = useSignalProperties(model, UPDATE_ISSUES_KEYS);
  if (!hasModel.value) {
    return null;
  }
  return (
    <MaintenanceCard
      subtitleText={subtitleText.value}
      titleText={titleText.value}
    >
      <ul class="issue-list">
        {items.value.map((item, index) => (
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
  model: ReadonlySignal<UpdateLatestAttemptSectionModel | null>;
}) {
  const hasModel = useComputed(() => props.model.value !== null);
  const model = useComputed(
    () => props.model.value ?? DEFAULT_UPDATE_LATEST_ATTEMPT_SECTION_MODEL,
  );
  const { badge, failureNote, rows, subtitleText, titleText } = useSignalProperties(
    model,
    UPDATE_LATEST_ATTEMPT_KEYS,
  );
  if (!hasModel.value) {
    return null;
  }
  return (
    <MaintenanceCard
      badge={<UpdateBadge badge={badge} />}
      subtitleText={subtitleText.value}
      titleText={titleText.value}
    >
      <StatusGrid rows={rows.value} />
      {failureNote.value ? (
        <div class="maintenance-note maintenance-note--bad">
          <strong>{failureNote.value.summaryText}</strong>
          {failureNote.value.detailText ? (
            <IssueDetail text={failureNote.value.detailText} />
          ) : null}
        </div>
      ) : null}
    </MaintenanceCard>
  );
}

function UpdateHealthCard(props: {
  model: ReadonlySignal<UpdateHealthSectionModel | null>;
}) {
  const hasModel = useComputed(() => props.model.value !== null);
  const model = useComputed(() => props.model.value ?? DEFAULT_UPDATE_HEALTH_SECTION_MODEL);
  const { badge, rows, summaryText, titleText } = useSignalProperties(
    model,
    UPDATE_HEALTH_KEYS,
  );
  if (!hasModel.value) {
    return null;
  }
  return (
    <MaintenanceCard
      badge={<UpdateBadge badge={badge} />}
      subtitleText={summaryText.value}
      titleText={titleText.value}
    >
      <StatusGrid rows={rows.value} />
    </MaintenanceCard>
  );
}

function UpdateLogCard(props: {
  model: ReadonlySignal<UpdateLogSectionModel | null>;
}) {
  const hasModel = useComputed(() => props.model.value !== null);
  const model = useComputed(() => props.model.value ?? DEFAULT_UPDATE_LOG_SECTION_MODEL);
  const { emptyState, lines, noteText, subtitleText, titleText } = useSignalProperties(
    model,
    UPDATE_LOG_KEYS,
  );
  const logBody = useComputed(() => lines.value.map((line) => `${line}\n`).join(""));
  if (!hasModel.value) {
    return null;
  }
  return (
    <MaintenanceCard
      subtitleText={subtitleText.value}
      titleText={titleText.value}
    >
      {emptyState.value ? (
        <InlineEmptyState emptyState={emptyState.value} />
      ) : (
        <>
          {noteText.value ? <MaintenanceNote text={noteText.value} /> : null}
          <pre class="log-pre">{logBody.value}</pre>
        </>
      )}
    </MaintenanceCard>
  );
}

function UpdateOverviewContent(props: {
  status: ReadonlySignal<UpdateStatusPanelViewModel | null>;
}) {
  const hasStatus = useComputed(() => props.status.value !== null);
  const currentStatus = useComputed(() => props.status.value?.currentStatus ?? null);
  const health = useComputed(() => props.status.value?.health ?? null);
  if (!hasStatus.value) {
    return null;
  }
  return (
    <div class="maintenance-pair-grid maintenance-pair-grid--summary">
      <UpdateCurrentStatusCard model={currentStatus} />
      <UpdateHealthCard model={health} />
    </div>
  );
}

function UpdateStatusContent(props: {
  status: ReadonlySignal<UpdateStatusPanelViewModel | null>;
}) {
  const hasStatus = useComputed(() => props.status.value !== null);
  const journey = useComputed(() => props.status.value?.journey ?? null);
  const log = useComputed(() => props.status.value?.log ?? null);
  const latestAttempt = useComputed(() => props.status.value?.latestAttempt ?? null);
  const issues = useComputed(() => props.status.value?.issues ?? null);
  if (!hasStatus.value) {
    return null;
  }
  return (
    <>
      <div class="maintenance-pair-grid maintenance-pair-grid--focus">
        <UpdateJourneyCard model={journey} />
        <UpdateLogCard model={log} />
      </div>
      <UpdateLatestAttemptCard model={latestAttempt} />
      <UpdateIssuesCard model={issues} />
    </>
  );
}

function UpdateActionRow(props: {
  actions: ReadonlySignal<UpdatePanelActionHandlers | null>;
  cancelButtonDisabled: ReadonlySignal<boolean>;
  cancelButtonHidden: ReadonlySignal<boolean>;
  cancelLabel: string;
  startButtonDisabled: ReadonlySignal<boolean>;
  startButtonHidden: ReadonlySignal<boolean>;
  startButtonLabelText: ReadonlySignal<string>;
}) {
  const handleStart = () => {
    props.actions.value?.onStart();
  };
  const handleCancel = () => {
    props.actions.value?.onCancel();
  };
  return (
    <div class="maintenance-action-row">
      <button
        type="button"
        id="updateStartBtn"
        class="btn btn--success"
        hidden={props.startButtonHidden.value}
        disabled={props.startButtonDisabled.value}
        onClick={handleStart}
      >
        {props.startButtonLabelText.value}
      </button>
      <button
        type="button"
        id="updateCancelBtn"
        class="btn btn--danger"
        hidden={props.cancelButtonHidden.value}
        disabled={props.cancelButtonDisabled.value}
        onClick={handleCancel}
      >
        {props.cancelLabel}
      </button>
    </div>
  );
}

function UpdatePanel(props: {
  actions: ReadonlySignal<UpdatePanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<UpdatePanelRenderModel> | null>;
}) {
  const actions = useComputed(() => props.actions.value);
  const labels = useComputed(() => ({
    cancelLabel: getUiText("settings.update.cancel", "Cancel Update"),
    hintText: getUiText(
      "settings.update.hint",
      "Use either temporary Wi-Fi credentials or an already-connected USB internet uplink to update from GitHub. The hotspot only pauses for the Wi-Fi path.",
    ),
    reconnectNote: getUiText(
      "settings.update.reconnect_note",
      "Note: The page may disconnect while the hotspot is down for the Wi-Fi path. It will reconnect automatically.",
    ),
    titleText: getUiText("settings.update.title", "System Update"),
  }));
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_UPDATE_PANEL_MODEL);
  const {
    cancelButtonDisabled,
    cancelButtonHidden,
    startButtonDisabled,
    startButtonHidden,
    startButtonLabelText,
    status,
  } = useSignalProperties(model, UPDATE_PANEL_MODEL_KEYS);
  const labelTexts = labels.value;
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <section class="maintenance-card maintenance-card--hero">
          <div class="maintenance-card__header">
            <div>
                <div class="maintenance-card__title">
                 {labelTexts.titleText}
                </div>
                <div class="subtle">
                 {labelTexts.hintText}
                </div>
            </div>
          </div>
          <div class="maintenance-card__body maintenance-card__body--hero">
            <div class="maintenance-note">
              {labelTexts.reconnectNote}
            </div>
            <div
              id="updateOverviewPanel"
              class="maintenance-stack maintenance-stack--tight"
              aria-live="polite"
            >
              <UpdateOverviewContent status={status} />
            </div>
            <UpdateActionRow
              actions={actions}
              cancelButtonDisabled={cancelButtonDisabled}
              cancelButtonHidden={cancelButtonHidden}
              cancelLabel={labelTexts.cancelLabel}
              startButtonDisabled={startButtonDisabled}
              startButtonHidden={startButtonHidden}
              startButtonLabelText={startButtonLabelText}
            />
          </div>
        </section>

        <div
          id="updateStatusPanel"
          class="maintenance-stack maintenance-stack--tight"
          aria-live="polite"
        >
          <UpdateStatusContent status={status} />
        </div>
      </div>
    </div>
  );
}

export function mountUpdatePanel(host: HTMLElement, view: UpdatePanelView): void {
  render(<UpdatePanel actions={view.actions} model={view.model} />, host);
}
