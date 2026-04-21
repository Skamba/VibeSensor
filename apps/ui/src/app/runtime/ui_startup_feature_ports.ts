import type { RealtimeFeature } from "../features/realtime_feature";

export interface UiStartupFeaturePorts {
  realtime: Pick<RealtimeFeature, "refreshLocationOptions" | "refreshLoggingStatus">;
}
