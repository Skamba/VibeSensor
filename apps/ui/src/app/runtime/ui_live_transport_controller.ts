import type { AdaptedPayload } from "../../transport/live_models";
import { uiLogger } from "../../ui_logger";
import {
  applyLivePayloadUpdate,
  type AppState,
} from "../ui_app_state";
import { batch, computed, effectOnChange, untracked } from "../ui_signals";

type AdaptServerPayload = typeof import("../../server_payload").adaptServerPayload;
type LiveTransportRuntime = {
  createWsClient: typeof import("../../ws").createWsClient;
  runDemoMode: typeof import("../demo_mode").runDemoMode;
};

let liveTransportRuntimePromise: Promise<LiveTransportRuntime> | null = null;
let payloadAdapterPromise: Promise<AdaptServerPayload> | null = null;

function loadLiveTransportRuntime(): Promise<LiveTransportRuntime> {
  if (liveTransportRuntimePromise === null) {
    liveTransportRuntimePromise = Promise.all([
      import("../../ws"),
      import("../demo_mode"),
    ]).then(([wsModule, demoModeModule]) => ({
      createWsClient: wsModule.createWsClient,
      runDemoMode: demoModeModule.runDemoMode,
    })).catch((error) => {
      liveTransportRuntimePromise = null;
      throw error;
    });
  }
  return liveTransportRuntimePromise;
}

function loadPayloadAdapter(): Promise<AdaptServerPayload> {
  if (payloadAdapterPromise === null) {
    payloadAdapterPromise = import("../../server_payload")
      .then(({ adaptServerPayload }) => adaptServerPayload)
      .catch((error) => {
        payloadAdapterPromise = null;
        throw error;
      });
  }
  return payloadAdapterPromise;
}

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

  private transportStarted = false;

  private adaptServerPayload: AdaptServerPayload | null = null;

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
    void loadLiveTransportRuntime().catch((error) => {
      uiLogger.error("[VibeSensor] Failed to preload websocket transport runtime.", error);
    });
    void this.preloadPayloadAdapter().catch((error) => {
      uiLogger.error("[VibeSensor] Failed to preload live payload adapter.", error);
    });
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
    if (this.disposed || this.transportStarted) {
      return;
    }
    this.transportStarted = true;
    const isDemoMode = new URLSearchParams(window.location.search).has("demo");
    void this.preloadPayloadAdapter().catch((error) => {
      uiLogger.error("[VibeSensor] Failed to preload live payload adapter.", error);
    });
    if (isDemoMode) {
      void this.startDemoMode().catch((error) => {
        this.transportStarted = false;
        uiLogger.error("[VibeSensor] Failed to start demo transport mode.", error);
      });
      return;
    }
    void this.connectWs().catch((error) => {
      this.transportStarted = false;
      uiLogger.error("[VibeSensor] Failed to load websocket transport runtime.", error);
    });
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
    const adaptServerPayload = this.adaptServerPayload;
    if (adaptServerPayload === null) {
      void this.applyPayloadAsync(payload);
      return;
    }
    this.applyPayloadWithAdapter(payload, adaptServerPayload);
  }

  private async applyPayloadAsync(payload: unknown): Promise<void> {
    try {
      const adaptServerPayload = await this.preloadPayloadAdapter();
      if (this.disposed) {
        return;
      }
      this.applyPayloadWithAdapter(payload, adaptServerPayload);
    } catch (error) {
      if (this.disposed) {
        return;
      }
      batch(() => {
        this.state.transport.payloadError.value =
          error instanceof Error ? error.message : this.payloadErrorMessage();
        this.state.spectrum.hasSpectrumData.value = false;
      });
    }
  }

  private applyPayloadWithAdapter(
    payload: unknown,
    adaptServerPayload: AdaptServerPayload,
  ): void {
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

  private async startDemoMode(): Promise<void> {
    const { runDemoMode } = await loadLiveTransportRuntime();
    if (this.disposed) {
      return;
    }
    runDemoMode({
      ingestTransportPayload: (payload) => this.ingestTransportPayload(payload, "connected"),
      state: this.state,
    });
  }

  private async preloadPayloadAdapter(): Promise<AdaptServerPayload> {
    if (this.adaptServerPayload !== null) {
      return this.adaptServerPayload;
    }
    const adaptServerPayload = await loadPayloadAdapter();
    this.adaptServerPayload = adaptServerPayload;
    return adaptServerPayload;
  }

  private async connectWs(): Promise<void> {
    if (this.disposed) {
      return;
    }
    const { createWsClient } = await loadLiveTransportRuntime();
    if (this.disposed) {
      return;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.transport.ws.value?.dispose();
    const ws = createWsClient({
      url: `${protocol}//${window.location.host}/ws`,
    });
    this.state.transport.ws.value = ws;
    ws.connect();
  }
}
