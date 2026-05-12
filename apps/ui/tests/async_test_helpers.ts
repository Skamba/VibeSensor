import { expect } from "vitest";

export type TimerHarness = {
  pendingDelays(): number[];
  restore(): void;
};

export type Deferred<T> = {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(reason?: unknown): void;
};

export function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

export function installWindowGlobal(): void {
  (globalThis as { window?: Window & typeof globalThis }).window =
    globalThis as unknown as Window & typeof globalThis;
}

export function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

export function installTimerHarness(): TimerHarness {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  let nextId = 1;
  const active = new Map<number, number>();

  globalThis.setTimeout = ((handler: TimerHandler, delay?: number) => {
    const id = nextId;
    nextId += 1;
    active.set(id, Number(delay ?? 0));
    void handler;
    return id as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;

  globalThis.clearTimeout = ((timeoutId?: ReturnType<typeof setTimeout>) => {
    if (typeof timeoutId !== "number") return;
    active.delete(timeoutId);
  }) as typeof clearTimeout;

  return {
    pendingDelays(): number[] {
      return Array.from(active.values()).sort((left, right) => left - right);
    },
    restore(): void {
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    },
  };
}

export async function flushAsyncWork(rounds = 12): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise<void>((resolve) => {
      setImmediate(() => resolve());
    });
  }
}

export async function flushSignalUpdates(rounds = 12): Promise<void> {
  await flushAsyncWork(rounds);
}

export async function resolveAfterDisposal<T>(options: {
  dispose(): void;
  resolve(value: T): void;
  start(): Promise<unknown>;
  value: T;
}): Promise<void> {
  const pending = options.start();
  await flushAsyncWork();
  options.dispose();
  options.resolve(options.value);
  await pending;
  await flushAsyncWork();
}

export async function expectSingleInFlightOperation<T>(options: {
  callCount(): number;
  resolve(value: T): void;
  start(): Promise<unknown>;
  value: T;
}): Promise<void> {
  const first = options.start();
  const second = options.start();
  await flushAsyncWork();

  expect(options.callCount()).toBe(1);
  options.resolve(options.value);
  await Promise.all([first, second]);
  await flushAsyncWork();
}
