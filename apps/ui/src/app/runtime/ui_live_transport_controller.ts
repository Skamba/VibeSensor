import { adaptServerPayload } from "../../server_payload";
import type { AdaptedPayload } from "../../transport/live_models";
import { runDemoMode } from "../demo_mode";
import { WsClient } from "../../ws";
import {
  applyLivePayloadUpdate,
  batchAppStateUpdates,
  trackAppStateSlice,
  type AppState,
  unwrapAppStateValue,
} from "../ui_app_state";
import { effect, untracked } from "../ui_signals";

type UiLiveTransportControllerDeps = {
  state: AppState;
  payloadErrorMessage: () => string;
};

export class UiLiveTransportController {
  private readonly state: AppState;

  private readonly payloadErrorMessage: () => string;

  constructor(deps: UiLiveTransportControllerDeps) {
    this.state = deps.state;
    this.payloadErrorMessage = deps.payloadErrorMessage;
    this.bindTransportSignalSync();
  }

  sendSelection(): void {
    if (this.state.transport.ws) {
      this.state.transport.ws.send({ client_id: this.state.realtime.selectedClientId });
    }
  }

  private bindTransportSignalSync(): void {
    let previousPendingPayload = unwrapAppStateValue(this.state.transport.pendingPayload);
    let pendingPayloadInitialized = false;
    effect(() => {
      trackAppStateSlice(this.state.transport);
      const nextPendingPayload = unwrapAppStateValue(this.state.transport.pendingPayload);
      if (!pendingPayloadInitialized) {
        pendingPayloadInitialized = true;
        previousPendingPayload = nextPendingPayload;
        return;
      }
      if (nextPendingPayload === previousPendingPayload) {
        return;
      }
      previousPendingPayload = nextPendingPayload;
      if (nextPendingPayload !== null) {
        untracked(() => this.queueRender());
      }
    });

    let previousWsState = this.state.transport.wsState;
    let wsStateInitialized = false;
    effect(() => {
      trackAppStateSlice(this.state.transport);
      const nextWsState = this.state.transport.wsState;
      if (!wsStateInitialized) {
        wsStateInitialized = true;
        previousWsState = nextWsState;
        return;
      }
      if (nextWsState === previousWsState) {
        return;
      }
      previousWsState = nextWsState;
      if (nextWsState === "connected" || nextWsState === "no_data") {
        untracked(() => this.sendSelection());
      }
    });
  }

  startTransportMode(): void {
    const isDemoMode = new URLSearchParams(window.location.search).has("demo");
    if (isDemoMode) {
      runDemoMode({
        state: this.state,
      });
      return;
    }
    this.connectWs();
  }

  private queueRender(): void {
    if (this.state.transport.renderQueued) return;
    this.state.transport.renderQueued = true;
    window.requestAnimationFrame(() => {
      this.state.transport.renderQueued = false;
      const now = Date.now();
      if (now - this.state.transport.lastRenderTsMs < this.state.transport.minRenderIntervalMs) {
        this.queueRender();
        return;
      }
      const payload = unwrapAppStateValue(this.state.transport.pendingPayload);
      if (!payload) return;
      batchAppStateUpdates(() => {
        this.state.transport.pendingPayload = null;
        this.state.transport.lastRenderTsMs = now;
      });
      this.applyPayload(payload);
    });
  }

  private applyPayload(payload: unknown): void {
    let adapted: AdaptedPayload;
    try {
      adapted = adaptServerPayload(payload);
    } catch (error) {
      batchAppStateUpdates(() => {
        this.state.transport.payloadError =
          error instanceof Error ? error.message : this.payloadErrorMessage();
        this.state.spectrum.hasSpectrumData = false;
      });
      return;
    }

    const update = batchAppStateUpdates(() => {
      this.state.transport.payloadError = null;
      return applyLivePayloadUpdate({
        realtime: this.state.realtime,
        spectrum: this.state.spectrum,
        adaptedPayload: adapted,
      });
    });
    if (update.hasSelectedClientChanged) {
      this.sendSelection();
    }
  }

  private connectWs(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.transport.ws = new WsClient({
      url: `${protocol}//${window.location.host}/ws`,
      transport: this.state.transport,
    });
    this.state.transport.ws.connect();
  }
}
