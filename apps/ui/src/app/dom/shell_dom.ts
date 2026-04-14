import { getById, queryOne, queryRequiredAll, requiredById } from "./dom_query";

const SHELL_OWNER = "UI shell";
const SHELL_CHROME_HOST_ID = "appShellChromeRoot";

export interface UiShellDom {
  menuButtons: HTMLElement[];
  views: HTMLElement[];
  languageSelect: HTMLSelectElement | null;
  languageFeedback: HTMLElement | null;
  speedUnitSelect: HTMLSelectElement | null;
  speedUnitFeedback: HTMLElement | null;
  linkState: HTMLElement | null;
  appErrorBanner: HTMLElement | null;
  appShellWrap: HTMLElement | null;
}

export function getUiShellChromeHost(): HTMLElement {
  return requiredById<HTMLElement>(SHELL_CHROME_HOST_ID, SHELL_OWNER);
}

export function createUiShellDom(): UiShellDom {
  return {
    menuButtons: queryRequiredAll<HTMLElement>(".menu-btn", SHELL_OWNER),
    views: queryRequiredAll<HTMLElement>(".view", SHELL_OWNER),
    languageSelect: getById<HTMLSelectElement>("languageSelect"),
    languageFeedback: getById<HTMLElement>("languageFeedback"),
    speedUnitSelect: getById<HTMLSelectElement>("speedUnitSelect"),
    speedUnitFeedback: getById<HTMLElement>("speedUnitFeedback"),
    linkState: getById<HTMLElement>("linkState"),
    appErrorBanner: getById<HTMLElement>("appErrorBanner"),
    appShellWrap: queryOne<HTMLElement>(".wrap"),
  };
}
