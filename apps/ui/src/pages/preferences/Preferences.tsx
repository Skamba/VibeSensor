import {
  languageFeedback,
  saveLanguage,
  saveSpeedUnit,
  selectedLanguage,
  selectedSpeedUnit,
  speedUnitFeedback,
} from "../../app_store";
import { FeedbackSlot } from "../../components/feedback";
import { t } from "../../i18n";

/** Settings → General: the speed unit and the language, saved on the Pi. */
export function Preferences() {
  return (
    <div class="panel card settings-layout">
      <div class="settings-groups">
        <section class="settings-group">
          <h3>{t("settings.general.display")}</h3>
          <div class="settings-subgrid settings-subgrid--aligned-labels">
            <div class="field">
              <label htmlFor="speedUnitSelect">{t("speed.unit")}</label>
              <select
                id="speedUnitSelect"
                class="unit-picker"
                aria-describedby={
                  speedUnitFeedback.value ? "speedUnitFeedback" : undefined
                }
                aria-invalid={
                  speedUnitFeedback.value?.tone === "error" ? "true" : undefined
                }
                value={selectedSpeedUnit.value}
                onChange={(event) =>
                  void saveSpeedUnit(event.currentTarget.value)
                }
              >
                <option value="kmh">{t("speed.unit.kmh")}</option>
                <option value="mps">{t("speed.unit.mps")}</option>
              </select>
              <FeedbackSlot
                id="speedUnitFeedback"
                message={speedUnitFeedback.value}
                compact
              />
            </div>
            <div class="field">
              <label htmlFor="languageSelect">{t("settings.language")}</label>
              <select
                id="languageSelect"
                class="lang-picker"
                aria-describedby={
                  languageFeedback.value ? "languageFeedback" : undefined
                }
                aria-invalid={
                  languageFeedback.value?.tone === "error" ? "true" : undefined
                }
                value={selectedLanguage.value}
                onChange={(event) =>
                  void saveLanguage(event.currentTarget.value)
                }
              >
                <option value="en">🇺🇸 English</option>
                <option value="nl">🇳🇱 Nederlands</option>
              </select>
              <FeedbackSlot
                id="languageFeedback"
                message={languageFeedback.value}
                compact
              />
            </div>
          </div>
          <div class="subtle settings-field-guidance">
            {t("settings.general.display_hint")}
          </div>
        </section>
      </div>
    </div>
  );
}
