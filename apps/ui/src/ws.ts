import type { LiveWsPayload } from "./contracts/ws_payload_types";
import {
  bindReplaceableTimerEffect,
  createReplaceableTimeout,
} from "./timer_cleanup";
import { batch, type ReadonlySignal, signal } from "@preact/signals";

export type WsUiState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "stale"
  | "no_data";

interface WsClientOptions {
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

/**
 * Coming back to the page after this long without a message reconnects at
 * once: a phone that slept or backgrounded the tab often keeps a socket that
 * looks open but is dead, and the server pushes several messages a second.
 */
const RESUME_QUIET_MS = 3000;

function hasSpectraClients(payload: unknown): boolean {
  const record =
    payload && typeof payload === "object"
      ? (payload as Partial<LiveWsPayload>)
      : null;
  const clients = record?.spectra?.clients;
  return Boolean(clients && Object.keys(clients).length > 0);
}

/**
 * Live socket that reconnects by itself: after a close (with backoff), when an
 * open socket goes quiet for `staleAfterMs` (the server pushes several times a
 * second, so silence means a dead link), and at once when the page becomes
 * visible again with the socket gone or quiet.
 */
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
  const openedAtMs = signal(0);
  const hasReceivedData = signal(false);
  const manuallyClosed = signal(false);
  const reconnectAttempt = signal(0);
  const reconnectDelayMs = signal<number | null>(null);
  const reconnectTimer = createReplaceableTimeout();
  const socketOpen = signal(false);
  const staleTimer = createReplaceableTimeout();
  const disposeReconnectLifecycle = bindReconnectLifecycle();
  const disposeStaleLifecycle = bindStaleLifecycle();
  const disposeVisibilityListener = bindVisibilityListener();
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
    if (
      ws &&
      (ws.readyState === WebSocket.CONNECTING ||
        ws.readyState === WebSocket.OPEN)
    ) {
      return;
    }
    open("connecting");
  }

  function close(): void {
    batch(() => {
      manuallyClosed.value = true;
      reconnectDelayMs.value = null;
      socketOpen.value = false;
    });
    const socket = ws;
    ws = null;
    if (socket) {
      socket.close();
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
    disposeVisibilityListener();
  }

  function send(payload: { client_id: string | null }): void {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  function open(initialState: WsUiState): void {
    reconnectTimer.clear();
    staleTimer.clear();
    if (ws) {
      const previousSocket = ws;
      ws = null;
      previousSocket.close();
    }
    batch(() => {
      commitState(initialState);
      hasReceivedData.value = false;
      lastMessageAtMs.value = 0;
      latestPayload.value = null;
      socketOpen.value = false;
    });
    const socket = new WebSocket(resolvedOptions.url);
    ws = socket;

    socket.onopen = () => {
      if (ws !== socket) {
        return;
      }
      batch(() => {
        openedAtMs.value = Date.now();
        socketOpen.value = true;
        commitState("no_data");
      });
    };

    socket.onmessage = (event) => {
      if (ws !== socket) {
        return;
      }
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const receivedAt = Date.now();
      batch(() => {
        reconnectAttempt.value = 0;
        // The socket is alive after all: drop a reconnect it went quiet into.
        reconnectDelayMs.value = null;
        lastMessageAtMs.value = receivedAt;
        hasReceivedData.value =
          hasReceivedData.value || resolvedOptions.hasData(payload);
        commitState(hasReceivedData.value ? "connected" : "no_data");
        latestPayload.value = payload;
      });
    };

    socket.onclose = () => {
      if (ws !== socket) {
        return;
      }
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

    socket.onerror = () => {
      if (ws !== socket) {
        return;
      }
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
    const raw = Math.min(15000, base * 2 ** exp);
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
      if (!socketOpen.value || manuallyClosed.value) {
        return null;
      }
      const lastHeardAtMs = lastMessageAtMs.value || openedAtMs.value;
      const elapsedMs = Date.now() - lastHeardAtMs;
      return {
        delayMs: Math.max(0, resolvedOptions.staleAfterMs - elapsedMs),
        callback: goneQuiet,
      };
    });
  }

  /** Shows the data as stale, then replaces the silent socket after the usual backoff. */
  function goneQuiet(): void {
    batch(() => {
      commitState(hasReceivedData.value ? "stale" : "reconnecting");
      scheduleReconnect();
    });
  }

  function bindVisibilityListener(): () => void {
    if (typeof document === "undefined") {
      return () => {};
    }
    const onVisibilityChange = () => {
      if (
        disposed ||
        manuallyClosed.peek() ||
        document.visibilityState !== "visible"
      ) {
        return;
      }
      const socket = ws;
      if (socket?.readyState === WebSocket.CONNECTING) {
        return;
      }
      const lastHeardAtMs = lastMessageAtMs.peek() || openedAtMs.peek();
      if (
        socket?.readyState === WebSocket.OPEN &&
        Date.now() - lastHeardAtMs < RESUME_QUIET_MS
      ) {
        return;
      }
      batch(() => {
        reconnectAttempt.value = 0;
        reconnectDelayMs.value = null;
      });
      open("reconnecting");
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", onVisibilityChange);
  }

  function commitState(next: WsUiState): void {
    if (uiState.value === next) {
      return;
    }
    uiState.value = next;
  }
}
