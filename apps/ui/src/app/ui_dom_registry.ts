export interface UiDomElements {
  menuButtons: HTMLElement[];
  views: HTMLElement[];
  languageSelect: HTMLSelectElement | null;
  languageFeedback: HTMLElement | null;
  speedUnitSelect: HTMLSelectElement | null;
  speedUnitFeedback: HTMLElement | null;
  speed: HTMLElement | null;
  rotationalBasisSource: HTMLElement | null;
  rotationalReason: HTMLElement | null;
  rotationalWheelValue: HTMLElement | null;
  rotationalWheelMode: HTMLElement | null;
  rotationalDriveshaftValue: HTMLElement | null;
  rotationalDriveshaftMode: HTMLElement | null;
  rotationalEngineValue: HTMLElement | null;
  rotationalEngineMode: HTMLElement | null;
  loggingStatus: HTMLElement | null;
  loggingSummary: HTMLElement | null;
  loggingRunId: HTMLElement | null;
  loggingPhase: HTMLElement | null;
  loggingElapsed: HTMLElement | null;
  loggingSamples: HTMLElement | null;
  startLoggingBtn: HTMLButtonElement | null;
  stopLoggingBtn: HTMLButtonElement | null;
  refreshHistoryBtn: HTMLButtonElement | null;
  deleteAllRunsBtn: HTMLButtonElement | null;
  historySummary: HTMLElement | null;
  historyTableBody: HTMLElement | null;
  sensorsSettingsBody: HTMLElement | null;
  liveConnectedSensors: HTMLElement | null;
  liveActiveCar: HTMLElement | null;
  liveRecordingState: HTMLElement | null;
  liveDataFreshness: HTMLElement | null;
  liveStrongestSignal: HTMLElement | null;
  liveRunHealth: HTMLElement | null;
  liveSensorRoster: HTMLElement | null;
  linkState: HTMLElement | null;
  shellLiveStatus: HTMLElement | null;
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement | null;
  spectrumOverlay: HTMLElement | null;
  spectrumInspector: HTMLElement | null;
  legend: HTMLElement | null;
  bandLegend: HTMLElement | null;
  spectrumBandToggle: HTMLButtonElement | null;
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
  analysisSaveFeedback: HTMLElement | null;
  analysisNoCarMessage: HTMLElement | null;
  carSelectionGuidance: HTMLElement | null;
  carListBody: HTMLElement | null;
  addCarBtn: HTMLButtonElement | null;
  wizardBackdrop: HTMLElement | null;
  addCarWizard: HTMLElement | null;
  wizardProgressText: HTMLElement | null;
  wizardCloseBtn: HTMLButtonElement | null;
  wizardBackBtn: HTMLButtonElement | null;
  wizardSteps: Array<HTMLElement | null>;
  wizardStepDots: HTMLElement[];
  wizardSummaryPanel: HTMLElement | null;
  wizardActionHint: HTMLElement | null;
  wizardBrandList: HTMLElement | null;
  wizardTypeList: HTMLElement | null;
  wizardModelList: HTMLElement | null;
  wizardVariantList: HTMLElement | null;
  wizardTireList: HTMLElement | null;
  wizardGearboxList: HTMLElement | null;
  wizardCustomBrandInput: HTMLInputElement | null;
  wizardCustomBrandBtn: HTMLButtonElement | null;
  wizardCustomTypeInput: HTMLInputElement | null;
  wizardCustomTypeBtn: HTMLButtonElement | null;
  wizardCustomModelInput: HTMLInputElement | null;
  wizardCustomModelBtn: HTMLButtonElement | null;
  wizardManualAddBtn: HTMLButtonElement | null;
  wizTireWidthInput: HTMLInputElement | null;
  wizTireAspectInput: HTMLInputElement | null;
  wizRimInput: HTMLInputElement | null;
  wizFinalDriveInput: HTMLInputElement | null;
  wizGearRatioInput: HTMLInputElement | null;
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
  internetStatusPanel: HTMLElement | null;
  updateTransportOptions: HTMLElement | null;
  updateTransportChoiceWifi: HTMLElement | null;
  updateTransportChoiceUsb: HTMLElement | null;
  updateWifiFields: HTMLElement | null;
  updateReadinessSummary: HTMLElement | null;
  updateDetailsCaption: HTMLElement | null;
  updateTransportNote: HTMLElement | null;
  updateTransportWifiRadio: HTMLInputElement | null;
  updateTransportUsbRadio: HTMLInputElement | null;
  updateUsbTransportSummary: HTMLElement | null;
  updateSsidInput: HTMLInputElement | null;
  updatePasswordInput: HTMLInputElement | null;
  updateTogglePasswordBtn: HTMLButtonElement | null;
  updateStartBtn: HTMLButtonElement | null;
  updateCancelBtn: HTMLButtonElement | null;
  updateStatusPanel: HTMLElement | null;
  espFlashPortSelect: HTMLSelectElement | null;
  espFlashRefreshPortsBtn: HTMLButtonElement | null;
  espFlashStartBtn: HTMLButtonElement | null;
  espFlashCancelBtn: HTMLButtonElement | null;
  espFlashStartSummary: HTMLElement | null;
  espFlashStatusBanner: HTMLElement | null;
  espFlashReadinessPanel: HTMLElement | null;
  espFlashJourneyPanel: HTMLElement | null;
  espFlashLogPanel: HTMLElement | null;
  espFlashHistoryPanel: HTMLElement | null;
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
  obdStatusRawResponse: HTMLElement | null;
  obdStatusDebugHint: HTMLElement | null;
  gpsFallbackPanel: HTMLElement | null;
  staleTimeoutInput: HTMLInputElement | null;
  staleTimeoutFeedback: HTMLElement | null;

  appErrorBanner: HTMLElement | null;
  appShellWrap: HTMLElement | null;
  rotationalAssumptions: HTMLElement | null;
  rotationalAssumptionsBody: HTMLElement | null;
}

