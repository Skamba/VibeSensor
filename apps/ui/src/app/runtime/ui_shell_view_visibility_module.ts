import { effect, type ReadonlySignal } from "../ui_signals";

type UiShellViewVisibilityDeps = {
  activeViewId: ReadonlySignal<string>;
  views: HTMLElement[];
};

export interface UiShellViewVisibilityModule {
  dispose(): void;
}

export function createUiShellViewVisibilityModule(
  deps: UiShellViewVisibilityDeps,
): UiShellViewVisibilityModule {
  const dispose = effect(() => {
    const activeViewId = deps.activeViewId.value;
    for (const view of deps.views) {
      view.hidden = view.id !== activeViewId;
    }
  });

  return { dispose };
}
