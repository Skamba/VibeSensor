export type LegacyFeatureDeps = {
  startLegacyUiApp: () => void;
};

export class LegacyFeatureController {
  constructor(private readonly deps: LegacyFeatureDeps) {}

  start(): void {
    this.deps.startLegacyUiApp();
  }
}
