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

function inlineStateActionClass(variant: InlineStateActionVariant | undefined): string {
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
