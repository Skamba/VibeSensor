import { adaptServerPayload } from "../../server_payload";
import { runDemoMode } from "../../features/demo/runDemoMode";
import { WsClient } from "../../ws";
import type { AppFeatureBundle } from "../app_feature_bundle";
import { applySpectrumTick, type AppState } from "../state/ui_app_state";

type UiLiveTransportControllerDeps = {
  state: AppState;
  getFeatures: () => AppFeatureBundle;
  payloadErrorMessage: () => string;
  renderWsState: () => void;
  renderSpeedReadout: () => void;
  renderSpectrum: () => void;
  updateSpectrumOverlay: () => void;
};

export class UiLiveTransportController {
  private readonly state: AppState;

  private readonly getFeatures: () => AppFeatureBundle;

  private readonly payloadErrorMessage: () => string;

  private readonly renderWsState: () => void;

  private readonly renderSpeedReadout: () => void;

  private readonly renderSpectrum: () => void;

  private readonly updateSpectrumOverlay: () => void;

  constructor(deps: UiLiveTransportControllerDeps) {
    this.state = deps.state;
    this.getFeatures = deps.getFeatures;
    this.payloadErrorMessage = deps.payloadErrorMessage;
    this.renderWsState = deps.renderWsState;
    this.renderSpeedReadout = deps.renderSpeedReadout;
    this.renderSpectrum = deps.renderSpectrum;
    this.updateSpectrumOverlay = deps.updateSpectrumOverlay;
  }

  sendSelection(): void {
    if (this.state.ws) {
      this.state.ws.send({ client_id: this.state.selectedClientId });
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
    if (this.state.renderQueued) return;
    this.state.renderQueued = true;
    window.requestAnimationFrame(() => {
      this.state.renderQueued = false;
      const now = Date.now();
      if (now - this.state.lastRenderTsMs < this.state.minRenderIntervalMs) {
        this.queueRender();
        return;
      }
      const payload = this.state.pendingPayload;
      if (!payload) return;
      this.state.pendingPayload = null;
      this.state.lastRenderTsMs = now;
      this.applyPayload(payload);
    });
  }

  private applyPayload(payload: unknown): void {
    const features = this.getFeatures();
    let adapted;
    try {
      adapted = adaptServerPayload(payload);
    } catch (error) {
      this.state.payloadError = error instanceof Error ? error.message : this.payloadErrorMessage();
      this.state.hasSpectrumData = false;
      this.renderWsState();
      this.updateSpectrumOverlay();
      return;
    }

    this.state.payloadError = null;
    this.renderWsState();

    const prevSelected = this.state.selectedClientId;
    this.state.clients = adapted.clients;
    const hasFresh = features.dashboard.hasFreshSensorFrames(this.state.clients);
    const incomingSpectra = adapted.spectra
      ? {
        clients: Object.fromEntries(
          Object.entries(adapted.spectra.clients).map(([clientId, spectrum]) => [
            clientId,
            {
              freq: spectrum.freq,
              strength_metrics: spectrum.strength_metrics,
              combined: spectrum.combined,
            },
          ]),
        ),
      }
      : null;
    const spectrumTick = applySpectrumTick(
      this.state.spectra,
      this.state.hasSpectrumData,
      incomingSpectra,
    );
    this.state.spectra = spectrumTick.spectra;
    features.realtime.updateClientSelection();
    features.realtime.maybeRenderSensorsSettingsList();
    features.realtime.renderLoggingStatus();
    if (prevSelected !== this.state.selectedClientId) {
      this.sendSelection();
    }
    this.state.speedMps = adapted.speed_mps;
    this.state.rotationalSpeeds = adapted.rotational_speeds;
    this.state.hasSpectrumData = spectrumTick.hasSpectrumData;
    this.renderSpeedReadout();
    features.dashboard.applyServerDiagnostics(adapted.diagnostics, hasFresh);
    const liveIntensity = features.dashboard.extractLiveLocationIntensity();
    const intensityToPlot = Object.keys(liveIntensity).length > 0
      ? liveIntensity
      : features.dashboard.extractConfirmedLocationIntensity();
    features.dashboard.pushCarMapSample(intensityToPlot);
    features.dashboard.renderCarMap();
    if (spectrumTick.hasNewSpectrumFrame) {
      this.renderSpectrum();
    } else {
      this.updateSpectrumOverlay();
    }
    features.realtime.renderStatus(
      this.state.clients.find((client) => client.id === this.state.selectedClientId),
    );
  }

  private resetLiveSessionCounters(): void {
    this.state.strengthFrameTotalsByClient = {};
    this.state.carMapSamples = [];
  }

  private connectWs(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.ws = new WsClient({
      url: `${protocol}//${window.location.host}/ws`,
      onPayload: (payload) => {
        this.state.hasReceivedPayload = true;
        this.state.pendingPayload = payload;
        this.queueRender();
      },
      onStateChange: (nextState) => {
        this.state.wsState = nextState;
        this.renderWsState();
        this.updateSpectrumOverlay();
        if (nextState === "connected" || nextState === "no_data") {
          this.resetLiveSessionCounters();
          this.sendSelection();
        }
      },
    });
    this.state.ws.connect();
  }
}
