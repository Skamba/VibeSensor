import type { UpdateStartRequestPayload } from "../../api/types";

export type JourneyStageState = "upcoming" | "active" | "done" | "attention";
export type UpdateJourneyTransport = UpdateStartRequestPayload["transport"];
export type UpdateStatusBadgeVariant = "muted" | "warn" | "ok" | "bad";

export interface UpdateStatusViewDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  selectedTransport: UpdateJourneyTransport;
}

export interface UpdateFailureSummary {
  detail: string | null;
  message: string | null;
  phaseLabel: string;
  recoveryDetail: string;
  recoveryTitle: string;
}

export interface UpdateStatusBadgeModel {
  variant: UpdateStatusBadgeVariant;
  text: string;
}

export interface UpdateStatusRowModel {
  labelText: string;
  valueText: string;
}

export interface UpdateCurrentStatusSectionModel {
  titleText: string;
  summaryText: string;
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
  emptyText: string | null;
}

export interface UpdateJourneyFailureNoteModel {
  summaryText: string;
  detailText: string | null;
  recoveryTitleText: string;
  recoveryDetailText: string;
}

export interface UpdateJourneyStageModel {
  phase: string;
  titleText: string;
  detailText: string;
  markerText: string;
  state: JourneyStageState;
  stateText: string;
  current: boolean;
}

export interface UpdateJourneySectionModel {
  titleText: string;
  subtitleText: string;
  failureNote: UpdateJourneyFailureNoteModel | null;
  stages: readonly UpdateJourneyStageModel[];
}

export interface UpdateIssueSectionItemModel {
  phaseText: string;
  messageText: string;
  detailText: string | null;
}

export interface UpdateIssuesSectionModel {
  titleText: string;
  subtitleText: string;
  items: readonly UpdateIssueSectionItemModel[];
}

export interface UpdateLatestAttemptFailureNoteModel {
  summaryText: string;
  detailText: string | null;
}

export interface UpdateLatestAttemptSectionModel {
  titleText: string;
  subtitleText: string;
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
  failureNote: UpdateLatestAttemptFailureNoteModel | null;
}

export interface UpdateHealthSectionModel {
  titleText: string;
  summaryText: string;
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
}

export interface UpdateLogEmptyStateModel {
  titleText: string;
  bodyText: string;
}

export interface UpdateLogSectionModel {
  titleText: string;
  subtitleText: string;
  noteText: string | null;
  lines: readonly string[];
  emptyState: UpdateLogEmptyStateModel | null;
}

export interface UpdateStatusPanelViewModel {
  currentStatus: UpdateCurrentStatusSectionModel;
  journey: UpdateJourneySectionModel;
  issues: UpdateIssuesSectionModel | null;
  latestAttempt: UpdateLatestAttemptSectionModel | null;
  health: UpdateHealthSectionModel;
  log: UpdateLogSectionModel;
}
