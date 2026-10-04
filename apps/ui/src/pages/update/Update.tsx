import type { TargetedInputEvent } from "preact";
import { useEffect, useRef } from "preact/hooks";

import {
  Card,
  InlineEmpty,
  Note,
  Pill,
  ReadinessPanel,
  StageList,
  StatusGrid,
} from "../../components/maintenance";
import { t } from "../../i18n";
import {
  activeTransport,
  canStart,
  currentStatusRows,
  currentStatusSummary,
  failureSummary,
  formatPhase,
  healthBadge,
  healthRows,
  healthSummary,
  internetBadge,
  internetRows,
  internetSummary,
  isRunning,
  journeyStages,
  latestAttemptRows,
  logPlaceholder,
  ROOT_SIDE_GIT_COMMAND,
  ROOT_SIDE_IMAGE_COMMAND,
  ROOT_SIDE_RUNBOOK_URL,
  rootSideFix,
  startLabel,
  startReadiness,
  stateBadge,
  type Transport,
  usbSummary,
} from "./update_model";
import {
  cancelUpdate,
  password,
  passwordVisible,
  ssid,
  ssidFocusRequest,
  startUpdate,
  transportChoice,
  updateView,
} from "./update_store";

function TransportChoice(props: {
  transport: Transport;
  title: string;
  summary: string;
  selected: boolean;
  /** Greyed out while USB internet is unavailable. */
  unavailable: boolean;
  inputDisabled: boolean;
}) {
  const { transport } = props;
  const wifi = transport === "wifi";
  return (
    <label
      id={wifi ? "updateTransportChoiceWifi" : "updateTransportChoiceUsb"}
      class="speed-source-choice update-transport-choice"
      data-update-transport-choice={transport}
      data-selected={props.selected ? "true" : undefined}
      data-disabled={props.unavailable ? "true" : undefined}
      data-choice-state={props.selected ? "active" : undefined}
      data-choice-badge={
        props.selected
          ? t("settings.update.transport.selected_badge")
          : undefined
      }
    >
      <input
        class="speed-source-choice__radio"
        type="radio"
        id={wifi ? "updateTransportWifiRadio" : "updateTransportUsbRadio"}
        name="updateTransport"
        value={transport}
        checked={props.selected}
        disabled={props.inputDisabled}
        onChange={() => {
          transportChoice.value = transport;
        }}
      />
      <span class="speed-source-choice__title">{props.title}</span>
      <span
        id={wifi ? undefined : "updateUsbTransportSummary"}
        class="speed-source-choice__caption"
      >
        {props.summary}
      </span>
    </label>
  );
}

