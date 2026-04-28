export interface UiLogger {
  error(message: string, error?: unknown): void;
  warn(message: string, error?: unknown): void;
}

export const uiLogger: UiLogger = {
  error(message, error) {
    if (typeof error === "undefined") {
      console.error(message);
      return;
    }
    console.error(message, error);
  },
  warn(message, error) {
    if (typeof error === "undefined") {
      console.warn(message);
      return;
    }
    console.warn(message, error);
  },
};
