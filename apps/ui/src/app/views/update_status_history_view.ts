import { createElementNode } from "./dom_render";
import {
  createIssueDetailElement,
  createMaintenanceCardElement,
  createStatusGridElement,
} from "./update_status_section_helpers";
import type {
  UpdateIssueSectionItemModel,
  UpdateIssuesSectionModel,
  UpdateLatestAttemptSectionModel,
} from "./update_status_view_models";

function createIssueItemElement(
  item: UpdateIssueSectionItemModel,
): HTMLLIElement {
  return createElementNode("li", {
    className: "issue-item",
    children: [
      createElementNode("div", {
        className: "issue-phase",
        text: item.phaseText,
      }),
      createElementNode("div", {
        children: [
          createElementNode("strong", {
            text: item.messageText,
          }),
          item.detailText ? createIssueDetailElement(item.detailText) : null,
        ],
      }),
    ],
  });
}

export function createUpdateIssuesCard(
  model: UpdateIssuesSectionModel,
): HTMLElement {
  return createMaintenanceCardElement({
    titleText: model.titleText,
    subtitleText: model.subtitleText,
    bodyChildren: [
      createElementNode("ul", {
        className: "issue-list",
        children: model.items.map((item) => createIssueItemElement(item)),
      }),
    ],
  });
}

export function createUpdateLatestAttemptCard(
  model: UpdateLatestAttemptSectionModel,
): HTMLElement {
  return createMaintenanceCardElement({
    titleText: model.titleText,
    subtitleText: model.subtitleText,
    badge: model.badge,
    bodyChildren: [
      createStatusGridElement(model.rows),
      model.failureNote
        ? createElementNode("div", {
            classes: ["maintenance-note", "maintenance-note--bad"],
            children: [
              createElementNode("strong", {
                text: model.failureNote.summaryText,
              }),
              model.failureNote.detailText
                ? createIssueDetailElement(model.failureNote.detailText)
                : null,
            ],
          })
        : null,
    ],
  });
}
