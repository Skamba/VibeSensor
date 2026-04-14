import { requiredById } from "./dom_query";

const ANALYSIS_OWNER = "Analysis feature";

export function getUiAnalysisPanelHost(): HTMLElement {
  return requiredById("analysisPanelRoot", ANALYSIS_OWNER);
}
