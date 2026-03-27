export function renderTableEmptyRow(
  textHtml: string,
  colspan: number,
): string {
  return `<tr><td colspan="${colspan}">${textHtml}</td></tr>`;
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
