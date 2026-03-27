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

export function renderStatusGridRow(
  labelHtml: string,
  valueHtml: string,
): string {
  return `<div class="update-status-row"><span class="update-label">${labelHtml}</span><span>${valueHtml}</span></div>`;
}
