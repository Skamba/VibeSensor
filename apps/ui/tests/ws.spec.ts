import { expect, test } from "@playwright/test";

import { createAppState, unwrapAppStateValue } from "../src/app/ui_app_state";
import { WsClient } from "../src/ws";
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

function installIntervalHarness() {
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  let intervalHandler: (() => void) | null = null;

  globalThis.setInterval = ((handler: TimerHandler) => {
    intervalHandler = handler as () => void;
    return 1 as unknown as ReturnType<typeof setInterval>;
  }) as typeof setInterval;

  globalThis.clearInterval = (() => {
    intervalHandler = null;
  }) as typeof clearInterval;

  return {
    tick(): void {
      if (!intervalHandler) {
        throw new Error("No interval handler installed");
      }
      intervalHandler();
    },
    restore(): void {
      globalThis.setInterval = originalSetInterval;
      globalThis.clearInterval = originalClearInterval;
    },
  };
}

test.describe("WsClient", () => {
  test.beforeEach(() => {
    installWindowGlobal();
    FakeWebSocket.reset();
  });

  test("writes websocket state and queued payloads into the transport slice", () => {
    const originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    try {
      const state = createAppState();
      const client = new WsClient({
        url: "ws://example.test/ws",
        transport: state.transport,
      });

      client.connect();

      const socket = FakeWebSocket.instances[0];
      expect(socket?.url).toBe("ws://example.test/ws");

      socket?.emitOpen();
      expect(state.transport.wsState).toBe("no_data");

      const payload = {
        spectra: {
          clients: {
            "client-1": {},
          },
        },
      };
      socket?.emitMessage(payload);

      expect(state.transport.wsState).toBe("connected");
      expect(state.transport.hasReceivedPayload).toBe(true);
      expect(unwrapAppStateValue(state.transport.pendingPayload)).toEqual(payload);

      client.close();
    } finally {
      globalThis.WebSocket = originalWebSocket;
    }
  });

  test("marks the transport stale after signal-backed message timing expires", () => {
    const originalWebSocket = globalThis.WebSocket;
    const originalDateNow = Date.now;
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    const interval = installIntervalHarness();
    let now = 1_000;
    Date.now = () => now;
    try {
      const state = createAppState();
      const client = new WsClient({
        url: "ws://example.test/ws",
        transport: state.transport,
        staleAfterMs: 10,
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

      expect(state.transport.wsState).toBe("connected");

      now += 25;
      interval.tick();

      expect(state.transport.wsState).toBe("stale");
      client.close();
    } finally {
      Date.now = originalDateNow;
      interval.restore();
      globalThis.WebSocket = originalWebSocket;
    }
  });
});
