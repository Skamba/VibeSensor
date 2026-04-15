import { h, type ComponentChildren } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { useUiTranslation } from "../ui_i18n";
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
} from "./update_status_view_models";

export interface UpdatePanelDom {
  updateOverviewPanel: HTMLElement | null;
  updateStartBtn: HTMLButtonElement;
  updateCancelBtn: HTMLButtonElement;
  updateStatusPanel: HTMLElement;
}

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
  readonly dom: UpdatePanelDom;
  bindActions(handlers: UpdatePanelActionHandlers): void;
  render(model: UpdatePanelRenderModel): void;
}

type UpdatePanelBridgeState = {
  actions: UpdatePanelActionHandlers | null;
  model: UpdatePanelRenderModel;
};

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
  state: UpdatePanelBridgeState;
}) {
  const { state } = props;
  const { model } = state;
  const t = useUiTranslation();
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <section class="maintenance-card maintenance-card--hero">
          <div class="maintenance-card__header">
            <div>
              <div class="maintenance-card__title">
                {t("settings.update.title", "System Update")}
              </div>
              <div class="subtle">
                {t(
                  "settings.update.hint",
                  "Use either temporary Wi-Fi credentials or an already-connected USB internet uplink to update from GitHub. The hotspot only pauses for the Wi-Fi path.",
                )}
              </div>
            </div>
          </div>
          <div class="maintenance-card__body maintenance-card__body--hero">
            <div class="maintenance-note">
              {t(
                "settings.update.reconnect_note",
                "Note: The page may disconnect while the hotspot is down for the Wi-Fi path. It will reconnect automatically.",
              )}
            </div>
            <div
              id="updateOverviewPanel"
              class="maintenance-stack maintenance-stack--tight"
              aria-live="polite"
            >
              <UpdateOverviewContent status={model.status} />
            </div>
            <div class="maintenance-action-row">
              <button
                type="button"
                id="updateStartBtn"
                class="btn btn--success"
                hidden={model.startButtonHidden}
                disabled={model.startButtonDisabled}
                onClick={() => state.actions?.onStart()}
              >
                {model.startButtonLabelText}
              </button>
              <button
                type="button"
                id="updateCancelBtn"
                class="btn btn--danger"
                hidden={model.cancelButtonHidden}
                disabled={model.cancelButtonDisabled}
                onClick={() => state.actions?.onCancel()}
              >
                {t("settings.update.cancel", "Cancel Update")}
              </button>
            </div>
          </div>
        </section>

        <div
          id="updateStatusPanel"
          class="maintenance-stack maintenance-stack--tight"
          aria-live="polite"
        >
          <UpdateStatusContent status={model.status} />
        </div>
      </div>
    </div>
  );
}

function requiredInHost<T extends Element>(
  host: ParentNode,
  selector: string,
): T {
  const element = host.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Update feature requires ${selector}`);
  }
  return element;
}

function createUpdatePanelDom(host: HTMLElement): UpdatePanelDom {
  return {
    updateOverviewPanel: host.querySelector<HTMLElement>("#updateOverviewPanel"),
    updateStartBtn: requiredInHost<HTMLButtonElement>(host, "#updateStartBtn"),
    updateCancelBtn: requiredInHost<HTMLButtonElement>(host, "#updateCancelBtn"),
    updateStatusPanel: requiredInHost<HTMLElement>(host, "#updateStatusPanel"),
  };
}

export function mountUpdatePanel(host: HTMLElement): UpdatePanelView {
  let state: UpdatePanelBridgeState = {
    actions: null,
    model: DEFAULT_UPDATE_PANEL_MODEL,
  };
  const mount = createUiPreactMount(host);

  function render(): void {
    mount.render(<UpdatePanel state={state} />);
  }

  render();

  return {
    dom: createUpdatePanelDom(host),
    bindActions(handlers) {
      state = { ...state, actions: handlers };
      render();
    },
    render(model) {
      state = { ...state, model };
      render();
    },
  };
}
