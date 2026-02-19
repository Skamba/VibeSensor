import type { UiAppFeatureController } from "../types/ui_app_feature";

export class UiAppController {
  constructor(private readonly features: UiAppFeatureController[]) {}

  start(): void {
    this.features.forEach((feature) => feature.start());
  }
}
