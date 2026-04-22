import { beforeEach, expect, test } from "vitest";

import { getUiText, setUiLanguage } from "../src/app/ui_i18n";

beforeEach(async () => {
  await setUiLanguage("en");
});

test("loads the active catalog before switching UI language", async () => {
  expect(getUiText("settings.language", "Language")).toBe("Language");

  await setUiLanguage("nl");

  expect(getUiText("settings.language", "Language")).toBe("Taal");
  expect(getUiText("dashboard.sensor_unassigned", "Location unassigned")).toBe(
    "Locatie niet toegewezen",
  );
});
