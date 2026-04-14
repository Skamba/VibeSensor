import { getById, queryRequiredAll } from "./dom_query";

const SETTINGS_OWNER = "Settings feature";

export interface UiSettingsDom {
  wheelBandwidthInput: HTMLInputElement | null;
  driveshaftBandwidthInput: HTMLInputElement | null;
  engineBandwidthInput: HTMLInputElement | null;
  speedUncertaintyInput: HTMLInputElement | null;
  tireDiameterUncertaintyInput: HTMLInputElement | null;
  finalDriveUncertaintyInput: HTMLInputElement | null;
  gearUncertaintyInput: HTMLInputElement | null;
  minAbsBandHzInput: HTMLInputElement | null;
  maxBandHalfWidthInput: HTMLInputElement | null;
  saveAnalysisBtn: HTMLButtonElement | null;
  resetAnalysisBtn: HTMLButtonElement | null;
  analysisGuidanceHelp: HTMLDetailsElement | null;
  analysisFieldGuidance: {
    wheelBandwidth: HTMLElement | null;
    driveshaftBandwidth: HTMLElement | null;
    engineBandwidth: HTMLElement | null;
    speedUncertainty: HTMLElement | null;
    tireDiameterUncertainty: HTMLElement | null;
    finalDriveUncertainty: HTMLElement | null;
    gearUncertainty: HTMLElement | null;
    minAbsBandHz: HTMLElement | null;
    maxBandHalfWidth: HTMLElement | null;
  };
  analysisSaveFeedback: HTMLElement | null;
  analysisNoCarMessage: HTMLElement | null;
  speedSourceRadios: HTMLInputElement[];
  speedSourceCurrentSource: HTMLElement | null;
  speedSourceEffectiveSpeed: HTMLElement | null;
  speedSourceChoiceGps: HTMLElement | null;
  speedSourceChoiceObd: HTMLElement | null;
  speedSourceChoiceManual: HTMLElement | null;
  manualSpeedConfig: HTMLElement | null;
  manualSpeedInput: HTMLInputElement | null;
  manualSpeedFeedback: HTMLElement | null;
  obdSpeedConfig: HTMLElement | null;
  obdConfiguredDevice: HTMLElement | null;
  scanObdDevicesBtn: HTMLButtonElement | null;
  obdDeviceScanStatus: HTMLElement | null;
  obdDeviceList: HTMLElement | null;
  saveSpeedSourceBtn: HTMLButtonElement | null;
  speedSourceSaveFeedback: HTMLElement | null;
  speedSourceDiagnostics: HTMLDetailsElement | null;
  settingsTabs: HTMLElement[];
  settingsTabPanels: HTMLElement[];
  gpsStatusPanel: HTMLElement | null;
  gpsStatusState: HTMLElement | null;
  gpsStatusDevice: HTMLElement | null;
  gpsStatusLastUpdate: HTMLElement | null;
  gpsStatusRawSpeed: HTMLElement | null;
  gpsStatusEffectiveSpeed: HTMLElement | null;
  gpsStatusLastError: HTMLElement | null;
  gpsStatusReconnect: HTMLElement | null;
  gpsStatusFallback: HTMLElement | null;
  obdStatusPanel: HTMLElement | null;
  obdStatusConfiguredDevice: HTMLElement | null;
  obdStatusPairing: HTMLElement | null;
  obdStatusTrusted: HTMLElement | null;
  obdStatusConnected: HTMLElement | null;
  obdStatusRfcommChannel: HTMLElement | null;
  obdStatusLastRpm: HTMLElement | null;
  obdStatusRpmAge: HTMLElement | null;
  obdStatusTargetCadence: HTMLElement | null;
  obdStatusEffectiveCadence: HTMLElement | null;
  obdStatusRequestRtt: HTMLElement | null;
  obdStatusTimeouts: HTMLElement | null;
  obdStatusErrors: HTMLElement | null;
  obdStatusMode: HTMLElement | null;
  obdStatusBackoff: HTMLElement | null;
  obdStatusRawResponse: HTMLElement | null;
  obdStatusDebugHint: HTMLElement | null;
  gpsFallbackPanel: HTMLElement | null;
  staleTimeoutInput: HTMLInputElement | null;
  staleTimeoutFeedback: HTMLElement | null;
}

