export const serverStateQueryKeys = {
  realtime: {
    clientLocations: () => ["realtime", "client-locations"] as const,
    loggingStatus: () => ["realtime", "logging-status"] as const,
  },
  settings: {
    analysis: () => ["settings", "analysis"] as const,
    cars: () => ["settings", "cars"] as const,
    gpsStatus: () => ["settings", "gps-status"] as const,
    language: () => ["settings", "language"] as const,
    speedSource: () => ["settings", "speed-source"] as const,
    speedSourceObdScan: () => ["settings", "speed-source", "obd-scan"] as const,
    speedUnit: () => ["settings", "speed-unit"] as const,
  },
  history: {
    insights: (runId: string, lang: string) =>
      ["history", "insights", runId, lang] as const,
    insightsPrefix: (runId: string) => ["history", "insights", runId] as const,
    runs: () => ["history", "runs"] as const,
  },
  carsWizard: {
    brands: () => ["cars", "wizard", "brands"] as const,
    models: (brand: string, carType: string) =>
      ["cars", "wizard", "models", brand, carType] as const,
    types: (brand: string) => ["cars", "wizard", "types", brand] as const,
  },
  update: {
    statusSnapshot: () => ["update", "status-snapshot"] as const,
  },
  espFlash: {
    ports: () => ["esp-flash", "ports"] as const,
    statusSnapshot: () => ["esp-flash", "status-snapshot"] as const,
  },
} as const;
