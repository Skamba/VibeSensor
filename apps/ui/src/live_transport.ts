import { batch, effect } from "@preact/signals";

import { isDemoMode } from "./app_store";
import { DEMO_CAR, demoPayload } from "./demo";
import { t } from "./i18n";
import {
  clients,
  hasReceivedPayload,
  payloadError,
  rotationalSpeeds,
  selectedClientId,
  spectra,
  speedMps,
  syncSelection,
  wsState,
} from "./live_store";
import { createSelectionSender, mergeSpectra } from "./live_sync";
import { adaptServerPayload } from "./server_payload";
import { analysisTuning, applyCars } from "./settings_store";
import {
  composeVehicleSettings,
  defaultCarAspectSettings,
} from "./vehicle_settings";
import { createWsClient } from "./ws";

/** Applies at most one payload per frame and every 100 ms. */
const MIN_APPLY_INTERVAL_MS = 100;

let started = false;
let pending: unknown = null;
let frameQueued = false;
let lastAppliedAtMs = 0;

function apply(payload: unknown): void {
  let adapted: ReturnType<typeof adaptServerPayload>;
  try {
    adapted = adaptServerPayload(payload);
  } catch (error) {
    payloadError.value =
      error instanceof Error ? error.message : t("ws.payload_error");
    return;
  }
  batch(() => {
    payloadError.value = null;
    clients.value = adapted.clients;
    spectra.value = mergeSpectra(spectra.value, adapted.spectra);
    speedMps.value = adapted.speed_mps;
    rotationalSpeeds.value = adapted.rotational_speeds;
    syncSelection();
  });
}

function scheduleApply(): void {
  if (frameQueued) {
    return;
  }
  frameQueued = true;
  requestAnimationFrame(() => {
    frameQueued = false;
    const now = Date.now();
    if (now - lastAppliedAtMs < MIN_APPLY_INTERVAL_MS) {
      scheduleApply();
      return;
    }
    const payload = pending;
    if (payload === null) {
      return;
    }
    pending = null;
    lastAppliedAtMs = now;
    apply(payload);
  });
}

function receive(payload: unknown): void {
  hasReceivedPayload.value = true;
  pending = payload;
  scheduleApply();
}

/** Connects to the live feed, or plays the canned demo payload with `?demo`. */
export function startLive(): void {
  if (started) {
    return;
  }
  started = true;
  if (isDemoMode()) {
    applyCars({
      cars: [
        {
          ...DEMO_CAR,
          aspects: composeVehicleSettings(
            defaultCarAspectSettings,
            analysisTuning.value,
          ),
        },
      ],
      active_car_id: DEMO_CAR.id,
    });
    wsState.value = "connected";
    receive(demoPayload());
    return;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = createWsClient({ url: `${protocol}//${window.location.host}/ws` });
  effect(() => {
    wsState.value = ws.uiState.value;
  });
  effect(() => {
    const payload = ws.latestPayload.value;
    if (payload !== null) {
      receive(payload);
    }
  });
  const sendSelection = createSelectionSender((clientId) =>
    ws.send({ client_id: clientId }),
  );
  effect(() => {
    const state = wsState.value;
    sendSelection(
      state === "connected" || state === "no_data",
      selectedClientId.value,
    );
  });
  ws.connect();
}
