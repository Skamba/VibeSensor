import { adaptServerPayload } from "../../server_payload";
import type { AdaptedPayload } from "../../transport/live_models";
import { runDemoMode } from "../demo_mode";
import { createWsClient } from "../../ws";
import {
  applyLivePayloadUpdate,
  type AppState,
} from "../ui_app_state";
import { batch, effect, effectOnChange, untracked } from "../ui_signals";

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
    const ws = this.state.transport.ws.value;
    if (ws) {
      ws.send({ client_id: this.state.realtime.selectedClientId.value });
    }
  }

  private bindTransportSignalSync(): void {
    effect(() => {
      const ws = this.state.transport.ws.value;
      if (!ws) {
        return;
      }
      const nextWsState = ws.uiState.value;
      if (this.state.transport.wsState.value === nextWsState) {
        return;
      }
      batch(() => {
        this.state.transport.wsState.value = nextWsState;
      });
    });

    effectOnChange(this.state.transport.pendingPayload, (nextPendingPayload) => {
      if (nextPendingPayload !== null) {
        untracked(() => this.queueRender());
      }
    });

    effectOnChange(this.state.transport.wsState, (nextWsState) => {
      if (nextWsState === "connected" || nextWsState === "no_data") {
        untracked(() => this.sendSelection());
      }
    });
  }

  startTransportMode(): void {
    const isDemoMode = new URLSearchParams(window.location.search).has("demo");
    if (isDemoMode) {
      runDemoMode({
        queueTransportPayload: (payload) => this.queueTransportPayload(payload),
        state: this.state,
      });
      return;
    }
    this.connectWs();
  }

  private queueRender(): void {
    if (this.state.transport.renderQueued.value) return;
    this.state.transport.renderQueued.value = true;
    window.requestAnimationFrame(() => {
      this.state.transport.renderQueued.value = false;
      const now = Date.now();
      if (
        now - this.state.transport.lastRenderTsMs.value
        < this.state.transport.minRenderIntervalMs.value
      ) {
        this.queueRender();
        return;
      }
      const payload = this.state.transport.pendingPayload.value;
      if (!payload) return;
      batch(() => {
        this.state.transport.pendingPayload.value = null;
        this.state.transport.lastRenderTsMs.value = now;
      });
      this.applyPayload(payload);
    });
  }

  private applyPayload(payload: unknown): void {
    let adapted: AdaptedPayload;
    try {
      adapted = adaptServerPayload(payload);
    } catch (error) {
      batch(() => {
        this.state.transport.payloadError.value =
          error instanceof Error ? error.message : this.payloadErrorMessage();
        this.state.spectrum.hasSpectrumData.value = false;
      });
      return;
    }

    let update!: ReturnType<typeof applyLivePayloadUpdate>;
    batch(() => {
      this.state.transport.payloadError.value = null;
      update = applyLivePayloadUpdate({
        realtime: this.state.realtime,
        spectrum: this.state.spectrum,
        adaptedPayload: adapted,
      });
    });
    if (update.hasSelectedClientChanged) {
      this.sendSelection();
    }
  }

  private queueTransportPayload(payload: unknown): void {
    batch(() => {
      this.state.transport.wsState.value = "connected";
      this.state.transport.hasReceivedPayload.value = true;
      this.state.transport.pendingPayload.value = payload;
    });
  }

  private connectWs(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.transport.ws.value = createWsClient({
      url: `${protocol}//${window.location.host}/ws`,
      onMessage: (payload) => {
        this.state.transport.hasReceivedPayload.value = true;
        this.state.transport.pendingPayload.value = payload;
      },
    });
    this.state.transport.ws.value.connect();
  }
}
