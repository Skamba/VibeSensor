import { beforeEach, describe, expect, test } from "vitest";
import { createAppState } from "../src/app/ui_app_state";
import { batch } from "../src/app/ui_signals";
import { createWsClient } from "../src/ws";
import { installWindowGlobal } from "./async_test_helpers";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: FakeWebSocket[] = [];

  readonly url: string;

  readyState = FakeWebSocket.CONNECTING;

  onopen: WebSocket["onopen"] = null;

  onmessage: WebSocket["onmessage"] = null;

  onclose: WebSocket["onclose"] = null;

  onerror: WebSocket["onerror"] = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  static reset(): void {
    FakeWebSocket.instances = [];
  }

  send(): void {}

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new Event("close") as CloseEvent);
  }

  emitOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  emitMessage(payload: unknown): void {
    this.onmessage?.({
      data: JSON.stringify(payload),
    } as MessageEvent);
  }
}

function installTimeoutHarness() {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  let nextId = 1;
  const callbacks = new Map<number, { callback: () => void; delayMs: number }>();

  globalThis.setTimeout = ((handler: TimerHandler, delay?: number) => {
    const timeoutId = nextId;
    nextId += 1;
    callbacks.set(timeoutId, {
      callback: handler as () => void,
      delayMs: Number(delay ?? 0),
    });
    return timeoutId as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;

  globalThis.clearTimeout = ((timeoutId?: ReturnType<typeof setTimeout>) => {
    if (typeof timeoutId !== "number") {
      return;
    }
    callbacks.delete(timeoutId);
  }) as typeof clearTimeout;

  return {
    pendingTimeoutCount(): number {
      return callbacks.size;
    },
    pendingDelays(): number[] {
      return [...callbacks.values()].map((entry) => entry.delayMs);
    },
    fireNext(): void {
      const next = callbacks.entries().next();
      if (next.done) {
        throw new Error("No timeout callback installed");
      }
      const [timeoutId, entry] = next.value;
      callbacks.delete(timeoutId);
      entry.callback();
    },
    restore(): void {
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    },
  };
}

describe("createWsClient", () => {
  beforeEach(() => {
    installWindowGlobal();
    FakeWebSocket.reset();
  });

  test("exposes signal state and forwards queued payloads through onMessage", () => {
    const originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    try {
      const state = createAppState();
      const client = createWsClient({
        url: "ws://example.test/ws",
        onMessage: (payload) => {
          batch(() => {
            state.transport.hasReceivedPayload.value = true;
            state.transport.pendingPayload.value = payload;
          });
        },
      });

      client.connect();

      const socket = FakeWebSocket.instances[0];
      expect(socket?.url).toBe("ws://example.test/ws");

      socket?.emitOpen();
      expect(client.uiState.value).toBe("no_data");

      const payload = {
        spectra: {
          clients: {
            "client-1": {},
          },
        },
      };
      socket?.emitMessage(payload);

      expect(client.uiState.value).toBe("connected");
      expect(state.transport.hasReceivedPayload.value).toBe(true);
      expect(state.transport.pendingPayload.value).toEqual(payload);

      client.close();
    } finally {
      globalThis.WebSocket = originalWebSocket;
    }
  });

  test("marks the transport stale after signal-backed message timing expires", () => {
    const originalWebSocket = globalThis.WebSocket;
    const originalDateNow = Date.now;
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    const timeouts = installTimeoutHarness();
    let now = 1_000;
    Date.now = () => now;
    try {
      const client = createWsClient({
        url: "ws://example.test/ws",
        staleAfterMs: 10,
        onMessage: () => undefined,
      });

      client.connect();

      const socket = FakeWebSocket.instances[0];
      socket?.emitOpen();
      socket?.emitMessage({
        spectra: {
          clients: {
            "client-1": {},
          },
        },
      });

      expect(client.uiState.value).toBe("connected");
      expect(timeouts.pendingTimeoutCount()).toBe(1);
      expect(timeouts.pendingDelays()).toEqual([10]);

      now += 5;
      socket?.emitMessage({
        spectra: {
          clients: {
            "client-1": {},
          },
        },
      });

      expect(client.uiState.value).toBe("connected");
      expect(timeouts.pendingTimeoutCount()).toBe(1);
      expect(timeouts.pendingDelays()).toEqual([10]);

      now += 25;
      timeouts.fireNext();

      expect(client.uiState.value).toBe("stale");
      client.close();
    } finally {
      Date.now = originalDateNow;
      timeouts.restore();
      globalThis.WebSocket = originalWebSocket;
    }
  });

  test("schedules reconnect through the signal-driven timeout lifecycle", () => {
    const originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    const timeouts = installTimeoutHarness();
    try {
      const client = createWsClient({
        url: "ws://example.test/ws",
        onMessage: () => undefined,
      });

      client.connect();
      const socket = FakeWebSocket.instances[0];
      socket?.emitOpen();
      socket?.close();

      expect(client.uiState.value).toBe("reconnecting");
      expect(timeouts.pendingTimeoutCount()).toBe(1);

      timeouts.fireNext();

      expect(FakeWebSocket.instances).toHaveLength(2);
      expect(FakeWebSocket.instances[1]?.url).toBe("ws://example.test/ws");

      client.close();
    } finally {
      timeouts.restore();
      globalThis.WebSocket = originalWebSocket;
    }
  });

  test("dispose clears reconnect timers and leaves no active timeout lifecycle", () => {
    const originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    const timeouts = installTimeoutHarness();
    try {
      const client = createWsClient({
        url: "ws://example.test/ws",
        onMessage: () => undefined,
      });

      client.connect();
      const socket = FakeWebSocket.instances[0];
      socket?.emitOpen();
      socket?.close();

      expect(client.uiState.value).toBe("reconnecting");
      expect(timeouts.pendingTimeoutCount()).toBe(1);

      client.dispose();
      expect(timeouts.pendingTimeoutCount()).toBe(0);
    } finally {
      timeouts.restore();
      globalThis.WebSocket = originalWebSocket;
    }
  });
});
