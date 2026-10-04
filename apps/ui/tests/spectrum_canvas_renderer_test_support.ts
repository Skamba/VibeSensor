import { type Signal, signal } from "@preact/signals";

import {
  createSpectrumFramePreparer,
  type SpectrumPreparedFrameData,
} from "../src/pages/spectrum/frame_preparer";
import type {
  SpectrumRenderer,
  SpectrumRendererDeps,
} from "../src/pages/spectrum/spectrum_renderer";
import type {
  AdaptedClient,
  SpectrumFrameData,
} from "../src/transport/live_models";
import {
  createElementStub,
  installDocumentStub,
} from "./spectrum_test_support";

/** The live inputs and chart status a renderer test controls. */
export interface RendererState {
  clients: Signal<AdaptedClient[]>;
  spectra: Signal<SpectrumFrameData>;
  chartLoading: Signal<boolean>;
  chartLoadError: Signal<string | null>;
  wsConnected: Signal<boolean>;
}
type ClientSpectrum = NonNullable<SpectrumFrameData["clients"][string]>;

interface ClientSpectrumOptions {
  combined?: number[];
  freq?: number[];
  noiseFloorAmpG?: number;
  peakAmp?: number;
  peakHz?: number;
  vibrationStrengthDb?: number;
}

export interface RendererClientFixture {
  client: AdaptedClient;
  spectrum: ClientSpectrum;
}

export interface SpectrumRendererHarnessOptions {
  deps?: Partial<Omit<SpectrumRendererDeps, "dom">>;
  seedState?: (state: RendererState) => void;
}

export interface SpectrumRendererHarness {
  prepareFrame: () => SpectrumPreparedFrameData;
  renderer: SpectrumRenderer;
  state: RendererState;
}

export function makeClient(
  id: string,
  name: string,
  overrides: Partial<AdaptedClient> = {},
): AdaptedClient {
  return {
    id,
    name,
    connected: true,
    mac_address: id,
    location_code: "front_right_wheel",
    last_seen_age_ms: 25,
    dropped_frames: 0,
    frame_loss_recent: false,
    frames_total: 100,
    frame_samples: 200,
    sample_rate_hz: 400,
    firmware_version: "fw-1.0.0",
    firmware_status: "unknown",
    ...overrides,
  };
}

export function makeSpectrum(
  options: ClientSpectrumOptions = {},
): ClientSpectrum {
  const freq = options.freq ?? [10, 15, 20];
  const combined = options.combined ?? [1, 0.75, 0.5];
  const peakAmp = options.peakAmp ?? combined[0] ?? 1;
  const peakHz = options.peakHz ?? freq[0] ?? 10;
  const vibrationStrengthDb = options.vibrationStrengthDb ?? 12;

  return {
    freq,
    combined,
    strength_metrics: {
      noise_floor_amp_g: options.noiseFloorAmpG ?? 0.1,
      peak_amp_g: peakAmp,
      strength_bucket: null,
      top_peaks: [
        {
          amp: peakAmp,
          hz: peakHz,
          strength_bucket: null,
          vibration_strength_db: vibrationStrengthDb,
        },
      ],
      vibration_strength_db: vibrationStrengthDb,
    },
  };
}

export function installClientSpectra(
  state: RendererState,
  entries: readonly RendererClientFixture[],
): void {
  state.clients.value = entries.map((entry) => entry.client);
  state.spectra.value = {
    ...state.spectra.value,
    clients: Object.fromEntries(
      entries.map((entry) => [entry.client.id, entry.spectrum]),
    ),
  };
}

export function getRequiredClientSpectrum(
  state: RendererState,
  clientId: string,
): ClientSpectrum {
  const spectrum = state.spectra.value.clients[clientId];
  if (!spectrum) {
    throw new Error(`Expected spectrum for ${clientId}`);
  }
  return spectrum;
}

export async function withSpectrumRendererHarness(
  options: SpectrumRendererHarnessOptions,
  run: (harness: SpectrumRendererHarness) => Promise<void> | void,
): Promise<void> {
  const restoreDocument = installDocumentStub();
  const framePreparer = createSpectrumFramePreparer();
  try {
    const { createSpectrumRenderer } = await import(
      "../src/pages/spectrum/spectrum_renderer"
    );
    const state: RendererState = {
      clients: signal([]),
      spectra: signal({ clients: {} }),
      chartLoading: signal(false),
      chartLoadError: signal(null),
      wsConnected: signal(false),
    };
    options.seedState?.(state);
    const dom = {
      specChart: createElementStub("div"),
      specChartWrap: createElementStub("div"),
    } as unknown as SpectrumRendererDeps["dom"];
    const renderer = createSpectrumRenderer({
      dom,
      t: (key) => key,
      canTween: () => state.wsConnected.value,
      chartLoading: state.chartLoading,
      chartLoadError: state.chartLoadError,
      getBandsVisible: () => false,
      getChartBands: () => [],
      getFocusMarker: () => null,
      onCursorDataIndexChange: () => undefined,
      ...options.deps,
    });
    const prepareFrame = () =>
      framePreparer.prepare({
        clients: state.clients.value,
        spectraByClient: state.spectra.value.clients,
      });

    await run({ prepareFrame, renderer, state });
  } finally {
    framePreparer.dispose();
    restoreDocument();
  }
}
