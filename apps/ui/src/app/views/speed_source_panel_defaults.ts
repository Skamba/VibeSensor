import type { SpeedSourceDiagnosticsRenderModel } from "./speed_source_panel";

export const DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL: SpeedSourceDiagnosticsRenderModel = {
  gps: {
    deviceText: "--",
    effectiveSpeedText: "--",
    fallbackText: "--",
    lastErrorText: "--",
    lastUpdateText: "--",
    rawSpeedText: "--",
    reconnectText: "--",
    stateText: "--",
  },
  obd: {
    backoffText: "--",
    configuredDeviceText: "--",
    connectedText: "--",
    debugHintText: "--",
    effectiveCadenceText: "--",
    errorsText: "--",
    lastRpmText: "--",
    modeText: "--",
    pairingText: "--",
    rawResponseText: "--",
    requestRttText: "--",
    rfcommChannelText: "--",
    rpmAgeText: "--",
    targetCadenceText: "--",
    timeoutsText: "--",
    trustedText: "--",
    visible: false,
  },
};
