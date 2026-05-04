import type { WsClient, WsUiState } from "../ws";
import { signal } from "./ui_signals";
import type { SignalState } from "./signal_state";

export interface TransportStateValue {
  ws: WsClient | null;
  wsState: WsUiState;
  pendingPayload: unknown | null;
  renderQueued: boolean;
  lastRenderTsMs: number;
  minRenderIntervalMs: number;
  hasReceivedPayload: boolean;
  payloadError: string | null;
}

export type TransportState = SignalState<TransportStateValue>;

export function createTransportState(): TransportState {
  return {
    ws: signal<WsClient | null>(null),
    wsState: signal<WsUiState>("connecting"),
    pendingPayload: signal<unknown | null>(null),
    renderQueued: signal(false),
    lastRenderTsMs: signal(0),
    minRenderIntervalMs: signal(100),
    hasReceivedPayload: signal(false),
    payloadError: signal<string | null>(null),
  };
}
