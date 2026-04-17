import type { UiShellErrorBannerModel } from "./ui_shell_chrome";
import { signal, type ReadonlySignal } from "../ui_signals";
import { createReplaceableTimeout } from "../timer_cleanup";

type UiShellNotificationDeps = {
  window: Pick<Window, "clearTimeout" | "setTimeout">;
};

export interface UiShellNotificationModule {
  readonly bannerModel: ReadonlySignal<UiShellErrorBannerModel>;
  clearError(): void;
  showError(message: string): void;
}

const HIDDEN_BANNER_MODEL: UiShellErrorBannerModel = {
  hidden: true,
  text: "",
  variant: null,
};

export function createUiShellNotificationModule(
  deps: UiShellNotificationDeps,
): UiShellNotificationModule {
  const hideBannerTimer = createReplaceableTimeout(deps.window);
  const bannerModel = signal<UiShellErrorBannerModel>(HIDDEN_BANNER_MODEL);

  function clearScheduledHide(): void {
    hideBannerTimer.clear();
  }

  function clearError(): void {
    clearScheduledHide();
    bannerModel.value = HIDDEN_BANNER_MODEL;
  }

  return {
    bannerModel,
    clearError,
    showError(message) {
      clearScheduledHide();
      bannerModel.value = {
        hidden: false,
        text: message,
        variant: "bad",
      };
      hideBannerTimer.replace(() => {
        bannerModel.value = HIDDEN_BANNER_MODEL;
      }, 5000);
    },
  };
}
