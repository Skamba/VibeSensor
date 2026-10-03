import { afterEach, expect, test } from "vitest";

import {
  lang,
  normalizeLang,
  setLanguage,
  t,
  translate,
  translationsOf,
} from "../src/i18n";

afterEach(async () => {
  await setLanguage("en");
});

test("normalizes language tags to a supported language", () => {
  expect(normalizeLang("nl-BE")).toBe("nl");
  expect(normalizeLang(" NL ")).toBe("nl");
  expect(normalizeLang("de")).toBe("en");
  expect(normalizeLang(null)).toBe("en");
});

test("loads the Dutch catalog before switching language", async () => {
  expect(t("settings.language")).toBe("Language");
  await setLanguage("nl");
  expect(lang.value).toBe("nl");
  expect(t("settings.language")).toBe("Taal");
  expect(document.documentElement.getAttribute("lang")).toBe("nl");
});

test("falls back to English, then to the key", async () => {
  await setLanguage("nl");
  expect(t("no.such.key")).toBe("no.such.key");
  expect(translate("en", "nav.history")).toBe("History");
});

test("fills placeholders and formats numbers per language", () => {
  expect(translate("en", "speed.none", { unit: "km/h" })).toBe("-- km/h");
  expect(
    translate("nl", "settings.speed.obd_scan_found", { count: 1234.5 }),
  ).toContain("1.234,5");
  expect(translate("en", "speed.none", { unit: Number.NaN })).toBe("-- --");
  expect(translate("en", "speed.none", {})).toBe("-- {unit}");
});

test("lists a key's text in every loaded language", async () => {
  await setLanguage("nl");
  expect(translationsOf("nav.history")).toEqual(["History", "Geschiedenis"]);
});
