import { adaptServerPayload, type AdaptedPayload } from "../../server_payload";
import { runDemoMode } from "../demo_mode";
import { WsClient } from "../../ws";
import type { AppFeatureBundle } from "../app_feature_bundle";
import { applySpectrumTick, type AppState } from "../ui_app_state";

type UiLiveTransportControllerDeps = {
  state: AppState;
  payloadErrorMessage: () => string;
  renderWsState: () => void;
  renderSpeedReadout: () => void;
  renderSpectrum: () => void;
  updateSpectrumOverlay: () => void;
};

export class UiLiveTransportController {
  private readonly state: AppState;

  private features: AppFeatureBundle | null = null;

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

  attachFeatures(features: AppFeatureBundle): void {
    this.features = features;
  }

  sendSelection(): void {
    if (this.state.transport.ws) {
      this.state.transport.ws.send({ client_id: this.state.realtime.selectedClientId });
    }
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
      const payload = this.state.transport.pendingPayload;
      if (!payload) return;
      this.state.transport.pendingPayload = null;
      this.state.transport.lastRenderTsMs = now;
      this.applyPayload(payload);
    });
  }

  private applyPayload(payload: unknown): void {
    const features = this.requireFeatures();
    let adapted: AdaptedPayload;
    try {
      adapted = adaptServerPayload(payload);
    } catch (error) {
      this.state.transport.payloadError = error instanceof Error ? error.message : this.payloadErrorMessage();
      this.state.spectrum.hasSpectrumData = false;
      this.renderWsState();
      this.updateSpectrumOverlay();
      return;
    }

    this.state.transport.payloadError = null;
    this.renderWsState();

    const prevSelected = this.state.realtime.selectedClientId;
    this.state.realtime.clients = adapted.clients;
    const spectrumTick = applySpectrumTick(
      this.state.spectrum.spectra,
      this.state.spectrum.hasSpectrumData,
      adapted.spectra,
    );
    this.state.spectrum.spectra = spectrumTick.spectra;
    features.realtime.updateClientSelection();
    features.realtime.maybeRenderSensorsSettingsList();
    features.realtime.renderLoggingStatus();
    if (prevSelected !== this.state.realtime.selectedClientId) {
      this.sendSelection();
    }
    this.state.realtime.speedMps = adapted.speed_mps;
    this.state.realtime.rotationalSpeeds = adapted.rotational_speeds;
    this.state.spectrum.hasSpectrumData = spectrumTick.hasSpectrumData;
    this.renderSpeedReadout();
    if (spectrumTick.hasNewSpectrumFrame) {
      this.renderSpectrum();
    } else {
      this.updateSpectrumOverlay();
    }
    features.realtime.renderStatus(
      this.state.realtime.clients.find((client) => client.id === this.state.realtime.selectedClientId),
    );
  }

  private connectWs(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.transport.ws = new WsClient({
      url: `${protocol}//${window.location.host}/ws`,
      onPayload: (payload) => {
        this.state.transport.hasReceivedPayload = true;
        this.state.transport.pendingPayload = payload;
        this.queueRender();
      },
      onStateChange: (nextState) => {
        this.state.transport.wsState = nextState;
        this.renderWsState();
        this.updateSpectrumOverlay();
        if (nextState === "connected" || nextState === "no_data") {
          this.sendSelection();
        }
      },
    });
    this.state.transport.ws.connect();
  }

  private requireFeatures(): AppFeatureBundle {
    if (this.features === null) {
      throw new Error("UiLiveTransportController features used before initialization");
    }
    return this.features;
  }
}
