import type { UiShellErrorBannerModel } from "./ui_shell_chrome";

type UiShellNotificationDeps = {
  onChanged?: () => void;
  window: Pick<Window, "clearTimeout" | "setTimeout">;
};

export interface UiShellNotificationModule {
  clearError(): void;
  getBannerModel(): UiShellErrorBannerModel;
  showError(message: string): void;
}

export function createUiShellNotificationModule(
  deps: UiShellNotificationDeps,
): UiShellNotificationModule {
  let hideBannerTimer: ReturnType<typeof setTimeout> | null = null;
  let bannerText = "";
  let bannerVisible = false;

  function notifyChanged(): void {
    deps.onChanged?.();
  }

  function clearScheduledHide(): void {
    if (hideBannerTimer !== null) {
      deps.window.clearTimeout(hideBannerTimer);
      hideBannerTimer = null;
    }
  }

  function clearError(): void {
    clearScheduledHide();
    bannerVisible = false;
    bannerText = "";
    notifyChanged();
  }

  return {
    clearError,
    getBannerModel() {
      return {
        hidden: !bannerVisible,
        text: bannerText,
        variant: bannerVisible ? "bad" : null,
      };
    },
    showError(message) {
      clearScheduledHide();
      bannerText = message;
      bannerVisible = true;
      notifyChanged();
      hideBannerTimer = deps.window.setTimeout(() => {
        bannerVisible = false;
        bannerText = "";
        hideBannerTimer = null;
        notifyChanged();
      }, 5000);
    },
  };
}
