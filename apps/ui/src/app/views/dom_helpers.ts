import {
  createElementNode,
  renderChildren,
  setClassStates,
  type RenderChild,
} from "./dom_render";

export function renderTableEmptyRow(
  textHtml: string,
  colspan: number,
): string {
  return `<tr><td colspan="${colspan}">${textHtml}</td></tr>`;
}

export type InlineStateActionVariant = "primary" | "success" | "muted";

export interface InlineStateAction {
  action: string;
  labelHtml: string;
  variant?: InlineStateActionVariant;
}

export interface InlineStatePanel {
  titleHtml: string;
  bodyHtml: string;
  detailHtml?: string;
  action?: InlineStateAction;
}

export interface InlineStatePanelElement {
  titleText: string;
  bodyText: string;
  detailText?: string;
  action?: {
    action: string;
    labelText: string;
    variant?: InlineStateActionVariant;
  };
}

export function inlineStateActionClass(variant: InlineStateActionVariant | undefined): string {
  switch (variant) {
    case "success":
      return "btn btn--success";
    case "muted":
      return "btn btn--muted";
    default:
      return "btn btn--primary";
  }
}

export function renderInlineStatePanel(panel: InlineStatePanel): string {
  const detailHtml = panel.detailHtml
    ? `<span class="empty-state__detail">${panel.detailHtml}</span>`
    : "";
  const actionHtml = panel.action
    ? `
      <div class="empty-state__actions">
        <button
          type="button"
          class="${inlineStateActionClass(panel.action.variant)}"
          data-inline-state-action="${panel.action.action}"
        >${panel.action.labelHtml}</button>
      </div>
    `
    : "";
  return `
    <div class="empty-state empty-state--inline empty-state--actionable">
      <strong class="empty-state__title">${panel.titleHtml}</strong>
      <span class="empty-state__body">${panel.bodyHtml}</span>
      ${detailHtml}
      ${actionHtml}
    </div>
  `;
}

export function createTableEmptyRowElement(
  content: RenderChild,
  colspan: number,
): HTMLTableRowElement {
  return createElementNode("tr", {
    children: [
      createElementNode("td", {
        attrs: { colspan },
        children: [content],
      }),
    ],
  });
}

export function createInlineStatePanelElement(
  panel: InlineStatePanelElement,
): HTMLDivElement {
  const root = createElementNode("div", {
    classes: ["empty-state", "empty-state--inline"],
  });
  setClassStates(root, {
    "empty-state--actionable": panel.action != null,
  });
  const children: RenderChild[] = [
    createElementNode("strong", {
      className: "empty-state__title",
      text: panel.titleText,
    }),
    createElementNode("span", {
      className: "empty-state__body",
      text: panel.bodyText,
    }),
  ];
  if (panel.detailText) {
    children.push(createElementNode("span", {
      className: "empty-state__detail",
      text: panel.detailText,
    }));
  }
  if (panel.action) {
    children.push(createElementNode("div", {
      className: "empty-state__actions",
      children: [
        createElementNode("button", {
          className: inlineStateActionClass(panel.action.variant),
          attrs: { type: "button" },
          data: { inlineStateAction: panel.action.action },
          text: panel.action.labelText,
        }),
      ],
    }));
  }
  renderChildren(root, children);
  return root;
}

export function closestFromTarget<T extends Element>(
  target: EventTarget | null,
  selector: string,
): T | null {
  if (!(target instanceof Element)) {
    return null;
  }
  return target.closest<T>(selector);
}

export function getInlineStateAction(target: EventTarget | null): string | null {
  return closestFromTarget<HTMLElement>(target, "[data-inline-state-action]")
    ?.getAttribute("data-inline-state-action") ?? null;
}

export function getTypedInlineStateAction<const TAction extends string>(
  target: EventTarget | null,
  allowedActions: readonly TAction[],
): TAction | null {
  const action = getInlineStateAction(target);
  if (!action) {
    return null;
  }
  return allowedActions.find((allowedAction) => allowedAction === action) ?? null;
}

export function formatEpochTimestamp(epoch: number | null | undefined): string {
  if (epoch === null || epoch === undefined || !Number.isFinite(epoch)) {
    return "—";
  }
  return new Date(epoch * 1000).toLocaleString();
}

export function renderStatusGridRow(
  labelHtml: string,
  valueHtml: string,
): string {
  return `<div class="status-grid__row"><span class="status-grid__label">${labelHtml}</span><span>${valueHtml}</span></div>`;
}

export function createStatusGridRowElement(
  labelText: string,
  valueText: string,
): HTMLDivElement {
  return createElementNode("div", {
    className: "status-grid__row",
    children: [
      createElementNode("span", {
        className: "status-grid__label",
        text: labelText,
      }),
      createElementNode("span", {
        text: valueText,
      }),
    ],
  });
}
