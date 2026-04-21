import type { SpectrumPanelChartDom } from "../src/app/runtime/spectrum_panel_view";
import type {
  SpectrumCanvasRenderer,
  SpectrumCanvasRendererDeps,
  SpectrumPreparedRenderData,
} from "../src/app/runtime/spectrum_canvas_renderer";
import { createSpectrumFramePreparerCore } from "../src/app/runtime/spectrum_frame_preparer";
import { createAppState } from "../src/app/ui_app_state";
import type { AdaptedClient } from "../src/transport/live_models";
import { createElementStub, installDocumentStub } from "./spectrum_test_support";

type AppState = ReturnType<typeof createAppState>;
type ClientSpectrum = NonNullable<AppState["spectrum"]["spectra"]["value"]["clients"][string]>;

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
  deps?: Partial<Omit<SpectrumCanvasRendererDeps, "dom" | "state">>;
  seedState?: (state: AppState) => void;
}

export interface SpectrumRendererHarness {
  dom: SpectrumPanelChartDom;
  prepareFrame: () => SpectrumPreparedRenderData;
  renderer: SpectrumCanvasRenderer;
  state: AppState;
}

export function makeClient(id: string, name: string, overrides: Partial<AdaptedClient> = {}): AdaptedClient {
  return {
    id,
    name,
    connected: true,
    mac_address: id,
    location_code: "front_right_wheel",
    last_seen_age_ms: 25,
    dropped_frames: 0,
    frames_total: 100,
    frame_samples: 200,
    sample_rate_hz: 400,
    firmware_version: "fw-1.0.0",
    ...overrides,
  };
}

export function makeSpectrum(options: ClientSpectrumOptions = {}): ClientSpectrum {
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
  state: AppState,
  entries: readonly RendererClientFixture[],
): void {
  state.realtime.clients.value = entries.map((entry) => entry.client);
  state.spectrum.spectra.value = {
    ...state.spectrum.spectra.value,
    clients: Object.fromEntries(entries.map((entry) => [entry.client.id, entry.spectrum])),
  };
}

export function getRequiredClientSpectrum(state: AppState, clientId: string): ClientSpectrum {
  const spectrum = state.spectrum.spectra.value.clients[clientId];
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
  const framePreparer = createSpectrumFramePreparerCore();
  try {
    const { createSpectrumCanvasRenderer } = await import(
      "../src/app/runtime/spectrum_canvas_renderer"
    );
    const state = createAppState();
    options.seedState?.(state);
    const dom = {
      specChart: createElementStub("div"),
      specChartWrap: createElementStub("div"),
    } as unknown as SpectrumPanelChartDom;
    const renderer = createSpectrumCanvasRenderer({
      state,
      dom,
      t: (key) => key,
      getBandsVisible: () => false,
      getChartBands: () => [],
      getFocusMarker: () => null,
      onCursorDataIndexChange: () => undefined,
      ...options.deps,
    });
    const prepareFrame = () => renderer.composePreparedFrame(framePreparer.prepare({
      clients: state.realtime.clients.value.map((client) => ({
        id: client.id,
        name: client.name,
        connected: client.connected,
      })),
      spectraByClient: state.spectrum.spectra.value.clients,
    }));

    await run({ dom, prepareFrame, renderer, state });
  } finally {
    framePreparer.dispose();
    restoreDocument();
  }
}
