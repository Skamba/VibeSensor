import type { HealthStatusPayload, UpdateStatusPayload } from "../../api/types";
import { buildUpdateJourneySectionModel } from "./update_journey_builder";
import {
  buildUpdateCurrentStatusSectionModel,
  buildUpdateIssuesSectionModel,
  buildUpdateLatestAttemptSectionModel,
} from "./update_current_status_builders";
import { buildUpdateHealthSectionModel } from "./update_health_status_builders";
import { buildUpdateLogSectionModel } from "./update_log_status_builder";
import type {
  UpdateStatusPanelViewModel,
  UpdateStatusViewDeps,
} from "./update_status_models";

export { buildUpdateCurrentStatusSectionModel } from "./update_current_status_builders";
export { buildUpdateLogSectionModel } from "./update_log_status_builder";

export function buildUpdateStatusPanelViewModel(
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateStatusPanelViewModel {
  return {
    currentStatus: buildUpdateCurrentStatusSectionModel(status, health, deps),
    journey: buildUpdateJourneySectionModel(status, deps),
    issues: buildUpdateIssuesSectionModel(status, deps),
    latestAttempt: buildUpdateLatestAttemptSectionModel(status, deps),
    health: buildUpdateHealthSectionModel(health, deps),
    log: buildUpdateLogSectionModel(status, deps),
  };
}
