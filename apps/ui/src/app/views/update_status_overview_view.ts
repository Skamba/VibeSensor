import { createElementNode } from "./dom_render";
import {
  createIssueDetailElement,
  createMaintenanceCardElement,
  createMaintenanceNoteElement,
  createStatusGridElement,
} from "./update_status_section_helpers";
import type {
  UpdateCurrentStatusSectionModel,
  UpdateJourneyFailureNoteModel,
  UpdateJourneySectionModel,
  UpdateJourneyStageModel,
} from "./update_status_view_models";

function createJourneyFailureStackElement(
  failure: UpdateJourneyFailureNoteModel,
): HTMLDivElement {
  return createElementNode("div", {
    classes: ["maintenance-stack", "maintenance-stack--tight"],
    children: [
      createElementNode("div", {
        classes: ["maintenance-note", "maintenance-note--bad"],
        children: [
          createElementNode("strong", {
            text: failure.summaryText,
          }),
          failure.detailText ? createIssueDetailElement(failure.detailText) : null,
        ],
      }),
      createElementNode("div", {
        className: "maintenance-note",
        children: [
          createElementNode("strong", {
            text: failure.recoveryTitleText,
          }),
          createIssueDetailElement(failure.recoveryDetailText),
        ],
      }),
    ],
  });
}

function createJourneyStageElement(
  stage: UpdateJourneyStageModel,
): HTMLLIElement {
  return createElementNode("li", {
    className: `maintenance-stage maintenance-stage--${stage.state}`,
    attrs: {
      "data-stage-phase": stage.phase,
      "data-stage-state": stage.state,
      "aria-current": stage.current ? "step" : null,
    },
    children: [
      createElementNode("span", {
        className: "maintenance-stage__marker",
        text: stage.markerText,
      }),
      createElementNode("div", {
        className: "maintenance-stage__body",
        children: [
          createElementNode("div", {
            className: "maintenance-stage__title",
            text: stage.titleText,
          }),
          createElementNode("div", {
            className: "maintenance-stage__detail",
            text: stage.detailText,
          }),
        ],
      }),
      createElementNode("span", {
        className: "maintenance-stage__state",
        text: stage.stateText,
      }),
    ],
  });
}

export function createUpdateCurrentStatusCard(
  model: UpdateCurrentStatusSectionModel,
): HTMLElement {
  return createMaintenanceCardElement({
    titleText: model.titleText,
    subtitleText: model.summaryText,
    badge: model.badge,
    bodyChildren: model.rows.length > 0
      ? [createStatusGridElement(model.rows)]
      : [createMaintenanceNoteElement(model.emptyText ?? "")],
  });
}

export function createUpdateJourneyCard(
  model: UpdateJourneySectionModel,
): HTMLElement {
  return createMaintenanceCardElement({
    titleText: model.titleText,
    subtitleText: model.subtitleText,
    bodyChildren: [
      createElementNode("div", {
        className: "maintenance-journey",
        children: [
          model.failureNote ? createJourneyFailureStackElement(model.failureNote) : null,
          createElementNode("ol", {
            className: "maintenance-stage-list",
            children: model.stages.map((stage) => createJourneyStageElement(stage)),
          }),
        ],
      }),
    ],
  });
}
