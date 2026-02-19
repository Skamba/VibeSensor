import { createUiDomRegistry, type UiDomRegistry } from "../dom/ui_dom_registry";
import { createUiAppState, type UiAppState } from "../state/ui_app_state";

export type UiAppContextDeps = {
  startLegacyUiApp: () => void;
};

export class UiAppContext {
  readonly dom: UiDomRegistry;
  readonly state: UiAppState;

  constructor(readonly deps: UiAppContextDeps) {
    this.dom = createUiDomRegistry();
    this.state = createUiAppState();
  }
}
