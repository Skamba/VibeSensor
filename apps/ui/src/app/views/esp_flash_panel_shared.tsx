import type { Signal } from "../ui_signals";
import type { VisualVariant } from "../visual_variant";
import {
  type MaintenanceReadinessPanelModel,
} from "./maintenance_readiness_view";
import { type DeferredModelSignal } from "./view_model_binding";

export interface EspFlashStatusBadgeModel {
  text: string;
  variant: VisualVariant;
}

export interface EspFlashStatusGridRowModel {
  labelText: string;
  valueText: string;
}

export interface EspFlashPortOptionModel {
  labelText: string;
  value: string;
}

export type EspFlashJourneyStageState =
  | "active"
  | "attention"
  | "done"
  | "upcoming";

export interface EspFlashJourneyStageModel {
  current: boolean;
  detailText: string;
  markerText: string;
  phase: string;
  state: EspFlashJourneyStageState;
  stateText: string;
  titleText: string;
}

export interface EspFlashJourneyPanelModel {
  stages: readonly EspFlashJourneyStageModel[];
  terminalNoteText: string | null;
}

export interface EspFlashEmptyStateModel {
  bodyText: string;
  titleText: string;
}

export interface EspFlashHistoryAttemptModel {
  badge: EspFlashStatusBadgeModel;
  errorText: string | null;
  metaText: string;
  portText: string;
}

export interface EspFlashHistoryPanelModel {
  attempts: readonly EspFlashHistoryAttemptModel[];
  emptyState: EspFlashEmptyStateModel | null;
}

export interface EspFlashLogPanelModel {
  emptyState: EspFlashEmptyStateModel | null;
  text: string;
}

export interface EspFlashReadinessPanelModel {
  errorText: string | null;
  rows: readonly EspFlashStatusGridRowModel[];
  summaryText: string;
}

export interface EspFlashPanelRenderModel {
  cancelButtonDisabled: boolean;
  cancelButtonHidden: boolean;
  history: EspFlashHistoryPanelModel;
  journey: EspFlashJourneyPanelModel;
  log: EspFlashLogPanelModel;
  portOptions: readonly EspFlashPortOptionModel[];
  portSelectDisabled: boolean;
  readiness: EspFlashReadinessPanelModel;
  refreshPortsDisabled: boolean;
  selectedPortValue: string;
  startButtonDisabled: boolean;
  startButtonHidden: boolean;
  startButtonLabelText: string;
  startSummary: MaintenanceReadinessPanelModel;
  statusBanner: EspFlashStatusBadgeModel;
}

export interface EspFlashPanelActionHandlers {
  onCancel(): void;
  onRefreshPorts(): void;
  onSelectPort(value: string): void;
  onStart(): void;
}

export interface EspFlashPanelView {
  actions: Signal<EspFlashPanelActionHandlers | null>;
  model: DeferredModelSignal<EspFlashPanelRenderModel>;
}

export const DEFAULT_ESP_FLASH_PANEL_MODEL: EspFlashPanelRenderModel = {
  cancelButtonDisabled: true,
  cancelButtonHidden: true,
  history: {
    attempts: [],
    emptyState: null,
  },
  journey: {
    stages: [],
    terminalNoteText: null,
  },
  log: {
    emptyState: null,
    text: "",
  },
  portOptions: [
    {
      labelText: "Auto-detect",
      value: "__auto__",
    },
  ],
  portSelectDisabled: false,
  readiness: {
    errorText: null,
    rows: [],
    summaryText: "",
  },
  refreshPortsDisabled: false,
  selectedPortValue: "__auto__",
  startButtonDisabled: true,
  startButtonHidden: false,
  startButtonLabelText: "Flash latest",
  startSummary: {
    items: [],
    stateLabel: "",
    stateVariant: "muted",
    summary: "",
    title: "",
  },
  statusBanner: {
    text: "Idle",
    variant: "muted",
  },
};

export function StatusBadge(props: {
  badge: EspFlashStatusBadgeModel;
}) {
  const { badge } = props;
  return (
    <span class="pill" data-variant={badge.variant}>
      {badge.text}
    </span>
  );
}

export function StatusGrid(props: {
  rows: readonly EspFlashStatusGridRowModel[];
}) {
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

export function MaintenanceNote(props: {
  text: string;
  variant?: "bad";
}) {
  const className = props.variant
    ? `maintenance-note maintenance-note--${props.variant}`
    : "maintenance-note";
  return <div class={className}>{props.text}</div>;
}

export function InlineEmptyState(props: {
  model: EspFlashEmptyStateModel;
}) {
  const { model } = props;
  return (
    <div class="empty-state empty-state--inline">
      <strong class="empty-state__title">{model.titleText}</strong>
      <span class="empty-state__body">{model.bodyText}</span>
    </div>
  );
}
