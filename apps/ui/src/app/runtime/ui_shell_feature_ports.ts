import type { UiShellLanguageRefreshFeaturePorts } from "./ui_shell_language_refresh_module";

export interface UiShellFeaturePorts {
  bindSettingsHandlers(): void;
  bindCarWizardHandlers(): void;
  bindRealtimeHandlers(): void;
  bindHistoryHandlers(): void;
  bindUpdateHandlers(): void;
  bindEspFlashHandlers(): void;
  languageRefresh: UiShellLanguageRefreshFeaturePorts;
}

export function bindUiShellFeatureEvents(ports: UiShellFeaturePorts): void {
  ports.bindSettingsHandlers();
  ports.bindCarWizardHandlers();
  ports.bindRealtimeHandlers();
  ports.bindHistoryHandlers();
  ports.bindUpdateHandlers();
  ports.bindEspFlashHandlers();
}
