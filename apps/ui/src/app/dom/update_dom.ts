import { getById, requiredById } from "./dom_query";

const UPDATE_OWNER = "Update feature";

export interface UiUpdateDom {
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
  updateStartBtn: HTMLButtonElement;
  updateCancelBtn: HTMLButtonElement | null;
  updateStatusPanel: HTMLElement | null;
}

export function createUiUpdateDom(): UiUpdateDom {
  return {
    internetStatusPanel: getById<HTMLElement>("internetStatusPanel"),
    updateTransportOptions: getById<HTMLElement>("updateTransportOptions"),
    updateTransportChoiceWifi: getById<HTMLElement>("updateTransportChoiceWifi"),
    updateTransportChoiceUsb: getById<HTMLElement>("updateTransportChoiceUsb"),
    updateWifiFields: getById<HTMLElement>("updateWifiFields"),
    updateReadinessSummary: getById<HTMLElement>("updateReadinessSummary"),
    updateDetailsCaption: getById<HTMLElement>("updateDetailsCaption"),
    updateTransportNote: getById<HTMLElement>("updateTransportNote"),
    updateTransportWifiRadio: getById<HTMLInputElement>("updateTransportWifiRadio"),
    updateTransportUsbRadio: getById<HTMLInputElement>("updateTransportUsbRadio"),
    updateUsbTransportSummary: getById<HTMLElement>("updateUsbTransportSummary"),
    updateSsidInput: getById<HTMLInputElement>("updateSsidInput"),
    updatePasswordInput: getById<HTMLInputElement>("updatePasswordInput"),
    updateTogglePasswordBtn: getById<HTMLButtonElement>("updateTogglePasswordBtn"),
    updateStartBtn: requiredById<HTMLButtonElement>("updateStartBtn", UPDATE_OWNER),
    updateCancelBtn: getById<HTMLButtonElement>("updateCancelBtn"),
    updateStatusPanel: getById<HTMLElement>("updateStatusPanel"),
  };
}