function getById<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function inputEl(id: string): HTMLInputElement | null {
  return getById<HTMLInputElement>(id);
}

function selectEl(id: string): HTMLSelectElement | null {
  return getById<HTMLSelectElement>(id);
}

function btnEl(id: string): HTMLButtonElement | null {
  return getById<HTMLButtonElement>(id);
}

function el(id: string): HTMLElement | null {
  return getById<HTMLElement>(id);
}

function queryAll<T extends Element>(selector: string): T[] {
  return Array.from(document.querySelectorAll<T>(selector));
}

export function createUiDomRegistry(): UiDomElements {
  return {
    menuButtons: queryAll<HTMLElement>(".menu-btn"),
    views: queryAll<HTMLElement>(".view"),
    languageSelect: selectEl("languageSelect"),
    languageFeedback: el("languageFeedback"),
    speedUnitSelect: selectEl("speedUnitSelect"),
    speedUnitFeedback: el("speedUnitFeedback"),
    speed: el("speed"),
    rotationalBasisSource: el("rotationalBasisSource"),
    rotationalReason: el("rotationalReason"),
    rotationalWheelValue: el("rotationalWheelValue"),
    rotationalWheelMode: el("rotationalWheelMode"),
    rotationalDriveshaftValue: el("rotationalDriveshaftValue"),
    rotationalDriveshaftMode: el("rotationalDriveshaftMode"),
    rotationalEngineValue: el("rotationalEngineValue"),
    rotationalEngineMode: el("rotationalEngineMode"),
    loggingStatus: el("loggingStatus"),
    loggingSummary: el("loggingSummary"),
    loggingRunId: el("loggingRunId"),
    loggingPhase: el("loggingPhase"),
    loggingElapsed: el("loggingElapsed"),
    loggingSamples: el("loggingSamples"),
    startLoggingBtn: btnEl("startLoggingBtn"),
    stopLoggingBtn: btnEl("stopLoggingBtn"),
    refreshHistoryBtn: btnEl("refreshHistoryBtn"),
    deleteAllRunsBtn: btnEl("deleteAllRunsBtn"),
    historySummary: el("historySummary"),
    historyTableBody: el("historyTableBody"),
    sensorsSettingsBody: el("sensorsSettingsBody"),
    liveConnectedSensors: el("liveConnectedSensors"),
    liveActiveCar: el("liveActiveCar"),
    liveRecordingState: el("liveRecordingState"),
    liveDataFreshness: el("liveDataFreshness"),
    liveStrongestSignal: el("liveStrongestSignal"),
    liveRunHealth: el("liveRunHealth"),
    liveSensorRoster: el("liveSensorRoster"),
    linkState: el("linkState"),
    shellLiveStatus: el("shellLiveStatus"),
    specChartWrap: el("specChartWrap"),
    specChart: el("specChart"),
    spectrumOverlay: el("spectrumOverlay"),
    spectrumInspector: el("spectrumInspector"),
    legend: el("legend"),
    bandLegend: el("bandLegend"),
    spectrumBandToggle: btnEl("spectrumBandToggle"),
    wheelBandwidthInput: inputEl("wheelBandwidthInput"),
    driveshaftBandwidthInput: inputEl("driveshaftBandwidthInput"),
    engineBandwidthInput: inputEl("engineBandwidthInput"),
    speedUncertaintyInput: inputEl("speedUncertaintyInput"),
    tireDiameterUncertaintyInput: inputEl("tireDiameterUncertaintyInput"),
    finalDriveUncertaintyInput: inputEl("finalDriveUncertaintyInput"),
    gearUncertaintyInput: inputEl("gearUncertaintyInput"),
    minAbsBandHzInput: inputEl("minAbsBandHzInput"),
    maxBandHalfWidthInput: inputEl("maxBandHalfWidthInput"),
    saveAnalysisBtn: btnEl("saveAnalysisBtn"),
    resetAnalysisBtn: btnEl("resetAnalysisBtn"),
    analysisGuidanceHelp: getById<HTMLDetailsElement>("analysisGuidanceHelp"),
    analysisSaveFeedback: el("analysisSaveFeedback"),
    analysisNoCarMessage: el("analysisNoCarMessage"),
    carSelectionGuidance: el("carSelectionGuidance"),
    carListBody: el("carListBody"),
    addCarBtn: btnEl("addCarBtn"),
    wizardBackdrop: el("wizardBackdrop"),
    addCarWizard: el("addCarWizard"),
    wizardProgressText: el("wizardProgressText"),
    wizardCloseBtn: btnEl("wizardCloseBtn"),
    wizardBackBtn: btnEl("wizardBackBtn"),
    wizardSteps: [0, 1, 2, 3, 4].map((index) => el(`wizardStep${index}`)),
    wizardStepDots: queryAll<HTMLElement>(".wizard-step-dot"),
    wizardSummaryPanel: el("wizardSummaryPanel"),
    wizardActionHint: el("wizardActionHint"),
    wizardBrandList: el("wizardBrandList"),
    wizardTypeList: el("wizardTypeList"),
    wizardModelList: el("wizardModelList"),
    wizardVariantList: el("wizardVariantList"),
    wizardTireList: el("wizardTireList"),
    wizardGearboxList: el("wizardGearboxList"),
    wizardCustomBrandInput: inputEl("wizardCustomBrand"),
    wizardCustomBrandBtn: btnEl("wizardCustomBrandBtn"),
    wizardCustomTypeInput: inputEl("wizardCustomType"),
    wizardCustomTypeBtn: btnEl("wizardCustomTypeBtn"),
    wizardCustomModelInput: inputEl("wizardCustomModel"),
    wizardCustomModelBtn: btnEl("wizardCustomModelBtn"),
    wizardManualAddBtn: btnEl("wizardManualAddBtn"),
    wizTireWidthInput: inputEl("wizTireWidth"),
    wizTireAspectInput: inputEl("wizTireAspect"),
    wizRimInput: inputEl("wizRim"),
    wizFinalDriveInput: inputEl("wizFinalDrive"),
    wizGearRatioInput: inputEl("wizGearRatio"),
    speedSourceRadios: queryAll<HTMLInputElement>('input[name="speedSourceRadio"]'),
    speedSourceCurrentSource: el("speedSourceCurrentSource"),
    speedSourceEffectiveSpeed: el("speedSourceEffectiveSpeed"),
    speedSourceChoiceGps: el("speedSourceChoiceGps"),
    speedSourceChoiceObd: el("speedSourceChoiceObd"),
    speedSourceChoiceManual: el("speedSourceChoiceManual"),
    manualSpeedConfig: el("manualSpeedConfig"),
    manualSpeedInput: inputEl("manualSpeedInput"),
    manualSpeedFeedback: el("manualSpeedFeedback"),
    obdSpeedConfig: el("obdSpeedConfig"),
    obdConfiguredDevice: el("obdConfiguredDevice"),
    scanObdDevicesBtn: btnEl("scanObdDevicesBtn"),
    obdDeviceScanStatus: el("obdDeviceScanStatus"),
    obdDeviceList: el("obdDeviceList"),
    saveSpeedSourceBtn: btnEl("saveSpeedSourceBtn"),
    speedSourceSaveFeedback: el("speedSourceSaveFeedback"),
    speedSourceDiagnostics: getById<HTMLDetailsElement>("speedSourceDiagnostics"),
    settingsTabs: queryAll<HTMLElement>(".settings-tab"),
    settingsTabPanels: queryAll<HTMLElement>(".settings-tab-panel"),
    internetStatusPanel: el("internetStatusPanel"),
    updateTransportOptions: el("updateTransportOptions"),
    updateTransportChoiceWifi: el("updateTransportChoiceWifi"),
    updateTransportChoiceUsb: el("updateTransportChoiceUsb"),
    updateWifiFields: el("updateWifiFields"),
    updateReadinessSummary: el("updateReadinessSummary"),
    updateDetailsCaption: el("updateDetailsCaption"),
    updateTransportNote: el("updateTransportNote"),
    updateTransportWifiRadio: inputEl("updateTransportWifiRadio"),
    updateTransportUsbRadio: inputEl("updateTransportUsbRadio"),
    updateUsbTransportSummary: el("updateUsbTransportSummary"),
    updateSsidInput: inputEl("updateSsidInput"),
    updatePasswordInput: inputEl("updatePasswordInput"),
    updateTogglePasswordBtn: btnEl("updateTogglePasswordBtn"),
    updateStartBtn: btnEl("updateStartBtn"),
    updateCancelBtn: btnEl("updateCancelBtn"),
    updateStatusPanel: el("updateStatusPanel"),
    espFlashPortSelect: selectEl("espFlashPortSelect"),
    espFlashRefreshPortsBtn: btnEl("espFlashRefreshPortsBtn"),
    espFlashStartBtn: btnEl("espFlashStartBtn"),
    espFlashCancelBtn: btnEl("espFlashCancelBtn"),
    espFlashStartSummary: el("espFlashStartSummary"),
    espFlashStatusBanner: el("espFlashStatusBanner"),
    espFlashReadinessPanel: el("espFlashReadinessPanel"),
    espFlashJourneyPanel: el("espFlashJourneyPanel"),
    espFlashLogPanel: el("espFlashLogPanel"),
    espFlashHistoryPanel: el("espFlashHistoryPanel"),
    gpsStatusPanel: el("gpsStatusPanel"),
    gpsStatusState: el("gpsStatusState"),
    gpsStatusDevice: el("gpsStatusDevice"),
    gpsStatusLastUpdate: el("gpsStatusLastUpdate"),
    gpsStatusRawSpeed: el("gpsStatusRawSpeed"),
    gpsStatusEffectiveSpeed: el("gpsStatusEffectiveSpeed"),
    gpsStatusLastError: el("gpsStatusLastError"),
    gpsStatusReconnect: el("gpsStatusReconnect"),
    gpsStatusFallback: el("gpsStatusFallback"),
    obdStatusPanel: el("obdStatusPanel"),
    obdStatusConfiguredDevice: el("obdStatusConfiguredDevice"),
    obdStatusPairing: el("obdStatusPairing"),
    obdStatusTrusted: el("obdStatusTrusted"),
    obdStatusConnected: el("obdStatusConnected"),
    obdStatusRfcommChannel: el("obdStatusRfcommChannel"),
    obdStatusLastRpm: el("obdStatusLastRpm"),
    obdStatusRawResponse: el("obdStatusRawResponse"),
    obdStatusDebugHint: el("obdStatusDebugHint"),
    gpsFallbackPanel: el("gpsFallbackPanel"),
    staleTimeoutInput: inputEl("staleTimeoutInput"),
    staleTimeoutFeedback: el("staleTimeoutFeedback"),
    appErrorBanner: el("appErrorBanner"),
    appShellWrap: document.querySelector<HTMLElement>(".wrap"),

    rotationalAssumptions: el("rotationalAssumptions"),
    rotationalAssumptionsBody: el("rotationalAssumptionsBody"),
  };
}
