import type { RealtimeFeature } from "../features/realtime_feature";

export interface UiStartupFeaturePorts {
  dashboard: {
    hydrateStartupState(): Promise<void>;
  };
  realtime: Pick<
    RealtimeFeature,
    "refreshLocationOptions" | "refreshLoggingStatus"
  >;
}
