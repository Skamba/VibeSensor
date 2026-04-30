import { effect } from "./ui_signals";

type TimeoutApi = Pick<typeof globalThis, "clearTimeout" | "setTimeout">;
type IntervalApi = Pick<typeof globalThis, "clearInterval" | "setInterval">;

type ScheduledHandleStore<Handle> = {
  clear(): void;
  release(): void;
  replace(nextHandle: Handle): void;
};

export interface ReplaceableTimer {
  clear(): void;
  replace(callback: () => void, delayMs: number): void;
}

export interface ReplaceableTimerEffectSchedule {
  callback: () => void;
  delayMs: number;
  fireImmediately?: boolean;
}

function createScheduledHandleStore<Handle>(
  clearHandle: (handle: Handle) => void,
): ScheduledHandleStore<Handle> {
  let handle: Handle | null = null;

  return {
    clear(): void {
      if (handle === null) {
        return;
      }
      clearHandle(handle);
      handle = null;
    },
    release(): void {
      handle = null;
    },
    replace(nextHandle: Handle): void {
      if (handle !== null) {
        clearHandle(handle);
      }
      handle = nextHandle;
    },
  };
}

export function createReplaceableTimeout(
  api: TimeoutApi = globalThis,
): ReplaceableTimer {
  const store = createScheduledHandleStore<ReturnType<typeof setTimeout>>(
    (handle) => api.clearTimeout(handle),
  );

  return {
    clear(): void {
      store.clear();
    },
    replace(callback: () => void, delayMs: number): void {
      store.replace(
        api.setTimeout(() => {
          store.release();
          callback();
        }, delayMs),
      );
    },
  };
}

export function createReplaceableInterval(
  api: IntervalApi = globalThis,
): ReplaceableTimer {
  const store = createScheduledHandleStore<ReturnType<typeof setInterval>>(
    (handle) => api.clearInterval(handle),
  );

  return {
    clear(): void {
      store.clear();
    },
    replace(callback: () => void, delayMs: number): void {
      store.replace(api.setInterval(callback, delayMs));
    },
  };
}

export function bindReplaceableTimerEffect(
  timer: ReplaceableTimer,
  resolveSchedule: () => ReplaceableTimerEffectSchedule | null,
): () => void {
  return effect(() => {
    const schedule = resolveSchedule();
    if (schedule === null) {
      timer.clear();
      return;
    }
    if (schedule.fireImmediately) {
      schedule.callback();
    }
    timer.replace(schedule.callback, schedule.delayMs);
    return () => {
      timer.clear();
    };
  });
}
