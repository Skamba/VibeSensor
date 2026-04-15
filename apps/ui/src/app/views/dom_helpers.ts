export type InlineStateActionVariant = "primary" | "success" | "muted";

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