export function createUiSettingsDom(): UiSettingsDom {
  return {
    wheelBandwidthInput: getById<HTMLInputElement>("wheelBandwidthInput"),
    driveshaftBandwidthInput: getById<HTMLInputElement>(
      "driveshaftBandwidthInput",
    ),
    engineBandwidthInput: getById<HTMLInputElement>("engineBandwidthInput"),
    speedUncertaintyInput: getById<HTMLInputElement>("speedUncertaintyInput"),
    tireDiameterUncertaintyInput: getById<HTMLInputElement>(
      "tireDiameterUncertaintyInput",
    ),
    finalDriveUncertaintyInput: getById<HTMLInputElement>(
      "finalDriveUncertaintyInput",
    ),
    gearUncertaintyInput: getById<HTMLInputElement>("gearUncertaintyInput"),
    minAbsBandHzInput: getById<HTMLInputElement>("minAbsBandHzInput"),
    maxBandHalfWidthInput: getById<HTMLInputElement>("maxBandHalfWidthInput"),
    saveAnalysisBtn: getById<HTMLButtonElement>("saveAnalysisBtn"),
    resetAnalysisBtn: getById<HTMLButtonElement>("resetAnalysisBtn"),
    analysisGuidanceHelp: getById<HTMLDetailsElement>("analysisGuidanceHelp"),
    analysisFieldGuidance: {
      wheelBandwidth: getById<HTMLElement>("wheelBandwidthGuidance"),
      driveshaftBandwidth: getById<HTMLElement>("driveshaftBandwidthGuidance"),
      engineBandwidth: getById<HTMLElement>("engineBandwidthGuidance"),
      speedUncertainty: getById<HTMLElement>("speedUncertaintyGuidance"),
      tireDiameterUncertainty: getById<HTMLElement>(
        "tireDiameterUncertaintyGuidance",
      ),
      finalDriveUncertainty: getById<HTMLElement>(
        "finalDriveUncertaintyGuidance",
      ),
      gearUncertainty: getById<HTMLElement>("gearUncertaintyGuidance"),
      minAbsBandHz: getById<HTMLElement>("minAbsBandHzGuidance"),
      maxBandHalfWidth: getById<HTMLElement>("maxBandHalfWidthGuidance"),
    },
    analysisSaveFeedback: getById<HTMLElement>("analysisSaveFeedback"),
    analysisNoCarMessage: getById<HTMLElement>("analysisNoCarMessage"),
    speedSourceRadios: Array.from(
      document.querySelectorAll<HTMLInputElement>(
        'input[name="speedSourceRadio"]',
      ),
    ),
    speedSourceCurrentSource: getById<HTMLElement>("speedSourceCurrentSource"),
    speedSourceEffectiveSpeed: getById<HTMLElement>(
      "speedSourceEffectiveSpeed",
    ),
    speedSourceChoiceGps: getById<HTMLElement>("speedSourceChoiceGps"),
    speedSourceChoiceObd: getById<HTMLElement>("speedSourceChoiceObd"),
    speedSourceChoiceManual: getById<HTMLElement>("speedSourceChoiceManual"),
    manualSpeedConfig: getById<HTMLElement>("manualSpeedConfig"),
    manualSpeedInput: getById<HTMLInputElement>("manualSpeedInput"),
    manualSpeedFeedback: getById<HTMLElement>("manualSpeedFeedback"),
    obdSpeedConfig: getById<HTMLElement>("obdSpeedConfig"),
    obdConfiguredDevice: getById<HTMLElement>("obdConfiguredDevice"),
    scanObdDevicesBtn: getById<HTMLButtonElement>("scanObdDevicesBtn"),
    obdDeviceScanStatus: getById<HTMLElement>("obdDeviceScanStatus"),
    obdDeviceList: getById<HTMLElement>("obdDeviceList"),
    saveSpeedSourceBtn: getById<HTMLButtonElement>("saveSpeedSourceBtn"),
    speedSourceSaveFeedback: getById<HTMLElement>("speedSourceSaveFeedback"),
    speedSourceDiagnostics: getById<HTMLDetailsElement>(
      "speedSourceDiagnostics",
    ),
    settingsTabs: queryRequiredAll<HTMLElement>(
      ".settings-tab",
      SETTINGS_OWNER,
    ),
    settingsTabPanels: queryRequiredAll<HTMLElement>(
      ".settings-tab-panel",
      SETTINGS_OWNER,
    ),
    gpsStatusPanel: getById<HTMLElement>("gpsStatusPanel"),
    gpsStatusState: getById<HTMLElement>("gpsStatusState"),
    gpsStatusDevice: getById<HTMLElement>("gpsStatusDevice"),
    gpsStatusLastUpdate: getById<HTMLElement>("gpsStatusLastUpdate"),
    gpsStatusRawSpeed: getById<HTMLElement>("gpsStatusRawSpeed"),
    gpsStatusEffectiveSpeed: getById<HTMLElement>("gpsStatusEffectiveSpeed"),
    gpsStatusLastError: getById<HTMLElement>("gpsStatusLastError"),
    gpsStatusReconnect: getById<HTMLElement>("gpsStatusReconnect"),
    gpsStatusFallback: getById<HTMLElement>("gpsStatusFallback"),
    obdStatusPanel: getById<HTMLElement>("obdStatusPanel"),
    obdStatusConfiguredDevice: getById<HTMLElement>(
      "obdStatusConfiguredDevice",
    ),
    obdStatusPairing: getById<HTMLElement>("obdStatusPairing"),
    obdStatusTrusted: getById<HTMLElement>("obdStatusTrusted"),
    obdStatusConnected: getById<HTMLElement>("obdStatusConnected"),
    obdStatusRfcommChannel: getById<HTMLElement>("obdStatusRfcommChannel"),
    obdStatusLastRpm: getById<HTMLElement>("obdStatusLastRpm"),
    obdStatusRpmAge: getById<HTMLElement>("obdStatusRpmAge"),
    obdStatusTargetCadence: getById<HTMLElement>("obdStatusTargetCadence"),
    obdStatusEffectiveCadence: getById<HTMLElement>(
      "obdStatusEffectiveCadence",
    ),
    obdStatusRequestRtt: getById<HTMLElement>("obdStatusRequestRtt"),
    obdStatusTimeouts: getById<HTMLElement>("obdStatusTimeouts"),
    obdStatusErrors: getById<HTMLElement>("obdStatusErrors"),
    obdStatusMode: getById<HTMLElement>("obdStatusMode"),
    obdStatusBackoff: getById<HTMLElement>("obdStatusBackoff"),
    obdStatusRawResponse: getById<HTMLElement>("obdStatusRawResponse"),
    obdStatusDebugHint: getById<HTMLElement>("obdStatusDebugHint"),
    gpsFallbackPanel: getById<HTMLElement>("gpsFallbackPanel"),
    staleTimeoutInput: getById<HTMLInputElement>("staleTimeoutInput"),
    staleTimeoutFeedback: getById<HTMLElement>("staleTimeoutFeedback"),
  };
}
