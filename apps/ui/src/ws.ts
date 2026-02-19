export type WsUiState = "connecting" | "connected" | "reconnecting" | "stale" | "no_data";

export interface WsClientOptions {
  url: string;
  staleAfterMs?: number;
  reconnectDelayMs?: number;
  hasData?: (payload: Record<string, unknown>) => boolean;
  onPayload: (payload: Record<string, unknown>) => void;
  onStateChange: (state: WsUiState) => void;
}

export class WsClient {
  private readonly options: Required<Omit<WsClientOptions, "onPayload" | "onStateChange">> & {
    onPayload: (payload: Record<string, unknown>) => void;
    onStateChange: (state: WsUiState) => void;
  };

  private ws: WebSocket | null = null;
  private state: WsUiState = "connecting";
  private reconnectTimer: number | null = null;
  private staleTimer: number | null = null;
  private lastMessageAtMs = 0;
  private lastServerTimeMs = 0;
  private hasData = false;
  private manuallyClosed = false;
  private reconnectAttempt = 0;

  constructor(options: WsClientOptions) {
    this.options = {
      staleAfterMs: 3000,
      reconnectDelayMs: 1200,
      hasData: (payload: Record<string, unknown>) => {
        const spectra = payload?.spectra;
        if (!spectra || typeof spectra !== "object") return false;
        const clients = (spectra as Record<string, unknown>).clients;
        if (!clients || typeof clients !== "object") return false;
        return Object.keys(clients as object).length > 0;
      },
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

  send(payload: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private open(initialState: WsUiState): void {
    this.setState(initialState);
    this.hasData = false;
    this.lastMessageAtMs = 0;
    this.lastServerTimeMs = 0;
    this.ws = new WebSocket(this.options.url);

    this.ws.onopen = () => {
      this.setState("no_data");
    };

    this.ws.onmessage = (event) => {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const receivedAt = Date.now();
      this.lastMessageAtMs = receivedAt;
      const parsedServerTime = Date.parse(String(payload?.server_time || ""));
      this.lastServerTimeMs = Number.isFinite(parsedServerTime) ? parsedServerTime : receivedAt;
      this.hasData = this.hasData || this.options.hasData(payload);
      this.reconnectAttempt = 0;
      this.setState(this.hasData ? "connected" : "no_data");
      this.options.onPayload(payload);
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
    if (!this.hasData || this.lastMessageAtMs <= 0) {
      this.setState("no_data");
      return;
    }
    const freshnessTime = this.lastMessageAtMs;
    if (Date.now() - freshnessTime > this.options.staleAfterMs) {
      this.setState("stale");
    }
  }

  private setState(next: WsUiState): void {
    if (this.state === next) return;
    this.state = next;
    this.options.onStateChange(next);
  }
}
