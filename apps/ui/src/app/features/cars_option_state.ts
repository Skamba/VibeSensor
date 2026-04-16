export type CarsFeatureOptionsStatus = "idle" | "loading" | "error" | "ready";

export interface CarsFeatureOptionsState<TOption> {
  message: string | null;
  options: readonly TOption[];
  status: CarsFeatureOptionsStatus;
}

export function createIdleOptionsState<TOption>(): CarsFeatureOptionsState<TOption> {
  return {
    message: null,
    options: [],
    status: "idle",
  };
}

export function createErrorOptionsState<TOption>(message: string): CarsFeatureOptionsState<TOption> {
  return {
    message,
    options: [],
    status: "error",
  };
}

export function createLoadingOptionsState<TOption>(message: string): CarsFeatureOptionsState<TOption> {
  return {
    message,
    options: [],
    status: "loading",
  };
}

export function createReadyOptionsState<TOption>(
  options: readonly TOption[],
): CarsFeatureOptionsState<TOption> {
  return {
    message: null,
    options: [...options],
    status: "ready",
  };
}
