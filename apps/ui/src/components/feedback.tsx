/** Inline save/validation feedback shared by the shell and settings pages. */
export interface Feedback {
  body: string;
  detail?: string;
  title?: string;
  tone?: "info" | "error";
  compact?: boolean;
}

function liveness(message: Feedback | null): "assertive" | "polite" {
  return message?.tone === "error" ? "assertive" : "polite";
}

export function FeedbackBlock(props: { message: Feedback; live?: boolean }) {
  const { message } = props;
  return (
    <div
      class="settings-feedback"
      data-tone={message.tone ?? "info"}
      data-compact={message.compact ? "true" : undefined}
      aria-live={props.live ? liveness(message) : undefined}
    >
      {message.title ? (
        <strong class="settings-feedback__title">{message.title}</strong>
      ) : null}
      <span class="settings-feedback__body">{message.body}</span>
      {message.detail ? (
        <span class="settings-feedback__detail">{message.detail}</span>
      ) : null}
    </div>
  );
}

export function FeedbackSlot(props: {
  id: string;
  message: Feedback | null;
  compact?: boolean;
}) {
  const { id, message } = props;
  return (
    <div
      id={id}
      class={
        props.compact
          ? "settings-feedback-slot settings-feedback-slot--compact"
          : "settings-feedback-slot"
      }
      hidden={message === null}
      aria-live={liveness(message)}
    >
      {message ? <FeedbackBlock message={message} /> : null}
    </div>
  );
}
