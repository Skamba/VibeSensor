import { adaptServerPayload } from "../../server_payload";
import type { AdaptedClient, AdaptedPayload } from "../../transport/live_models";
import { runDemoMode } from "../demo_mode";
import { WsClient } from "../../ws";
import {
  applyLivePayloadUpdate,
  batchAppStateUpdates,
  type AppState,
  unwrapAppStateValue,
} from "../ui_app_state";

type UiLiveTransportControllerDeps = {
  state: AppState;
  payloadErrorMessage: () => string;
  renderWsState: () => void;
  renderSpeedReadout: () => void;
  renderSpectrum: () => void;
  updateSpectrumOverlay: () => void;
};

export interface UiTransportFeaturePorts {
  updateClientSelection(): void;
  maybeRenderSensorsSettingsList(force?: boolean): void;
  renderLoggingStatus(): void;
  renderStatus(clientRow: AdaptedClient | undefined): void;
}

export class UiLiveTransportController {
  private readonly state: AppState;

  private ports: UiTransportFeaturePorts | null = null;

  private readonly payloadErrorMessage: () => string;

  private readonly renderWsState: () => void;

  private readonly renderSpeedReadout: () => void;

  private readonly renderSpectrum: () => void;

  private readonly updateSpectrumOverlay: () => void;

  constructor(deps: UiLiveTransportControllerDeps) {
    this.state = deps.state;
    this.payloadErrorMessage = deps.payloadErrorMessage;
    this.renderWsState = deps.renderWsState;
    this.renderSpeedReadout = deps.renderSpeedReadout;
    this.renderSpectrum = deps.renderSpectrum;
    this.updateSpectrumOverlay = deps.updateSpectrumOverlay;
  }

  attachPorts(ports: UiTransportFeaturePorts): void {
    this.ports = ports;
  }

  sendSelection(): void {
    if (this.state.transport.ws) {
      this.state.transport.ws.send({ client_id: this.state.realtime.selectedClientId });
    }
  }

  private refreshWsChrome(): void {
    this.renderWsState();
    this.updateSpectrumOverlay();
  }

  startTransportMode(): void {
    const isDemoMode = new URLSearchParams(window.location.search).has("demo");
    if (isDemoMode) {
      runDemoMode({
        state: this.state,
        renderWsState: this.renderWsState,
        applyPayload: (payload) => this.applyPayload(payload),
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
    const ports = this.requirePorts();
    let adapted: AdaptedPayload;
    try {
      adapted = adaptServerPayload(payload);
    } catch (error) {
      batchAppStateUpdates(() => {
        this.state.transport.payloadError =
          error instanceof Error ? error.message : this.payloadErrorMessage();
        this.state.spectrum.hasSpectrumData = false;
      });
      this.refreshWsChrome();
      return;
    }

    const update = batchAppStateUpdates(() => {
      this.state.transport.payloadError = null;
      return applyLivePayloadUpdate({
        realtime: this.state.realtime,
        spectrum: this.state.spectrum,
        adaptedPayload: adapted,
        updateClientSelection: () => ports.updateClientSelection(),
      });
    });
    this.renderWsState();
    ports.maybeRenderSensorsSettingsList();
    ports.renderLoggingStatus();
    if (update.hasSelectedClientChanged) {
      this.sendSelection();
    }
    this.renderSpeedReadout();
    if (update.hasNewSpectrumFrame) {
      this.renderSpectrum();
    } else {
      this.updateSpectrumOverlay();
    }
    ports.renderStatus(update.selectedClient);
  }

  private connectWs(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.transport.ws = new WsClient({
      url: `${protocol}//${window.location.host}/ws`,
      onPayload: (payload) => {
        batchAppStateUpdates(() => {
          this.state.transport.hasReceivedPayload = true;
          this.state.transport.pendingPayload = payload;
        });
        this.queueRender();
      },
      onStateChange: (nextState) => {
        this.state.transport.wsState = nextState;
        this.refreshWsChrome();
        if (nextState === "connected" || nextState === "no_data") {
          this.sendSelection();
        }
      },
    });
    this.state.transport.ws.connect();
  }

  private requirePorts(): UiTransportFeaturePorts {
    if (this.ports === null) {
      throw new Error("UiLiveTransportController ports used before initialization");
    }
    return this.ports;
  }
}
