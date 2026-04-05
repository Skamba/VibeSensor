import { createInlineStatePanelElement, createStatusGridRowElement } from "./dom_helpers";
import { createElementNode, type RenderChild } from "./dom_render";
import type {
  UpdateLogEmptyStateModel,
  UpdateStatusBadgeModel,
  UpdateStatusRowModel,
} from "./update_status_view_models";

interface MaintenanceCardElementOptions {
  titleText: string;
  subtitleText: string;
  bodyChildren: readonly RenderChild[];
  badge?: UpdateStatusBadgeModel | null;
}

export function createUpdateBadgeElement(
  badge: UpdateStatusBadgeModel,
): HTMLSpanElement {
  return createElementNode("span", {
    className: `pill pill--${badge.variant}`,
    text: badge.text,
  });
}

export function createMaintenanceCardElement(
  options: MaintenanceCardElementOptions,
): HTMLElement {
  return createElementNode("section", {
    className: "maintenance-card",
    children: [
      createElementNode("div", {
        className: "maintenance-card__header",
        children: [
          createElementNode("div", {
            children: [
              createElementNode("div", {
                className: "maintenance-card__title",
                text: options.titleText,
              }),
              createElementNode("div", {
                className: "subtle",
                text: options.subtitleText,
              }),
            ],
          }),
          options.badge ? createUpdateBadgeElement(options.badge) : null,
        ],
      }),
      createElementNode("div", {
        className: "maintenance-card__body",
        children: options.bodyChildren,
      }),
    ],
  });
}

export function createStatusGridElement(
  rows: readonly UpdateStatusRowModel[],
): HTMLDivElement {
  return createElementNode("div", {
    className: "status-grid",
    children: rows.map((row) => createStatusGridRowElement(row.labelText, row.valueText)),
  });
}

export function createIssueDetailElement(text: string): HTMLDivElement {
  return createElementNode("div", {
    className: "issue-detail",
    text,
  });
}

export function createMaintenanceNoteElement(
  text: string,
  variant: "bad" | null = null,
): HTMLDivElement {
  return createElementNode("div", {
    classes: ["maintenance-note", variant ? `maintenance-note--${variant}` : null],
    text,
  });
}

export function createInlineEmptyStateElement(
  emptyState: UpdateLogEmptyStateModel,
): HTMLDivElement {
  return createInlineStatePanelElement({
    titleText: emptyState.titleText,
    bodyText: emptyState.bodyText,
  });
}
