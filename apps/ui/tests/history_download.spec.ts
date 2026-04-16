import { expect, test } from "@playwright/test";

import {
  downloadBlobFile,
  filenameFromDisposition,
} from "../src/app/features/history_download";

test("filenameFromDisposition decodes UTF-8 and falls back when needed", () => {
  expect(
    filenameFromDisposition(
      "attachment; filename*=UTF-8''run%20%C3%BC.pdf",
      "fallback.pdf",
    ),
  ).toBe("run ü.pdf");
  expect(
    filenameFromDisposition('attachment; filename="run-001_report.pdf"', "fallback.pdf"),
  ).toBe("run-001_report.pdf");
  expect(filenameFromDisposition(null, "fallback.pdf")).toBe("fallback.pdf");
  expect(filenameFromDisposition("attachment", "fallback.pdf")).toBe("fallback.pdf");
});

test("downloadBlobFile downloads with decoded filename and revokes the blob URL", async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = (globalThis as { document?: Document }).document;
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const originalSetTimeout = globalThis.setTimeout;
  const anchorState = { href: "", download: "", clicks: 0, removed: 0 };
  const revoked: string[] = [];

  globalThis.fetch = (async () =>
    new Response("PDF", {
      status: 200,
      headers: {
        "content-type": "application/pdf",
        "content-disposition": "attachment; filename*=UTF-8''run%20%C3%BC.pdf",
      },
    })) as typeof fetch;
  (globalThis as { document?: Document }).document = {
    body: {
      appendChild() {
        /* no-op */
      },
    } as unknown as HTMLBodyElement,
    createElement(tagName: string) {
      expect(tagName).toBe("a");
      return {
        set href(value: string) {
          anchorState.href = value;
        },
        get href() {
          return anchorState.href;
        },
        set download(value: string) {
          anchorState.download = value;
        },
        get download() {
          return anchorState.download;
        },
        click() {
          anchorState.clicks += 1;
        },
        remove() {
          anchorState.removed += 1;
        },
      } as unknown as HTMLAnchorElement;
    },
  } as Document;
  URL.createObjectURL = (() => "blob:history-download-test") as typeof URL.createObjectURL;
  URL.revokeObjectURL = ((url: string) => {
    revoked.push(url);
  }) as typeof URL.revokeObjectURL;
  globalThis.setTimeout = ((handler: TimerHandler) => {
    if (typeof handler === "function") {
      handler();
    }
    return 0 as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;

  try {
    await downloadBlobFile("/api/history/run-001/report.pdf", "fallback.pdf");
  } finally {
    globalThis.fetch = originalFetch;
    (globalThis as { document?: Document }).document = originalDocument;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    globalThis.setTimeout = originalSetTimeout;
  }

  expect(anchorState.download).toBe("run ü.pdf");
  expect(anchorState.href).toBe("blob:history-download-test");
  expect(anchorState.clicks).toBe(1);
  expect(anchorState.removed).toBe(1);
  expect(revoked).toEqual(["blob:history-download-test"]);
});
