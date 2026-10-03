import { signal } from "@preact/signals";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { poll } from "../src/poll";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("loads on activation, then every interval, and pauses while inactive", async () => {
  const active = signal(false);
  const seen: number[] = [];
  let calls = 0;
  const p = poll({
    active,
    intervalMs: 1000,
    load: async () => ++calls,
    onData: (value) => seen.push(value),
  });
  await vi.advanceTimersByTimeAsync(5000);
  expect(calls).toBe(0);

  active.value = true;
  await vi.advanceTimersByTimeAsync(0);
  expect(seen).toEqual([1]);
  await vi.advanceTimersByTimeAsync(1000);
  expect(seen).toEqual([1, 2]);

  active.value = false;
  await vi.advanceTimersByTimeAsync(5000);
  expect(seen).toEqual([1, 2]);
  p.stop();
});

test("derives the next interval from the last result", async () => {
  const active = signal(true);
  const results = ["running", "running", "idle", "idle"];
  const seen: string[] = [];
  const p = poll({
    active,
    intervalMs: (last) => (last === "running" ? 100 : 1000),
    load: async () => results.shift() ?? "idle",
    onData: (value) => seen.push(value),
  });
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(100);
  await vi.advanceTimersByTimeAsync(100);
  expect(seen).toEqual(["running", "running", "idle"]);
  await vi.advanceTimersByTimeAsync(500);
  expect(seen).toHaveLength(3);
  await vi.advanceTimersByTimeAsync(500);
  expect(seen).toHaveLength(4);
  p.stop();
});

test("delivers only the latest request when an older one resolves later", async () => {
  const active = signal(false);
  const requests = [deferred<string>(), deferred<string>()];
  let index = 0;
  const seen: string[] = [];
  const p = poll({
    active,
    intervalMs: 1000,
    load: () => requests[index++].promise,
    onData: (value) => seen.push(value),
  });
  const first = p.refresh();
  const second = p.refresh();
  requests[1].resolve("new");
  await second;
  requests[0].resolve("old");
  await first;
  expect(seen).toEqual(["new"]);
  p.stop();
});

test("reports errors and keeps polling", async () => {
  const active = signal(true);
  const errors: unknown[] = [];
  const seen: number[] = [];
  let calls = 0;
  const p = poll({
    active,
    intervalMs: 1000,
    load: async () => {
      calls += 1;
      if (calls === 1) {
        throw new Error("offline");
      }
      return calls;
    },
    onData: (value) => seen.push(value),
    onError: (error) => errors.push(error),
  });
  await vi.advanceTimersByTimeAsync(0);
  expect(errors).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(1000);
  expect(seen).toEqual([2]);
  p.stop();
});

test("refresh loads immediately even while inactive", async () => {
  const active = signal(false);
  const seen: string[] = [];
  const p = poll({
    active,
    intervalMs: 1000,
    load: async () => "now",
    onData: (value) => seen.push(value),
  });
  await p.refresh();
  expect(seen).toEqual(["now"]);
  await vi.advanceTimersByTimeAsync(5000);
  expect(seen).toEqual(["now"]);
  p.stop();
});
