export interface UiDomElements {
  menuButtons: HTMLElement[];
  views: HTMLElement[];
  languageSelect: HTMLSelectElement | null;
  speedUnitSelect: HTMLSelectElement | null;
  speed: HTMLElement | null;
  loggingStatus: HTMLElement | null;
  currentLogFile: HTMLElement | null;
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
  linkState: HTMLElement | null;
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement | null;
  spectrumOverlay: HTMLElement | null;
  legend: HTMLElement | null;
  bandLegend: HTMLElement | null;
  strengthChart: HTMLElement | null;
  strengthTooltip: HTMLElement | null;
  liveCarMapDots: HTMLElement | null;
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
  carListBody: HTMLElement | null;
  addCarBtn: HTMLButtonElement | null;
  addCarWizard: HTMLElement | null;
  wizardCloseBtn: HTMLButtonElement | null;
  wizardBackBtn: HTMLButtonElement | null;
  manualSpeedInput: HTMLInputElement | null;
  saveSpeedSourceBtn: HTMLButtonElement | null;
  settingsTabs: HTMLElement[];
  settingsTabPanels: HTMLElement[];
  vibrationLog: HTMLElement | null;
  vibrationMatrix: HTMLElement | null;
  matrixTooltip: HTMLElement | null;
}

function inputEl(id: string): HTMLInputElement | null {
  return document.getElementById(id) as HTMLInputElement | null;
}

function selectEl(id: string): HTMLSelectElement | null {
  return document.getElementById(id) as HTMLSelectElement | null;
}

function btnEl(id: string): HTMLButtonElement | null {
  return document.getElementById(id) as HTMLButtonElement | null;
}

function el(id: string): HTMLElement | null {
  return document.getElementById(id);
}

export function createUiDomRegistry(): UiDomElements {
  return {
    menuButtons: Array.from(document.querySelectorAll(".menu-btn")),
    views: Array.from(document.querySelectorAll(".view")),
    languageSelect: selectEl("languageSelect"),
    speedUnitSelect: selectEl("speedUnitSelect"),
    speed: el("speed"),
    loggingStatus: el("loggingStatus"),
    currentLogFile: el("currentLogFile"),
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
    linkState: el("linkState"),
    specChartWrap: el("specChartWrap"),
    specChart: el("specChart"),
    spectrumOverlay: el("spectrumOverlay"),
    legend: el("legend"),
    bandLegend: el("bandLegend"),
    strengthChart: el("strengthChart"),
    strengthTooltip: el("strengthTooltip"),
    liveCarMapDots: el("liveCarMapDots"),
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
    carListBody: el("carListBody"),
    addCarBtn: btnEl("addCarBtn"),
    addCarWizard: el("addCarWizard"),
    wizardCloseBtn: btnEl("wizardCloseBtn"),
    wizardBackBtn: btnEl("wizardBackBtn"),
    manualSpeedInput: inputEl("manualSpeedInput"),
    saveSpeedSourceBtn: btnEl("saveSpeedSourceBtn"),
    settingsTabs: Array.from(document.querySelectorAll(".settings-tab")),
    settingsTabPanels: Array.from(document.querySelectorAll(".settings-tab-panel")),
    vibrationLog: el("vibrationLog"),
    vibrationMatrix: el("vibrationMatrix"),
    matrixTooltip: el("matrixTooltip"),
  };
}
