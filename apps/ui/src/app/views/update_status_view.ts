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
import type { UpdateStatusPanelViewModel } from "./update_status_view_models";

export function syncUpdateControls(
  els: {
    updateStartBtn: HTMLButtonElement;
    updateCancelBtn: HTMLButtonElement | null;
    updateSsidInput: HTMLInputElement | null;
    updatePasswordInput: HTMLInputElement | null;
  },
  status: { state: string },
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
  viewModel: UpdateStatusPanelViewModel,
): void {
  renderChildren(
    panel,
    createElementNode("div", {
      className: "maintenance-pair-grid maintenance-pair-grid--focus",
      children: [
        createUpdateJourneyCard(viewModel.journey),
        createUpdateLogCard(viewModel.log),
      ],
    }),
    viewModel.latestAttempt ? createUpdateLatestAttemptCard(viewModel.latestAttempt) : null,
    viewModel.issues ? createUpdateIssuesCard(viewModel.issues) : null,
  );
}

export function renderUpdateOverviewPanel(
  panel: HTMLElement | null,
  viewModel: UpdateStatusPanelViewModel,
): void {
  if (!panel) {
    return;
  }
  renderChildren(
    panel,
    createElementNode("div", {
      className: "maintenance-pair-grid maintenance-pair-grid--summary",
      children: [
        createUpdateCurrentStatusCard(viewModel.currentStatus),
        createUpdateHealthCard(viewModel.health),
      ],
    }),
  );
}
