import { UiAppContext, type UiAppContextDeps } from "../context/ui_app_context";
import { UiAppController } from "../controllers/ui_app_controller";
import { CarsFeatureFactory } from "./cars_feature_factory";
import { DashboardFeatureFactory } from "./dashboard_feature_factory";
import { DemoFeatureFactory } from "./demo_feature_factory";
import { HistoryFeatureFactory } from "./history_feature_factory";
import { RealtimeFeatureFactory } from "./realtime_feature_factory";
import { SettingsFeatureFactory } from "./settings_feature_factory";

export type UiAppFactoryDeps = UiAppContextDeps;

export class UiAppFactory {
  constructor(private readonly deps: UiAppFactoryDeps) {}

  create(): UiAppController {
    const context = new UiAppContext(this.deps);
    const features = [
      new DashboardFeatureFactory().create(context),
      new HistoryFeatureFactory().create(context),
      new SettingsFeatureFactory().create(context),
      new CarsFeatureFactory().create(context),
      new RealtimeFeatureFactory().create(context),
      new DemoFeatureFactory().create(context),
    ];
    return new UiAppController(features);
  }
}
