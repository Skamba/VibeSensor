import {
  useSignalProperties,
  type ReadonlySignal,
} from "../../ui_signals";
import {
  settingsFeedbackAttrs,
  type SettingsFeedbackMessage,
} from "../../views/settings_feedback";
import {
  SHELL_PREFERENCES_MODEL_KEYS,
  SPEED_UNIT_OPTIONS,
  type UiShellChromeActions,
  type UiShellChromePreferencesModel,
} from "./ui_shell_chrome_shared";

const LANGUAGE_OPTIONS = [
  { label: "🇺🇸 English", value: "en" },
  { label: "🇳🇱 Nederlands", value: "nl" },
] as const;

export function ShellPreferences(props: {
  actions: ReadonlySignal<UiShellChromeActions>;
  preferencesModel: ReadonlySignal<UiShellChromePreferencesModel>;
}) {
  const { actions, preferencesModel } = props;
  const {
    languageFeedback,
    languageLabelText,
    selectedLanguage,
    selectedSpeedUnit,
    speedUnitFeedback,
    speedUnitLabelText,
    speedUnitOptionLabels,
  } = useSignalProperties(preferencesModel, SHELL_PREFERENCES_MODEL_KEYS);

  return (
    <div class="site-header__preferences">
      <label class="header-select" htmlFor="speedUnitSelect">
        <span class="mini-label">{speedUnitLabelText}</span>
        <select
          id="speedUnitSelect"
          class="unit-picker"
          aria-label={speedUnitLabelText}
          aria-describedby={speedUnitFeedback.value ? "speedUnitFeedback" : undefined}
          aria-invalid={speedUnitFeedback.value?.tone === "error" ? "true" : undefined}
          value={selectedSpeedUnit}
          onChange={(event) => {
            void actions.value.saveSpeedUnit(event.currentTarget.value);
          }}
        >
          {SPEED_UNIT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {speedUnitOptionLabels.value[option.value] ?? option.fallbackLabel}
            </option>
          ))}
        </select>
        <SettingsFeedbackSlot id="speedUnitFeedback" message={speedUnitFeedback} />
      </label>
      <label class="header-select" htmlFor="languageSelect">
        <span class="mini-label">{languageLabelText}</span>
        <select
          id="languageSelect"
          class="lang-picker"
          aria-label={languageLabelText}
          aria-describedby={languageFeedback.value ? "languageFeedback" : undefined}
          aria-invalid={languageFeedback.value?.tone === "error" ? "true" : undefined}
          value={selectedLanguage}
          onChange={(event) => {
            void actions.value.saveLanguage(event.currentTarget.value);
          }}
        >
          {LANGUAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <SettingsFeedbackSlot id="languageFeedback" message={languageFeedback} />
      </label>
    </div>
  );
}

function SettingsFeedbackSlot(props: {
  id: string;
  message: ReadonlySignal<SettingsFeedbackMessage | null>;
}) {
  const { id, message } = props;
  const currentMessage = message.value;
  const ariaLive = currentMessage
    ? currentMessage.tone === "error" ? "assertive" : "polite"
    : undefined;

  return (
    <div
      id={id}
      class="settings-feedback-slot settings-feedback-slot--compact"
      hidden={!currentMessage}
      aria-live={ariaLive}
    >
      {currentMessage ? (
        <div {...settingsFeedbackAttrs(currentMessage)}>
          {currentMessage.title ? (
            <strong class="settings-feedback__title">{currentMessage.title}</strong>
          ) : null}
          <span class="settings-feedback__body">{currentMessage.body}</span>
          {currentMessage.detail ? (
            <span class="settings-feedback__detail">{currentMessage.detail}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
