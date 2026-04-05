import type {
  HealthStatusPayload,
  UpdateStatusPayload,
} from "../../transport/http_models";
import { createElementNode, renderChildren } from "./dom_render";
import { createUpdateHealthCard } from "./update_status_health_view";
import {
  createUpdateIssuesCard,
  createUpdateLatestAttemptCard,
} from "./update_status_history_view";
import { createUpdateLogCard } from "./update_status_log_view";
import {
  createUpdateCurrentStatusCard,
  createUpdateJourneyCard,
} from "./update_status_overview_view";
import {
  buildUpdateStatusPanelViewModel,
  type UpdateStatusViewDeps,
} from "./update_status_view_models";

export { getUpdateFailureSummary } from "./update_status_view_models";
export type { UpdateStatusViewDeps } from "./update_status_view_models";

export function syncUpdateControls(
  els: {
    updateStartBtn: HTMLButtonElement;
    updateCancelBtn: HTMLButtonElement | null;
    updateSsidInput: HTMLInputElement | null;
    updatePasswordInput: HTMLInputElement | null;
  },
  status: UpdateStatusPayload,
): void {
  const isRunning = status.state === "running";
  els.updateStartBtn.hidden = isRunning;
  els.updateStartBtn.disabled = isRunning;
  if (els.updateCancelBtn) {
    els.updateCancelBtn.hidden = !isRunning;
  }
  if (els.updateSsidInput) els.updateSsidInput.disabled = isRunning;
  if (els.updatePasswordInput) els.updatePasswordInput.disabled = isRunning;
}

export function renderUpdateStatusPanel(
  panel: HTMLElement,
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): void {
  const viewModel = buildUpdateStatusPanelViewModel(status, health, deps);
  renderChildren(
    panel,
    createElementNode("div", {
      className: "maintenance-pair-grid",
      children: [
        createUpdateCurrentStatusCard(viewModel.currentStatus),
        createUpdateJourneyCard(viewModel.journey),
      ],
    }),
    viewModel.issues ? createUpdateIssuesCard(viewModel.issues) : null,
    viewModel.latestAttempt ? createUpdateLatestAttemptCard(viewModel.latestAttempt) : null,
    createUpdateHealthCard(viewModel.health),
    createUpdateLogCard(viewModel.log),
  );
}
