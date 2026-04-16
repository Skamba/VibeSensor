import { computed, signal, type ReadonlySignal } from "../ui_signals";

export interface UiConfirmationDialogModel {
  cancelButtonText: string;
  confirmButtonText: string;
  messageText: string;
  titleText: string;
}

interface PendingConfirmationRequest {
  message: string;
  resolve: (result: boolean) => void;
}

export interface UiConfirmationModule {
  readonly dialogModel: ReadonlySignal<UiConfirmationDialogModel | null>;
  requestConfirmation(message: string): Promise<boolean>;
  confirm(): void;
  cancel(): void;
}

export function createUiConfirmationModule(deps: {
  t: (key: string, vars?: Record<string, unknown>) => string;
}): UiConfirmationModule {
  const queue: PendingConfirmationRequest[] = [];
  const currentMessage = signal<string | null>(null);
  let currentResolver: ((result: boolean) => void) | null = null;

  function advanceQueue(): void {
    if (currentResolver !== null) {
      return;
    }
    const next = queue.shift();
    if (!next) {
      currentMessage.value = null;
      return;
    }
    currentMessage.value = next.message;
    currentResolver = next.resolve;
  }

  function settle(result: boolean): void {
    if (currentResolver === null) {
      return;
    }
    const resolve = currentResolver;
    currentResolver = null;
    currentMessage.value = null;
    resolve(result);
    advanceQueue();
  }

  return {
    dialogModel: computed(() => {
      const messageText = currentMessage.value;
      if (messageText === null) {
        return null;
      }
      return {
        cancelButtonText: deps.t("actions.cancel"),
        confirmButtonText: deps.t("actions.confirm"),
        messageText,
        titleText: deps.t("actions.confirm_title"),
      };
    }),
    requestConfirmation(message: string): Promise<boolean> {
      return new Promise<boolean>((resolve) => {
        queue.push({ message, resolve });
        advanceQueue();
      });
    },
    confirm(): void {
      settle(true);
    },
    cancel(): void {
      settle(false);
    },
  };
}
