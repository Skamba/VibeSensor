export interface UiRecordingHistoryRefreshDeps {
  refreshHistory: () => Promise<void>;
}

export interface UiRecordingHistoryRefresh {
  onRecordingStatusChanged(): Promise<void>;
}

export function createUiRecordingHistoryRefresh(
  deps: UiRecordingHistoryRefreshDeps,
): UiRecordingHistoryRefresh {
  return {
    onRecordingStatusChanged(): Promise<void> {
      return deps.refreshHistory();
    },
  };
}
