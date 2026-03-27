export interface UiDomElements {
  menuButtons: HTMLElement[];
  views: HTMLElement[];
  languageSelect: HTMLSelectElement | null;
  speedUnitSelect: HTMLSelectElement | null;
  speed: HTMLElement | null;
  headerGpsStatus: HTMLElement | null;
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
  startLoggingBtn: HTMLButtonElement | null;
  stopLoggingBtn: HTMLButtonElement | null;
  refreshHistoryBtn: HTMLButtonElement | null;
  deleteAllRunsBtn: HTMLButtonElement | null;
  historySummary: HTMLElement | null;
  historyTableBody: HTMLElement | null;
  sensorsSettingsBody: HTMLElement | null;
  lastSeen: HTMLElement | null;
  dropped: HTMLElement | null;
  framesTotal: HTMLElement | null;
  liveConnectedSensors: HTMLElement | null;
  liveAssignedLocations: HTMLElement | null;
  liveFocusSensor: HTMLElement | null;
  liveStrongestSignal: HTMLElement | null;
  liveRunHealth: HTMLElement | null;
  liveSensorRoster: HTMLElement | null;
  linkState: HTMLElement | null;
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement | null;
  spectrumOverlay: HTMLElement | null;
  spectrumInspector: HTMLElement | null;
  legend: HTMLElement | null;
  bandLegend: HTMLElement | null;
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
  analysisNoCarMessage: HTMLElement | null;
  carSelectionGuidance: HTMLElement | null;
  carListBody: HTMLElement | null;
  addCarBtn: HTMLButtonElement | null;
  addCarWizard: HTMLElement | null;
  wizardCloseBtn: HTMLButtonElement | null;
  wizardBackBtn: HTMLButtonElement | null;
  wizardSteps: Array<HTMLElement | null>;
  wizardStepDots: HTMLElement[];
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
  manualSpeedInput: HTMLInputElement | null;
  saveSpeedSourceBtn: HTMLButtonElement | null;
  settingsTabs: HTMLElement[];
  settingsTabPanels: HTMLElement[];
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
  espFlashStatusBanner: HTMLElement | null;
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
  gpsFallbackPanel: HTMLElement | null;
  staleTimeoutInput: HTMLInputElement | null;

  connectionBanner: HTMLElement | null;
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
    speedUnitSelect: selectEl("speedUnitSelect"),
    speed: el("speed"),
    headerGpsStatus: el("headerGpsStatus"),
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
    startLoggingBtn: btnEl("startLoggingBtn"),
    stopLoggingBtn: btnEl("stopLoggingBtn"),
    refreshHistoryBtn: btnEl("refreshHistoryBtn"),
    deleteAllRunsBtn: btnEl("deleteAllRunsBtn"),
    historySummary: el("historySummary"),
    historyTableBody: el("historyTableBody"),
    sensorsSettingsBody: el("sensorsSettingsBody"),
    lastSeen: el("lastSeen"),
    dropped: el("dropped"),
    framesTotal: el("framesTotal"),
    liveConnectedSensors: el("liveConnectedSensors"),
    liveAssignedLocations: el("liveAssignedLocations"),
    liveFocusSensor: el("liveFocusSensor"),
    liveStrongestSignal: el("liveStrongestSignal"),
    liveRunHealth: el("liveRunHealth"),
    liveSensorRoster: el("liveSensorRoster"),
    linkState: el("linkState"),
    specChartWrap: el("specChartWrap"),
    specChart: el("specChart"),
    spectrumOverlay: el("spectrumOverlay"),
    spectrumInspector: el("spectrumInspector"),
    legend: el("legend"),
    bandLegend: el("bandLegend"),
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
    analysisNoCarMessage: el("analysisNoCarMessage"),
    carSelectionGuidance: el("carSelectionGuidance"),
    carListBody: el("carListBody"),
    addCarBtn: btnEl("addCarBtn"),
    addCarWizard: el("addCarWizard"),
    wizardCloseBtn: btnEl("wizardCloseBtn"),
    wizardBackBtn: btnEl("wizardBackBtn"),
    wizardSteps: [0, 1, 2, 3, 4].map((index) => el(`wizardStep${index}`)),
    wizardStepDots: queryAll<HTMLElement>(".wizard-step-dot"),
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
    manualSpeedInput: inputEl("manualSpeedInput"),
    saveSpeedSourceBtn: btnEl("saveSpeedSourceBtn"),
    settingsTabs: queryAll<HTMLElement>(".settings-tab"),
    settingsTabPanels: queryAll<HTMLElement>(".settings-tab-panel"),
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
    espFlashStatusBanner: el("espFlashStatusBanner"),
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
    gpsFallbackPanel: el("gpsFallbackPanel"),
    staleTimeoutInput: inputEl("staleTimeoutInput"),
    connectionBanner: el("connectionBanner"),
    appErrorBanner: el("appErrorBanner"),
    appShellWrap: document.querySelector<HTMLElement>(".wrap"),

    rotationalAssumptions: el("rotationalAssumptions"),
    rotationalAssumptionsBody: el("rotationalAssumptionsBody"),
  };
}
