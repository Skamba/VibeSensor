import { startUiApp } from "./app/start_ui_app";

async function bootstrapUi(): Promise<void> {
  const mockMode =
    import.meta.env.MODE === "msw" ||
    import.meta.env.VITE_UI_MSW_MODE === "browser";
  if (mockMode) {
    const { startBrowserMocksIfEnabled } = await import("./mocks/browser");
    await startBrowserMocksIfEnabled();
  }
  startUiApp();
}

void bootstrapUi();
