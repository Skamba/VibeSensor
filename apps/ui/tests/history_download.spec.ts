import { expect, test } from "vitest";

import { filenameFromDisposition } from "../src/pages/history/download";

test("filenameFromDisposition decodes UTF-8 and falls back when needed", () => {
  expect(
    filenameFromDisposition(
      "attachment; filename*=UTF-8''run%20%C3%BC.pdf",
      "fallback.pdf",
    ),
  ).toBe("run ü.pdf");
  expect(
    filenameFromDisposition(
      'attachment; filename="run-001_report.pdf"',
      "fallback.pdf",
    ),
  ).toBe("run-001_report.pdf");
  expect(filenameFromDisposition(null, "fallback.pdf")).toBe("fallback.pdf");
  expect(filenameFromDisposition("attachment", "fallback.pdf")).toBe(
    "fallback.pdf",
  );
});
