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

export function inlineStateActionClass(
  variant: InlineStateActionVariant | undefined,
): string {
  switch (variant) {
    case "success":
      return "btn btn--success";
    case "muted":
      return "btn btn--muted";
    default:
      return "btn btn--primary";
  }
}
