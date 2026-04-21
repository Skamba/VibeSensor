import type { LiveWsPayload } from "./contracts/ws_payload_types";
import {
  bindReplaceableTimerEffect,
  createReplaceableTimeout,
} from "./app/timer_cleanup";
import { batch, signal, type ReadonlySignal } from "./app/ui_signals";

export type WsUiState = "connecting" | "connected" | "reconnecting" | "stale" | "no_data";

export interface WsClientOptions {
  url: string;
  staleAfterMs?: number;
  reconnectDelayMs?: number;
  hasData?: (payload: unknown) => boolean;
}

export interface WsClient {
  readonly latestPayload: ReadonlySignal<unknown | null>;
  readonly uiState: ReadonlySignal<WsUiState>;
  connect(): void;
  close(): void;
  dispose(): void;
  send(payload: { client_id: string | null }): void;
}

function hasSpectraClients(payload: unknown): boolean {
  const record = payload && typeof payload === "object"
    ? (payload as Partial<LiveWsPayload>)
    : null;
  const clients = record?.spectra?.clients;
  return Boolean(clients && Object.keys(clients).length > 0);
}

export function createWsClient(options: WsClientOptions): WsClient {
  const resolvedOptions: Required<WsClientOptions> = {
    // 3s is too aggressive on weaker Pi + hotspot links and causes false stale flicker.
    staleAfterMs: 10000,
    reconnectDelayMs: 1200,
    hasData: hasSpectraClients,
    ...options,
  };

  let ws: WebSocket | null = null;
  const latestPayload = signal<unknown | null>(null);
  const uiState = signal<WsUiState>("connecting");
  const lastMessageAtMs = signal(0);
  const hasReceivedData = signal(false);
  const manuallyClosed = signal(false);
  const reconnectAttempt = signal(0);
  const reconnectDelayMs = signal<number | null>(null);
  const reconnectTimer = createReplaceableTimeout();
  const socketOpen = signal(false);
  const staleTimer = createReplaceableTimeout();
  const disposeReconnectLifecycle = bindReconnectLifecycle();
  const disposeStaleLifecycle = bindStaleLifecycle();
  let disposed = false;

  return {
    latestPayload,
    uiState,
    connect,
    close,
    dispose,
    send,
  };

  function connect(): void {
    if (disposed) {
      return;
    }
    batch(() => {
      manuallyClosed.value = false;
      reconnectDelayMs.value = null;
    });
    open("connecting");
  }

  function close(): void {
    batch(() => {
      manuallyClosed.value = true;
      reconnectDelayMs.value = null;
      socketOpen.value = false;
    });
    if (ws) {
      ws.close();
      ws = null;
    }
    reconnectTimer.clear();
    staleTimer.clear();
  }

  function dispose(): void {
    if (disposed) {
      return;
    }
    disposed = true;
    close();
    disposeReconnectLifecycle();
    disposeStaleLifecycle();
  }

  function send(payload: { client_id: string | null }): void {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  function open(initialState: WsUiState): void {
    batch(() => {
      commitState(initialState);
      hasReceivedData.value = false;
      lastMessageAtMs.value = 0;
      latestPayload.value = null;
      socketOpen.value = false;
    });
    ws = new WebSocket(resolvedOptions.url);

    ws.onopen = () => {
      batch(() => {
        socketOpen.value = true;
        commitState("no_data");
      });
    };

    ws.onmessage = (event) => {
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const receivedAt = Date.now();
      batch(() => {
        reconnectAttempt.value = 0;
        lastMessageAtMs.value = receivedAt;
        hasReceivedData.value = hasReceivedData.value || resolvedOptions.hasData(payload);
        commitState(hasReceivedData.value ? "connected" : "no_data");
        latestPayload.value = payload;
      });
    };

    ws.onclose = () => {
      batch(() => {
        ws = null;
        socketOpen.value = false;
        if (manuallyClosed.value) {
          return;
        }
        commitState("reconnecting");
        scheduleReconnect();
      });
    };

    ws.onerror = () => {
      // onclose handles reconnect transitions.
    };
  }

  function scheduleReconnect(): void {
    if (disposed) {
      return;
    }
    reconnectDelayMs.value = nextReconnectDelayMs();
  }

  function nextReconnectDelayMs(): number {
    const base = Math.max(250, resolvedOptions.reconnectDelayMs);
    const exp = Math.min(6, reconnectAttempt.value);
    const raw = Math.min(15000, base * (2 ** exp));
    const jitter = raw * 0.25 * Math.random();
    reconnectAttempt.value += 1;
    return Math.round(raw + jitter);
  }

  function bindReconnectLifecycle(): () => void {
    return bindReplaceableTimerEffect(reconnectTimer, () => {
      const pendingReconnectDelayMs = reconnectDelayMs.value;
      if (pendingReconnectDelayMs === null || manuallyClosed.value) {
        return null;
      }
      return {
        delayMs: pendingReconnectDelayMs,
        callback: () => {
          batch(() => {
            reconnectDelayMs.value = null;
          });
          open("reconnecting");
        },
      };
    });
  }

  function bindStaleLifecycle(): () => void {
    return bindReplaceableTimerEffect(staleTimer, () => {
      if (
        !socketOpen.value
        || manuallyClosed.value
        || !hasReceivedData.value
        || lastMessageAtMs.value <= 0
      ) {
        return null;
      }
      const elapsedMs = Date.now() - lastMessageAtMs.value;
      const remainingMs = resolvedOptions.staleAfterMs - elapsedMs;
      if (remainingMs <= 0) {
        setState("stale");
        return null;
      }
      return {
        delayMs: remainingMs,
        callback: () => {
          setState("stale");
        },
      };
    });
  }

  function setState(next: WsUiState): void {
    commitState(next);
  }

  function commitState(next: WsUiState): void {
    if (uiState.value === next) {
      return;
    }
    uiState.value = next;
  }
}
