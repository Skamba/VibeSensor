import { beforeEach, describe, expect, test, vi } from "vitest";
import { uiLogger } from "../src/ui_logger";

describe("uiLogger", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("warn forwards message-only and message-plus-error calls", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const error = new Error("warn detail");

    uiLogger.warn("message only");
    uiLogger.warn("message with error", error);

    expect(warn).toHaveBeenNthCalledWith(1, "message only");
    expect(warn).toHaveBeenNthCalledWith(2, "message with error", error);
  });

  test("error forwards message-only and message-plus-error calls", () => {
    const errorLog = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const error = new Error("error detail");

    uiLogger.error("message only");
    uiLogger.error("message with error", error);

    expect(errorLog).toHaveBeenNthCalledWith(1, "message only");
    expect(errorLog).toHaveBeenNthCalledWith(2, "message with error", error);
  });
});
