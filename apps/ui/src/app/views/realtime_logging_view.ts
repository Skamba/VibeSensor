import { createElementNode, renderChildren, setNodeText } from "./dom_render";
import { createInlineStatePanelElement } from "./dom_helpers";
import type {
  RealtimeCaptureReadinessChecklistItemModel,
  RealtimeCaptureReadinessChecklistModel,
  RealtimeLoggingSummaryPanelModel,
} from "./realtime_logging_view_models";

export function createRealtimeLoggingSummarySignature(
  summaryText: string,
  summaryPanel: RealtimeLoggingSummaryPanelModel | null,
): string {
  if (summaryPanel === null) {
    return `text:${summaryText}`;
  }
  const actionSignature = summaryPanel.action
    ? `${summaryPanel.action.action}|${summaryPanel.action.labelText}|${summaryPanel.action.variant ?? ""}`
    : "";
  return `panel:${summaryPanel.titleText}|${summaryPanel.bodyText}|${summaryPanel.detailText ?? ""}|${actionSignature}`;
}

export function renderRealtimeLoggingSummary(
  container: HTMLElement | null,
  summaryText: string,
  summaryPanel: RealtimeLoggingSummaryPanelModel | null,
  previousSignature: string | null,
): string | null {
  if (!container) {
    return previousSignature;
  }
  const nextSignature = createRealtimeLoggingSummarySignature(summaryText, summaryPanel);
  container.hidden = summaryText === "" && summaryPanel === null;
  if (nextSignature !== previousSignature) {
    if (summaryPanel) {
      renderChildren(container, createInlineStatePanelElement(summaryPanel));
    } else {
      setNodeText(container, summaryText);
    }
  }
  container.classList.toggle("logging-summary--panel", summaryPanel !== null);
  return nextSignature;
}

function createChecklistItemElement(
  item: RealtimeCaptureReadinessChecklistItemModel,
): HTMLDivElement {
  return createElementNode("div", {
    className: `capture-readiness__item capture-readiness__item--${item.state}`,
    children: [
      createElementNode("div", {
        className: "capture-readiness__row",
        children: [
          createElementNode("span", {
            className: "capture-readiness__label",
            text: item.labelText,
          }),
          createElementNode("span", {
            className: "capture-readiness__state",
            text: item.stateText,
          }),
        ],
      }),
      createElementNode("div", {
        className: "capture-readiness__detail",
        text: item.detailText,
      }),
    ],
  });
}

export function renderRealtimeCaptureReadinessChecklist(
  container: HTMLElement | null,
  checklist: RealtimeCaptureReadinessChecklistModel | null,
): void {
  if (!container) {
    return;
  }
  container.hidden = checklist === null;
  if (checklist === null) {
    renderChildren(container);
    return;
  }
  renderChildren(
    container,
    createElementNode("div", {
      className: "capture-readiness__title",
      text: checklist.titleText,
    }),
    createElementNode("div", {
      className: "capture-readiness__list",
      children: checklist.items.map((item) => createChecklistItemElement(item)),
    }),
  );
}
