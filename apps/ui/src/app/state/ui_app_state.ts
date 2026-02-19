export type UiAppState = {
  started: boolean;
};

export function createUiAppState(): UiAppState {
  return { started: false };
}
