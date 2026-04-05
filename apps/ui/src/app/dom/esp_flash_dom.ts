import { getById, requiredById } from "./dom_query";

const ESP_FLASH_OWNER = "ESP flash feature";

export interface UiEspFlashDom {
  espFlashPortSelect: HTMLSelectElement | null;
  espFlashRefreshPortsBtn: HTMLButtonElement | null;
  espFlashStartBtn: HTMLButtonElement;
  espFlashCancelBtn: HTMLButtonElement | null;
  espFlashStartSummary: HTMLElement | null;
  espFlashStatusBanner: HTMLElement | null;
  espFlashReadinessPanel: HTMLElement | null;
  espFlashJourneyPanel: HTMLElement | null;
  espFlashLogPanel: HTMLElement | null;
  espFlashHistoryPanel: HTMLElement | null;
}

export function createUiEspFlashDom(): UiEspFlashDom {
  return {
    espFlashPortSelect: getById<HTMLSelectElement>("espFlashPortSelect"),
    espFlashRefreshPortsBtn: getById<HTMLButtonElement>("espFlashRefreshPortsBtn"),
    espFlashStartBtn: requiredById<HTMLButtonElement>("espFlashStartBtn", ESP_FLASH_OWNER),
    espFlashCancelBtn: getById<HTMLButtonElement>("espFlashCancelBtn"),
    espFlashStartSummary: getById<HTMLElement>("espFlashStartSummary"),
    espFlashStatusBanner: getById<HTMLElement>("espFlashStatusBanner"),
    espFlashReadinessPanel: getById<HTMLElement>("espFlashReadinessPanel"),
    espFlashJourneyPanel: getById<HTMLElement>("espFlashJourneyPanel"),
    espFlashLogPanel: getById<HTMLElement>("espFlashLogPanel"),
    espFlashHistoryPanel: getById<HTMLElement>("espFlashHistoryPanel"),
  };
}
