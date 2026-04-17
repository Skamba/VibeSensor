import type { LiveWsPayload } from "./contracts/ws_payload_types";
import { batchAppStateUpdates } from "./app/ui_app_state";
import { effect, signal } from "./app/ui_signals";

export type WsUiState = "connecting" | "connected" | "reconnecting" | "stale" | "no_data";

export interface WsTransportState {
  wsState: WsUiState;
  pendingPayload: unknown | null;
  hasReceivedPayload: boolean;
}

export interface WsClientOptions {
  url: string;
  staleAfterMs?: number;
  reconnectDelayMs?: number;
  hasData?: (payload: unknown) => boolean;
  transport: WsTransportState;
}

function hasSpectraClients(payload: unknown): boolean {
  const record = payload && typeof payload === "object"
    ? (payload as Partial<LiveWsPayload>)
    : null;
  const clients = record?.spectra?.clients;
  return Boolean(clients && Object.keys(clients).length > 0);
}

export class WsClient {
  private readonly options: Required<Omit<WsClientOptions, "transport">> & {
    transport: WsTransportState;
  };

  private ws: WebSocket | null = null;
  private readonly lastMessageAtMs = signal(0);
  private readonly hasData = signal(false);
  private readonly manuallyClosed = signal(false);
  private readonly reconnectAttempt = signal(0);
  private readonly reconnectDelayMs = signal<number | null>(null);
  private readonly socketOpen = signal(false);

  constructor(options: WsClientOptions) {
    this.options = {
      // 3s is too aggressive on weaker Pi + hotspot links and causes false stale flicker.
      staleAfterMs: 10000,
      reconnectDelayMs: 1200,
      hasData: hasSpectraClients,
      ...options,
    };
    this.bindReconnectLifecycle();
    this.bindStaleLifecycle();
  }

  connect(): void {
    batchAppStateUpdates(() => {
      this.manuallyClosed.value = false;
      this.reconnectDelayMs.value = null;
    });
    this.open("connecting");
  }

  close(): void {
    batchAppStateUpdates(() => {
      this.manuallyClosed.value = true;
      this.reconnectDelayMs.value = null;
      this.socketOpen.value = false;
    });
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  send(payload: { client_id: string | null }): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private open(initialState: WsUiState): void {
    batchAppStateUpdates(() => {
      this.commitState(initialState);
      this.hasData.value = false;
      this.lastMessageAtMs.value = 0;
      this.socketOpen.value = false;
    });
    this.ws = new WebSocket(this.options.url);

    this.ws.onopen = () => {
      batchAppStateUpdates(() => {
        this.socketOpen.value = true;
        this.commitState("no_data");
      });
    };

    this.ws.onmessage = (event) => {
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const receivedAt = Date.now();
      batchAppStateUpdates(() => {
        this.reconnectAttempt.value = 0;
        this.lastMessageAtMs.value = receivedAt;
        this.hasData.value = this.hasData.value || this.options.hasData(payload);
        this.commitState(this.hasData.value ? "connected" : "no_data");
        this.options.transport.hasReceivedPayload = true;
        this.options.transport.pendingPayload = payload;
      });
    };

    this.ws.onclose = () => {
      batchAppStateUpdates(() => {
        this.ws = null;
        this.socketOpen.value = false;
        if (this.manuallyClosed.value) {
          return;
        }
        this.commitState("reconnecting");
        this.scheduleReconnect();
      });
    };

    this.ws.onerror = () => {
      // onclose handles reconnect transitions.
    };
  }

  private scheduleReconnect(): void {
    this.reconnectDelayMs.value = this.nextReconnectDelayMs();
  }

  private nextReconnectDelayMs(): number {
    const base = Math.max(250, this.options.reconnectDelayMs);
    const exp = Math.min(6, this.reconnectAttempt.value);
    const raw = Math.min(15000, base * (2 ** exp));
    const jitter = raw * 0.25 * Math.random();
    this.reconnectAttempt.value += 1;
    return Math.round(raw + jitter);
  }

  private bindReconnectLifecycle(): void {
    effect(() => {
      const reconnectDelayMs = this.reconnectDelayMs.value;
      if (reconnectDelayMs === null || this.manuallyClosed.value) {
        return;
      }
      const timeoutId = window.setTimeout(() => {
        batchAppStateUpdates(() => {
          this.reconnectDelayMs.value = null;
        });
        this.open("reconnecting");
      }, reconnectDelayMs);
      return () => {
        window.clearTimeout(timeoutId);
      };
    });
  }

  private bindStaleLifecycle(): void {
    effect(() => {
      if (
        !this.socketOpen.value
        || this.manuallyClosed.value
        || !this.hasData.value
        || this.lastMessageAtMs.value <= 0
      ) {
        return;
      }
      const lastMessageAtMs = this.lastMessageAtMs.value;
      const intervalId = window.setInterval(() => {
        if (Date.now() - lastMessageAtMs > this.options.staleAfterMs) {
          this.setState("stale");
        }
      }, 1000);
      return () => {
        window.clearInterval(intervalId);
      };
    });
  }

  private setState(next: WsUiState): void {
    batchAppStateUpdates(() => {
      this.commitState(next);
    });
  }

  private commitState(next: WsUiState): void {
    if (this.options.transport.wsState === next) return;
    this.options.transport.wsState = next;
  }
}
