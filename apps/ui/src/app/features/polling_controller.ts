import { effect, type ReadonlySignal } from "../ui_signals";

export interface PollingController {
  start(): void;
  stop(): void;
  restart(): void;
}

export interface PollingControllerOptions {
  enabled?: ReadonlySignal<boolean>;
  poll: () => Promise<number>;
  onErrorDelayMs: number;
}

export function createPollingController(
  options: PollingControllerOptions,
): PollingController {
  const { enabled, poll, onErrorDelayMs } = options;

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollGeneration = 0;
  let pollingActive = false;

  function clearPollTimer(): void {
    if (pollTimer === null) return;
    clearTimeout(pollTimer);
    pollTimer = null;
  }

  function schedulePoll(delayMs: number, generation: number): void {
    if (!pollingActive || generation !== pollGeneration) return;
    clearPollTimer();
    pollTimer = setTimeout(() => void runPoll(generation), delayMs);
  }

  async function runPoll(generation: number = pollGeneration): Promise<void> {
    try {
      const delayMs = await poll();
      schedulePoll(delayMs, generation);
    } catch {
      schedulePoll(onErrorDelayMs, generation);
    }
  }

  function restart(): void {
    if (!pollingActive) return;
    pollGeneration += 1;
    clearPollTimer();
    void runPoll(pollGeneration);
  }

  function start(): void {
    if (pollingActive) return;
    pollingActive = true;
    restart();
  }

  function stop(): void {
    if (!pollingActive && pollTimer === null) return;
    pollingActive = false;
    pollGeneration += 1;
    clearPollTimer();
  }

  if (enabled) {
    effect(() => {
      if (enabled.value) {
        start();
        return;
      }
      stop();
    });
  }

  return {
    start,
    stop,
    restart,
  };
}
