export type SettingsFeedbackTone = "info" | "error";

export interface SettingsFeedbackMessage {
  body: string;
  detail?: string;
  title?: string;
  tone?: SettingsFeedbackTone;
  compact?: boolean;
}

function appendTextElement(
  documentRef: Document,
  parent: HTMLElement,
  tagName: "span" | "strong",
  className: string,
  text: string | undefined,
): void {
  const trimmedText = text?.trim();
  if (!trimmedText) {
    return;
  }
  const element = documentRef.createElement(tagName);
  element.className = className;
  element.textContent = trimmedText;
  parent.append(element);
}

function feedbackClassName(message: SettingsFeedbackMessage): string {
  const tone = message.tone ?? "info";
  const classNames = ["settings-feedback", `settings-feedback--${tone}`];
  if (message.compact) {
    classNames.push("settings-feedback--compact");
  }
  return classNames.join(" ");
}

export function createSettingsFeedbackElement(
  documentRef: Document,
  message: SettingsFeedbackMessage,
): HTMLDivElement {
  const root = documentRef.createElement("div");
  root.className = feedbackClassName(message);
  appendTextElement(
    documentRef,
    root,
    "strong",
    "settings-feedback__title",
    message.title,
  );
  appendTextElement(
    documentRef,
    root,
    "span",
    "settings-feedback__body",
    message.body,
  );
  appendTextElement(
    documentRef,
    root,
    "span",
    "settings-feedback__detail",
    message.detail,
  );
  return root;
}

export function setSettingsFeedback(
  slot: HTMLElement | null,
  message: SettingsFeedbackMessage | null,
): void {
  if (!slot) {
    return;
  }
  if (!message) {
    slot.hidden = true;
    slot.replaceChildren();
    slot.removeAttribute("aria-live");
    return;
  }
  slot.hidden = false;
  slot.setAttribute("aria-live", message.tone === "error" ? "assertive" : "polite");
  slot.replaceChildren(createSettingsFeedbackElement(slot.ownerDocument, message));
}
