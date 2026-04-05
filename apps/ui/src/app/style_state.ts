export type VisualVariant = "bad" | "muted" | "ok" | "warn";

export type ChoiceCardState = "active" | "draft" | "error";

function setAttributeState(
  element: Element | null,
  name: string,
  value: string | null | undefined,
): void {
  if (!element) {
    return;
  }
  if (!value) {
    element.removeAttribute(name);
    return;
  }
  element.setAttribute(name, value);
}

function setBooleanDataState(
  element: Element | null,
  name: string,
  enabled: boolean,
): void {
  setAttributeState(element, `data-${name}`, enabled ? "true" : null);
}

export function setVariantState(
  element: Element | null,
  variant: VisualVariant | null,
): void {
  setAttributeState(element, "data-variant", variant);
}

export function setChoiceCardState(
  element: Element | null,
  options: {
    selected?: boolean;
    disabled?: boolean;
    state?: ChoiceCardState | null;
    badgeText?: string | null;
  },
): void {
  if (!element) {
    return;
  }
  setBooleanDataState(element, "selected", options.selected === true);
  setBooleanDataState(element, "disabled", options.disabled === true);
  setAttributeState(element, "data-choice-state", options.state ?? null);
  setAttributeState(element, "data-choice-badge", options.badgeText ?? null);
}
