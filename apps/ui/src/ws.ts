import type { LiveWsPayload } from "./contracts/ws_payload_types";
import { batchAppStateUpdates } from "./app/ui_app_state";
import { signal } from "./app/ui_signals";

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
  private reconnectTimer: number | null = null;
  private staleTimer: number | null = null;
  private readonly lastMessageAtMs = signal(0);
  private readonly hasData = signal(false);
  private manuallyClosed = false;
  private reconnectAttempt = 0;

  constructor(options: WsClientOptions) {
    this.options = {
      // 3s is too aggressive on weaker Pi + hotspot links and causes false stale flicker.
      staleAfterMs: 10000,
      reconnectDelayMs: 1200,
      hasData: hasSpectraClients,
      ...options,
    };
  }

  connect(): void {
    this.manuallyClosed = false;
    this.open("connecting");
    if (this.staleTimer === null) {
      this.staleTimer = window.setInterval(() => this.tickStale(), 1000);
    }
  }

  close(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.staleTimer !== null) {
      window.clearInterval(this.staleTimer);
      this.staleTimer = null;
    }
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
    });
    this.ws = new WebSocket(this.options.url);

    this.ws.onopen = () => {
      this.setState("no_data");
    };

    this.ws.onmessage = (event) => {
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const receivedAt = Date.now();
      this.reconnectAttempt = 0;
      batchAppStateUpdates(() => {
        this.lastMessageAtMs.value = receivedAt;
        this.hasData.value = this.hasData.value || this.options.hasData(payload);
        this.commitState(this.hasData.value ? "connected" : "no_data");
        this.options.transport.hasReceivedPayload = true;
        this.options.transport.pendingPayload = payload;
      });
    };

    this.ws.onclose = () => {
      this.ws = null;
      if (this.manuallyClosed) return;
      this.setState("reconnecting");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose handles reconnect transitions.
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.open("reconnecting");
    }, this.nextReconnectDelayMs());
  }

  private nextReconnectDelayMs(): number {
    const base = Math.max(250, this.options.reconnectDelayMs);
    const exp = Math.min(6, this.reconnectAttempt);
    const raw = Math.min(15000, base * (2 ** exp));
    const jitter = raw * 0.25 * Math.random();
    this.reconnectAttempt += 1;
    return Math.round(raw + jitter);
  }

  private tickStale(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    if (!this.hasData.value || this.lastMessageAtMs.value <= 0) {
      this.setState("no_data");
      return;
    }
    if (Date.now() - this.lastMessageAtMs.value > this.options.staleAfterMs) {
      this.setState("stale");
    }
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
