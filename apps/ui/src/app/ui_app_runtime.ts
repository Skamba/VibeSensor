import { createAppState, type AppState } from "./ui_app_state";
import {
  createLazyUiPanels,
  type UiLazyPanels,
  type UiMountedLazyPanelHandles,
  type UiMountedPanels,
} from "./ui_lazy_panels";
import {
  createUiShellChromeBindings,
  DEFAULT_UI_SHELL_CHROME_ACTIONS,
  SHELL_NAV_ITEMS,
  type UiShellChromeActions,
  type UiShellChromeBindings,
  type UiShellChromeNavigationModel,
} from "./runtime/ui_shell_chrome";
import { computed, signal, type Signal } from "./ui_signals";
import type { UiAppBootRuntime } from "./ui_app_boot_runtime";

export interface UiAppRuntime {
  attachSettingsPanels(handles: UiMountedLazyPanelHandles): void;
  dispose(): void;
  panels: UiMountedPanels;
  shellChrome: UiShellChromeBindings;
  spectrumPanel: UiLazyPanels["spectrumPanel"];
  start(): void;
}

export interface UiAppRuntimeDeps {
  state?: AppState;
}

export function createUiAppRuntime(deps: UiAppRuntimeDeps = {}): UiAppRuntime {
  const state = deps.state ?? createAppState();
  const shellChromeActions: Signal<UiShellChromeActions> =
    signal<UiShellChromeActions>({
      ...DEFAULT_UI_SHELL_CHROME_ACTIONS,
      activateView: (viewId) => {
        state.shell.activeViewId.value = viewId;
      },
    });
  const shellChrome = createUiShellChromeBindings(shellChromeActions);
  const prebootNavigationModel = computed<UiShellChromeNavigationModel>(() => ({
    activeViewId: state.shell.activeViewId.value,
    navItems: SHELL_NAV_ITEMS.map((item) => ({
      labelText: item.fallbackLabel,
      tabId: item.tabId,
      viewId: item.viewId,
    })),
  }));
  shellChrome.view.bindNavigationModel(prebootNavigationModel);
  const lazyPanels = createLazyUiPanels();
  let bootRuntime: UiAppBootRuntime | null = null;
  let bootRuntimePromise: Promise<UiAppBootRuntime | null> | null = null;
  let disposed = false;

  function ensureBootRuntime(): Promise<UiAppBootRuntime | null> {
    if (bootRuntime !== null) {
      return Promise.resolve(bootRuntime);
    }
    if (bootRuntimePromise !== null) {
      return bootRuntimePromise;
    }
    bootRuntimePromise = import("./ui_app_boot_runtime")
      .then(({ createUiAppBootRuntime }) => {
        if (disposed) {
          return null;
        }
        const nextBootRuntime = createUiAppBootRuntime({
          state,
          shellChrome,
          shellChromeActions,
          lazyPanels,
        });
        if (disposed) {
          nextBootRuntime.dispose();
          return null;
        }
        bootRuntime = nextBootRuntime;
        return nextBootRuntime;
      })
      .catch((error) => {
        bootRuntimePromise = null;
        throw error;
      });
    return bootRuntimePromise;
  }

  return {
    attachSettingsPanels: lazyPanels.attachSettingsPanels,
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      bootRuntime?.dispose();
      lazyPanels.dispose();
    },
    panels: lazyPanels.panels,
    shellChrome,
    spectrumPanel: lazyPanels.spectrumPanel,
    start() {
      if (disposed) {
        return;
      }
      void ensureBootRuntime()
        .then((resolvedBootRuntime) => {
          resolvedBootRuntime?.start();
        })
        .catch((error) => {
          console.error("[VibeSensor] Failed to start UI boot runtime.", error);
        });
    },
  };
}
