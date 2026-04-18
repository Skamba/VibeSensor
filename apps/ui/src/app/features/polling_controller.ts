import { effect, signal, type ReadonlySignal } from "../ui_signals";
import { createReplaceableTimeout } from "../timer_cleanup";

export interface PollingController {
  dispose(): void;
  start(): void;
  stop(): void;
  restart(): void;
}

export interface PollingControllerOptions {
  enabled?: ReadonlySignal<boolean>;
  poll: () => Promise<number>;
  onError?: (error: unknown) => void;
  onErrorDelayMs: number;
}

export function createPollingController(
  options: PollingControllerOptions,
): PollingController {
  const { enabled, poll, onErrorDelayMs } = options;
  const onError = options.onError ?? ((error: unknown) => {
    if (typeof window !== "undefined") {
      console.warn("Polling task failed", error);
    }
  });

  const pollTimer = createReplaceableTimeout();
  let pollGeneration = 0;
  const pollingActive = signal(false);
  let disposeEnabledSync: (() => void) | null = null;
  let disposed = false;

  function schedulePoll(delayMs: number, generation: number): void {
    if (disposed || !pollingActive.value || generation !== pollGeneration) return;
    pollTimer.replace(() => {
      void runPoll(generation);
    }, delayMs);
  }

  async function runPoll(generation: number = pollGeneration): Promise<void> {
    if (disposed) {
      return;
    }
    try {
      const delayMs = await poll();
      schedulePoll(delayMs, generation);
    } catch (error) {
      onError(error);
      schedulePoll(onErrorDelayMs, generation);
    }
  }

  function restart(): void {
    if (disposed || !pollingActive.value) return;
    pollGeneration += 1;
    pollTimer.clear();
    void runPoll(pollGeneration);
  }

  function start(): void {
    if (disposed || pollingActive.value) return;
    pollingActive.value = true;
    restart();
  }

  function stop(): void {
    if (!pollingActive.value) return;
    pollingActive.value = false;
    pollGeneration += 1;
    pollTimer.clear();
  }

  function dispose(): void {
    if (disposed) {
      return;
    }
    disposed = true;
    stop();
    disposeEnabledSync?.();
    disposeEnabledSync = null;
  }

  if (enabled) {
    disposeEnabledSync = effect(() => {
      if (enabled.value) {
        start();
        return;
      }
      stop();
    });
  }

  return {
    dispose,
    start,
    stop,
    restart,
  };
}
