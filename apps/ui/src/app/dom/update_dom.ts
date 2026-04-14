import { getById, requiredById } from "./dom_query";

const UPDATE_OWNER = "Update feature";

export interface UiUpdateDom {
  updateStartBtn: HTMLButtonElement;
  updateCancelBtn: HTMLButtonElement | null;
  updateStatusPanel: HTMLElement | null;
}

export function createUiUpdateDom(): UiUpdateDom {
  return {
    updateStartBtn: requiredById<HTMLButtonElement>(
      "updateStartBtn",
      UPDATE_OWNER,
    ),
    updateCancelBtn: getById<HTMLButtonElement>("updateCancelBtn"),
    updateStatusPanel: getById<HTMLElement>("updateStatusPanel"),
  };
}
