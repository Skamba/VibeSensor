import { afterEach, expect, test } from "vitest";

import { lang, normalizeLang, setLanguage, t, translate } from "../src/i18n";

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

test("a count of one reads singular, others plural, in both languages", async () => {
  await setLanguage("nl");
  const key =
    "dashboard.capture_readiness.sensors_ready.limited_sensor_coverage";
  expect(translate("nl", key, { count: 1 })).toBe(
    "Er is maar 1 live sensor actief, dus het rapport kan niet zeggen op welke plek de trilling het sterkst is.",
  );
  expect(translate("nl", key, { count: 2 })).toBe(
    "Er zijn maar 2 live sensoren actief, dus de locatierangschikking is zwakker.",
  );
  expect(translate("en", key, { count: 1 })).toBe(
    "Only 1 live sensor is active, so the report can't tell where the vibration is strongest.",
  );
  expect(translate("en", "history.available_count", { count: 1 })).toBe(
    "1 run available",
  );
  expect(translate("en", "history.available_count", { count: 3 })).toBe(
    "3 runs available",
  );
});

test("no counted text hedges its plural with (s) or (en)", async () => {
  await setLanguage("nl");
  const hedged = /\w\((s|en)\)/;
  for (const language of ["en", "nl"] as const) {
    const catalog = (
      language === "en"
        ? (await import("../src/i18n/catalogs/en.json")).default
        : (await import("../src/i18n/catalogs/nl.json")).default
    ) as Record<string, string>;
    const offenders = Object.entries(catalog).filter(([, text]) =>
      hedged.test(text),
    );
    expect(offenders, language).toEqual([]);
  }
});
