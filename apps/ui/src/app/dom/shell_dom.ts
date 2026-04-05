import { getById, queryOne, queryRequiredAll } from "./dom_query";

const SHELL_OWNER = "UI shell";

export interface UiShellDom {
  menuButtons: HTMLElement[];
  views: HTMLElement[];
  languageSelect: HTMLSelectElement | null;
  languageFeedback: HTMLElement | null;
  speedUnitSelect: HTMLSelectElement | null;
  speedUnitFeedback: HTMLElement | null;
  speed: HTMLElement | null;
  linkState: HTMLElement | null;
  appErrorBanner: HTMLElement | null;
  appShellWrap: HTMLElement | null;
}

export function createUiShellDom(): UiShellDom {
  return {
    menuButtons: queryRequiredAll<HTMLElement>(".menu-btn", SHELL_OWNER),
    views: queryRequiredAll<HTMLElement>(".view", SHELL_OWNER),
    languageSelect: getById<HTMLSelectElement>("languageSelect"),
    languageFeedback: getById<HTMLElement>("languageFeedback"),
    speedUnitSelect: getById<HTMLSelectElement>("speedUnitSelect"),
    speedUnitFeedback: getById<HTMLElement>("speedUnitFeedback"),
    speed: getById<HTMLElement>("speed"),
    linkState: getById<HTMLElement>("linkState"),
    appErrorBanner: getById<HTMLElement>("appErrorBanner"),
    appShellWrap: queryOne<HTMLElement>(".wrap"),
  };
}
