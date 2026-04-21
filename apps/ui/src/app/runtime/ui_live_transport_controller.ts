import { adaptServerPayload } from "../../server_payload";
import type { AdaptedPayload } from "../../transport/live_models";
import { runDemoMode } from "../demo_mode";
import { createWsClient } from "../../ws";
import {
  applyLivePayloadUpdate,
  type AppState,
} from "../ui_app_state";
import { batch, computed, effectOnChange, untracked } from "../ui_signals";

type UiLiveTransportControllerDeps = {
  state: AppState;
  payloadErrorMessage: () => string;
};

export class UiLiveTransportController {
  private readonly state: AppState;

  private readonly payloadErrorMessage: () => string;

  private readySelectionCycle = 0;

  private lastSentSelectionClientId: string | null | undefined = undefined;

  private lastSentSelectionCycle = -1;

  private readonly disposeTransportStateSync: () => void;

  private readonly disposeTransportIngressSync: () => void;

  private readonly disposePendingPayloadSync: () => void;

  private readonly disposeWsStateSync: () => void;

  private readonly disposeSelectionSync: () => void;

  private disposed = false;

  private queuedRenderFrameId: number | null = null;

  constructor(deps: UiLiveTransportControllerDeps) {
    this.state = deps.state;
    this.payloadErrorMessage = deps.payloadErrorMessage;
    const disposers = this.bindTransportSignalSync();
    this.disposeTransportStateSync = disposers.transportStateSync;
    this.disposeTransportIngressSync = disposers.transportIngressSync;
    this.disposePendingPayloadSync = disposers.pendingPayloadSync;
    this.disposeWsStateSync = disposers.wsStateSync;
    this.disposeSelectionSync = disposers.selectionSync;
  }

  sendSelection(): void {
    if (this.disposed) {
      return;
    }
    const ws = this.state.transport.ws.value;
    const clientId = this.state.realtime.selectedClientId.value;
    if (
      !ws
      || (
        this.lastSentSelectionCycle === this.readySelectionCycle
        && Object.is(this.lastSentSelectionClientId, clientId)
      )
    ) {
      return;
    }
    this.lastSentSelectionCycle = this.readySelectionCycle;
    this.lastSentSelectionClientId = clientId;
    ws.send({ client_id: clientId });
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    if (this.queuedRenderFrameId !== null) {
      globalThis.cancelAnimationFrame(this.queuedRenderFrameId);
      this.queuedRenderFrameId = null;
    }
    this.state.transport.ws.value?.dispose();
    this.state.transport.ws.value = null;
    this.disposeSelectionSync();
    this.disposeWsStateSync();
    this.disposePendingPayloadSync();
    this.disposeTransportIngressSync();
    this.disposeTransportStateSync();
  }

  private bindTransportSignalSync(): {
    pendingPayloadSync: () => void;
    selectionSync: () => void;
    transportIngressSync: () => void;
    transportStateSync: () => void;
    wsStateSync: () => void;
  } {
    const wsUiState = computed(() => this.state.transport.ws.value?.uiState.value ?? null);
    const wsLatestPayload = computed(
      () => this.state.transport.ws.value?.latestPayload.value ?? null,
    );

    const transportStateSync = effectOnChange(wsUiState, (nextWsState) => {
      if (nextWsState === null || this.state.transport.wsState.value === nextWsState) {
        return;
      }
      this.state.transport.wsState.value = nextWsState;
    });

    const transportIngressSync = effectOnChange(wsLatestPayload, (nextPayload) => {
      if (nextPayload === null) {
        return;
      }
      this.ingestTransportPayload(nextPayload);
    });

    const pendingPayloadSync = effectOnChange(this.state.transport.pendingPayload, (nextPendingPayload) => {
      if (nextPendingPayload !== null) {
        untracked(() => this.queueRender());
      }
    });

    const wsStateSync = effectOnChange(this.state.transport.wsState, (nextWsState, previousWsState) => {
      const nextReady = nextWsState === "connected" || nextWsState === "no_data";
      const previousReady = previousWsState === "connected" || previousWsState === "no_data";
      if (nextReady && !previousReady) {
        this.readySelectionCycle += 1;
        untracked(() => this.sendSelection());
      }
    });

    const selectionSync = effectOnChange(this.state.realtime.selectedClientId, () => {
      untracked(() => this.sendSelection());
    });

    return {
      pendingPayloadSync,
      selectionSync,
      transportIngressSync,
      transportStateSync,
      wsStateSync,
    };
  }

  startTransportMode(): void {
    if (this.disposed) {
      return;
    }
    const isDemoMode = new URLSearchParams(window.location.search).has("demo");
    if (isDemoMode) {
      runDemoMode({
        ingestTransportPayload: (payload) => this.ingestTransportPayload(payload, "connected"),
        state: this.state,
      });
      return;
    }
    this.connectWs();
  }

  private queueRender(): void {
    if (this.disposed || this.state.transport.renderQueued.value) return;
    this.state.transport.renderQueued.value = true;
    this.queuedRenderFrameId = globalThis.requestAnimationFrame(() => {
      this.queuedRenderFrameId = null;
      if (this.disposed) {
        this.state.transport.renderQueued.value = false;
        return;
      }
      this.state.transport.renderQueued.value = false;
      const now = Date.now();
      if (
        now - this.state.transport.lastRenderTsMs.value
        < this.state.transport.minRenderIntervalMs.value
      ) {
        // Retain RAF pacing here for render/spectrum throughput, not because the
        // transport ingress path still needs callback-style fan-out.
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
    if (this.disposed) {
      return;
    }
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

    batch(() => {
      this.state.transport.payloadError.value = null;
      applyLivePayloadUpdate({
        realtime: this.state.realtime,
        spectrum: this.state.spectrum,
        adaptedPayload: adapted,
      });
    });
  }

  private ingestTransportPayload(
    payload: unknown,
    wsState: "connected" | null = null,
  ): void {
    if (this.disposed) {
      return;
    }
    batch(() => {
      if (wsState !== null) {
        this.state.transport.wsState.value = wsState;
      }
      this.state.transport.hasReceivedPayload.value = true;
      this.state.transport.pendingPayload.value = payload;
    });
  }

  private connectWs(): void {
    if (this.disposed) {
      return;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.transport.ws.value = createWsClient({
      url: `${protocol}//${window.location.host}/ws`,
    });
    this.state.transport.ws.value.connect();
  }
}