export function Internet() {
  const view = updateView.value;
  const locked = isRunning(view);
  const usingUsb = activeTransport(view) === "usb_internet";
  const usable = view.internet.usable;
  const ssidInput = useRef<HTMLInputElement | null>(null);
  const focusRequest = ssidFocusRequest.value;
  useEffect(() => {
    if (focusRequest > 0) {
      ssidInput.current?.focus();
    }
  }, [focusRequest]);
  const badge = internetBadge(view.internet, t);
  const passwordInputProps = {
    id: "updatePasswordInput",
    autoComplete: "off",
    maxLength: 128,
    class: "internet-panel__input",
    value: password.value,
    disabled: locked,
    onInput: (event: TargetedInputEvent<HTMLInputElement>) => {
      password.value = event.currentTarget.value;
    },
  };
  return (
    <div class="maintenance-stack">
      <div class="panel card">
        <strong>{t("settings.internet.title")}</strong>
        <div class="subtle">{t("settings.internet.hint")}</div>
        <div
          id="internetStatusPanel"
          class="maintenance-stack internet-panel__status"
          aria-live="polite"
        >
          {view.status && view.health ? (
            <Card
              title={t("settings.internet.card_title")}
              subtitle={internetSummary(view.internet, t)}
              badge={<Pill variant={badge.variant}>{badge.text}</Pill>}
            >
              <div class="maintenance-card__body">
                <StatusGrid rows={internetRows(view.internet, t)} />
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      <Card
        title={t("settings.update.controls_title")}
        subtitle={t("settings.update.controls_intro")}
      >
        <div class="update-form">
          <div
            id="updateTransportOptions"
            class="maintenance-stack maintenance-stack--tight"
          >
            <div class="subtle">{t("settings.update.transport_label")}</div>
            <div class="speed-source-choice-grid">
              <TransportChoice
                transport="wifi"
                title={t("settings.update.transport.wifi_title")}
                summary={t("settings.update.transport.wifi_summary")}
                selected={!usingUsb}
                unavailable={false}
                inputDisabled={locked}
              />
              <TransportChoice
                transport="usb_internet"
                title={t("settings.update.transport.usb_title")}
                summary={usbSummary(view.internet, t)}
                selected={usingUsb}
                unavailable={!usable && !locked}
                inputDisabled={locked || !usable}
              />
            </div>
          </div>
          <div id="updateWifiFields" hidden={usingUsb}>
            <div class="form-group">
              <label htmlFor="updateSsidInput">
                {t("settings.update.ssid")}
              </label>
              <input
                type="text"
                id="updateSsidInput"
                ref={ssidInput}
                autoComplete="off"
                maxLength={64}
                class="internet-panel__input"
                value={ssid.value}
                disabled={locked}
                onInput={(event) => {
                  ssid.value = event.currentTarget.value;
                }}
              />
            </div>
            <div class="form-group">
              <label htmlFor="updatePasswordInput">
                {t("settings.update.password")}
              </label>
              <div class="internet-panel__input-row">
                {/* Same position and no key, so Preact keeps one <input> and only
                    flips its type; Preact's per-type input typings need literal types. */}
                {passwordVisible.value ? (
                  <input type="text" {...passwordInputProps} />
                ) : (
                  <input type="password" {...passwordInputProps} />
                )}
                <button
                  type="button"
                  id="updateTogglePasswordBtn"
                  class="btn btn--small"
                  disabled={locked}
                  onClick={() => {
                    passwordVisible.value = !passwordVisible.value;
                  }}
                >
                  <span>
                    {t(
                      passwordVisible.value
                        ? "settings.update.hide_password"
                        : "settings.update.show_password",
                    )}
                  </span>
                </button>
              </div>
            </div>
          </div>
          <div
            id="updateReadinessSummary"
            class="maintenance-stack maintenance-stack--tight"
            aria-live="polite"
          >
            <ReadinessPanel model={startReadiness(view, t)} />
          </div>
          <details class="settings-help-disclosure settings-help-disclosure--inline">
            <summary class="settings-help-disclosure__summary">
              <span class="settings-help-disclosure__heading">
                <span class="settings-help-disclosure__title">
                  {t("settings.update.details_title")}
                </span>
                <span
                  id="updateDetailsCaption"
                  class="settings-help-disclosure__caption"
                >
                  {t(
                    usingUsb
                      ? "settings.update.details_caption_usb"
                      : "settings.update.details_caption_wifi",
                  )}
                </span>
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div id="updateTransportNote" class="maintenance-note">
                {t(
                  usingUsb
                    ? "settings.update.preflight_note_usb"
                    : "settings.update.preflight_note_wifi",
                )}
              </div>
            </div>
          </details>
        </div>
      </Card>
    </div>
  );
}

function IssueDetail(props: { text: string }) {
  return <div class="issue-detail">{props.text}</div>;
}

function UpdateStatusCards() {
  const view = updateView.value;
  const { status } = view;
  if (!status || !view.health) {
    return null;
  }
  const failure = failureSummary(status, t);
  const attemptRows = latestAttemptRows(status, t);
  const placeholder = logPlaceholder(status, t);
  const running = status.state === "running";
  const badge = stateBadge(status, t);
  return (
    <>
      <div class="maintenance-pair-grid maintenance-pair-grid--focus">
        <Card
          title={t("settings.update.journey_title")}
          subtitle={t("settings.update.journey_intro")}
        >
          <div class="maintenance-card__body">
            <div class="maintenance-journey">
              {failure ? (
                <div class="maintenance-stack maintenance-stack--tight">
                  <Note bad>
                    <strong>
                      {failure.message
                        ? `${failure.phaseLabel} — ${failure.message}`
                        : failure.phaseLabel}
                    </strong>
                    {failure.detail ? (
                      <IssueDetail text={failure.detail} />
                    ) : null}
                  </Note>
                  <Note>
                    <strong>{failure.recoveryTitle}</strong>
                    <IssueDetail text={failure.recoveryDetail} />
                  </Note>
                </div>
              ) : null}
              <StageList stages={journeyStages(status, view, t)} />
            </div>
          </div>
        </Card>
        <Card
          title={t("settings.update.log")}
          subtitle={t(
            running
              ? "settings.update.log_intro_running"
              : "settings.update.log_intro",
          )}
        >
          <div class="maintenance-card__body">
            {placeholder ? (
              <InlineEmpty title={placeholder.title} body={placeholder.body} />
            ) : (
              <>
                {running ? (
                  <Note>{t("settings.update.log_running_note")}</Note>
                ) : null}
                <pre class="log-pre">
                  {status.log_tail.map((line) => `${line}\n`).join("")}
                </pre>
              </>
            )}
          </div>
        </Card>
      </div>
      {attemptRows ? (
        <Card
          title={t("settings.update.attempt_title")}
          subtitle={t("settings.update.attempt_intro")}
          badge={<Pill variant={badge.variant}>{badge.text}</Pill>}
        >
          <div class="maintenance-card__body">
            <StatusGrid rows={attemptRows} />
            {failure ? (
              <Note bad>
                <strong>{failure.message ?? failure.phaseLabel}</strong>
                {failure.detail ? <IssueDetail text={failure.detail} /> : null}
              </Note>
            ) : null}
          </div>
        </Card>
      ) : null}
      {status.issues.length > 0 ? (
        <Card
          title={t("settings.update.issues")}
          subtitle={t("settings.update.issues_intro")}
        >
          <div class="maintenance-card__body">
            <ul class="issue-list">
              {status.issues.map((issue, index) => (
                <li class="issue-item" key={`${issue.phase}:${index}`}>
                  <div class="issue-phase">{formatPhase(issue.phase, t)}</div>
                  <div>
                    <strong>{issue.message}</strong>
                    {issue.detail ? <IssueDetail text={issue.detail} /> : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      ) : null}
    </>
  );
}

/** Root-side helpers that do not match this app: what fails and how to fix it. */
function RootSideNote() {
  const fix = rootSideFix(updateView.value, t);
  if (!fix) {
    return null;
  }
  return (
    <Note bad>
      <div
        id="rootSideOutdatedNote"
        class="maintenance-stack maintenance-stack--tight"
      >
        <span>{fix.summary}</span>
        <span>
          {fix.imageStep} <code>{ROOT_SIDE_IMAGE_COMMAND}</code>
        </span>
        <span>
          {fix.gitStep} <code>{ROOT_SIDE_GIT_COMMAND}</code>
        </span>
        <a
          href={ROOT_SIDE_RUNBOOK_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          {fix.runbookLabel}
        </a>
      </div>
    </Note>
  );
}

function UpdateOverview() {
  const { status, health } = updateView.value;
  if (!status || !health) {
    return null;
  }
  const rows = currentStatusRows(status, t);
  const badge = stateBadge(status, t);
  const healthState = healthBadge(health, t);
  return (
    <div class="maintenance-pair-grid maintenance-pair-grid--summary">
      <Card
        title={t("settings.update.current_status_title")}
        subtitle={currentStatusSummary(status, health, t)}
        badge={<Pill variant={badge.variant}>{badge.text}</Pill>}
      >
        <div class="maintenance-card__body">
          {rows.length > 0 ? (
            <StatusGrid rows={rows} />
          ) : (
            <Note>{t("settings.update.current_status_empty")}</Note>
          )}
        </div>
      </Card>
      <Card
        title={t("settings.update.health_card_title")}
        subtitle={healthSummary(health, t)}
        badge={<Pill variant={healthState.variant}>{healthState.text}</Pill>}
      >
        <div class="maintenance-card__body">
          <RootSideNote />
          <StatusGrid rows={healthRows(health, t)} />
        </div>
      </Card>
    </div>
  );
}

export function Update() {
  const view = updateView.value;
  const running = isRunning(view);
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <Card
          hero
          title={t("settings.update.title")}
          subtitle={t("settings.update.hint")}
        >
          <div class="maintenance-card__body maintenance-card__body--hero">
            <Note>{t("settings.update.reconnect_note")}</Note>
            <div
              id="updateOverviewPanel"
              class="maintenance-stack maintenance-stack--tight"
              aria-live="polite"
            >
              <UpdateOverview />
            </div>
            <div class="maintenance-action-row">
              <button
                type="button"
                id="updateStartBtn"
                class="btn btn--success"
                hidden={running}
                disabled={!canStart(view, t)}
                onClick={() => void startUpdate()}
              >
                {startLabel(view, t)}
              </button>
              <button
                type="button"
                id="updateCancelBtn"
                class="btn btn--danger"
                hidden={!running}
                disabled={!running}
                onClick={() => void cancelUpdate()}
              >
                {t("settings.update.cancel")}
              </button>
            </div>
          </div>
        </Card>
        <div
          id="updateStatusPanel"
          class="maintenance-stack maintenance-stack--tight"
          aria-live="polite"
        >
          <UpdateStatusCards />
        </div>
      </div>
    </div>
  );
}
