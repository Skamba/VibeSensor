import type { JSX } from "preact";

import { HistoryHeatmap } from "./history_heatmap_section";
import type {
  HistoryDetailsViewModel,
  HistoryInsightsViewModel,
  HistoryPrimaryFindingViewModel,
  HistoryRowViewModel,
  HistorySecondaryFindingViewModel,
} from "./history_table_models";
import type {
  HistoryPanelActionHandlers,
  HistoryRunAction,
} from "./history_table_view";

function HistoryPrimaryFinding(props: { primary: HistoryPrimaryFindingViewModel }) {
  const { primary } = props;
  return (
    <div class="history-findings-overview">
      <div class="history-findings-overview__header">
        <div class="history-findings-overview__eyebrow">{primary.eyebrow}</div>
      </div>
      <div class={`history-diagnosis-card history-diagnosis-card--${primary.tone}`}>
        <div class="history-diagnosis-card__header">
          <div class="history-diagnosis-card__copy">
            <div class="history-findings-overview__headline">{primary.headline}</div>
            <div class="history-diagnosis-card__signature">{primary.signature}</div>
          </div>
          <span class={`history-diagnosis-card__confidence history-diagnosis-card__confidence--${primary.tone}`}>
            {primary.confidence}
          </span>
        </div>
        {primary.explanation ? (
          <p class="history-findings-overview__explanation">{primary.explanation}</p>
        ) : null}
        <div class="history-findings-overview__chips">
          {primary.chips.map((chip, index) => (
            <div key={`${chip.label}:${index}`} class="history-findings-chip">
              <span class="history-findings-chip__label">{chip.label}</span>
              <strong>{chip.value}</strong>
            </div>
          ))}
        </div>
        {primary.nextStep && primary.nextStepLabel ? (
          <div class="history-diagnosis-card__next-step">
            <span class="history-diagnosis-card__next-step-label">{primary.nextStepLabel}</span>
            <strong>{primary.nextStep}</strong>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function HistorySecondaryFindingCard(props: { finding: HistorySecondaryFindingViewModel }) {
  const { finding } = props;
  return (
    <li class={`history-finding-card history-finding-card--secondary history-finding-card--${finding.tone}`}>
      <div class="history-finding-card__header">
        <div class="history-finding-card__title-group">
          <strong class="history-finding-card__title">{finding.source}</strong>
          <span class="history-finding-card__signal">{finding.signature}</span>
        </div>
        <span class={`history-finding-card__confidence history-finding-card__confidence--${finding.tone}`}>
          {finding.confidence}
        </span>
      </div>
      <div class="history-finding-card__meta">
        <div class="history-finding-card__meta-item">
          <span class="history-finding-card__label">{finding.locationLabel}</span>
          <strong>{finding.location}</strong>
        </div>
        <div class="history-finding-card__meta-item">
          <span class="history-finding-card__label">{finding.speedBandLabel}</span>
          <strong>{finding.speedBand}</strong>
        </div>
      </div>
      <p class="history-finding-card__summary">{finding.evidenceSummary}</p>
    </li>
  );
}

function HistoryInsightsBlock(props: { insights: HistoryInsightsViewModel }) {
  const { insights } = props;

  let body: JSX.Element;
  if (insights.primary) {
    body = (
      <>
        <HistoryPrimaryFinding primary={insights.primary} />
        {insights.secondaryTitle ? (
          <div class="history-secondary-findings">
            <div class="history-secondary-findings__title">{insights.secondaryTitle}</div>
            <ul class="history-findings-list history-findings-list--secondary">
              {insights.visibleSecondary.map((finding, index) => (
                <HistorySecondaryFindingCard
                  key={`${finding.source}:${finding.signature}:${index}`}
                  finding={finding}
                />
              ))}
            </ul>
            {insights.hiddenSecondary.length > 0 && insights.showMoreLabel ? (
              <details class="history-secondary-findings__more">
                <summary>{insights.showMoreLabel}</summary>
                <ul class="history-findings-list history-findings-list--secondary">
                  {insights.hiddenSecondary.map((finding, index) => (
                    <HistorySecondaryFindingCard
                      key={`${finding.source}:${finding.signature}:hidden:${index}`}
                      finding={finding}
                    />
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}
      </>
    );
  } else if (insights.emptyMessage) {
    body = (
      <ul class="history-findings-list history-findings-list--secondary">
        <li class="history-finding-card history-finding-card--empty">{insights.emptyMessage}</li>
      </ul>
    );
  } else {
    body = <div class="history-panel-state">{insights.stateMessage ?? ""}</div>;
  }

  return (
    <div class="history-insights-block">
      <div class="history-panel-header">
        <div class="history-panel-header__eyebrow">{insights.headerEyebrow}</div>
      </div>
      {body}
    </div>
  );
}

function HistoryWarnings(props: { warnings: HistoryDetailsViewModel["warnings"] }) {
  const { warnings } = props;
  if (!warnings.length) {
    return null;
  }
  return (
    <div class="history-warning-list">
      {warnings.map((warning, index) => (
        <div
          key={`${warning.severity}:${warning.title}:${index}`}
          class={`history-warning-banner history-warning-banner--${warning.severity}`}
        >
          <strong>{warning.title}</strong>
          {warning.detail ? (
            <div class="history-warning-banner__detail">{warning.detail}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function HistoryRunActionsPanel(props: {
  details: HistoryDetailsViewModel;
  historyExportUrl: (runId: string) => string;
  onRunAction(
    event: JSX.TargetedMouseEvent<HTMLElement>,
    action: HistoryRunAction,
    runId: string,
  ): void;
  onStopRowToggle(event: JSX.TargetedMouseEvent<HTMLElement>): void;
  row: HistoryRowViewModel;
}) {
  const { details, historyExportUrl, onRunAction, onStopRowToggle, row } = props;
  return (
    <div class="history-details-footer">
      <div class="history-details-footer__copy">
        <div class="history-details-footer__eyebrow">{details.footerEyebrow}</div>
        <div class="history-details-footer__body">{details.footerBody}</div>
      </div>
      <div class="history-details-footer__actions">
        <a
          class="btn btn--muted"
          href={historyExportUrl(row.runId)}
          download={`${row.runId}.zip`}
          data-run-action="download-raw"
          data-run={row.runId}
          onClick={onStopRowToggle}
        >
          {details.exportLabel}
        </a>
        <button
          class="btn btn--danger-quiet"
          type="button"
          data-run-action="delete-run"
          data-run={row.runId}
          onClick={(event) => onRunAction(event, "delete-run", row.runId)}
        >
          {details.deleteLabel}
        </button>
      </div>
    </div>
  );
}

export function HistoryDetailsRow(props: {
  details: HistoryDetailsViewModel;
  historyExportUrl: (runId: string) => string;
  onRunAction(
    event: JSX.TargetedMouseEvent<HTMLElement>,
    action: HistoryRunAction,
    runId: string,
  ): void;
  onStopRowToggle(event: JSX.TargetedMouseEvent<HTMLElement>): void;
  row: HistoryRowViewModel;
}) {
  const { details, historyExportUrl, onRunAction, onStopRowToggle, row } = props;
  return (
    <tr class="history-details-row">
      <td colSpan={4}>
        <div class="history-details-card">
          <div class="history-details-header">
            <div class="history-details-header__copy">
              <div class="history-details-header__eyebrow">{details.titleEyebrow}</div>
              <div class="history-details-header__title">{details.title}</div>
              {details.runSummary ? (
                <div class="history-run-summary">{details.runSummary}</div>
              ) : null}
            </div>
            <div class="history-details-header__actions">
              {details.reloadActionLabel ? (
                <button
                  class="btn btn--muted"
                  type="button"
                  disabled={details.reloadActionDisabled}
                  data-run-action="load-insights"
                  data-run={row.runId}
                  onClick={(event) => onRunAction(event, "load-insights", row.runId)}
                >
                  {details.reloadActionLabel}
                </button>
              ) : details.loadingStatusText ? (
                <div class="history-details-header__status">{details.loadingStatusText}</div>
              ) : null}
              {details.insightsError ? (
                <span class="history-inline-error">{details.insightsError}</span>
              ) : null}
            </div>
          </div>
          <HistoryWarnings warnings={details.warnings} />
          <div class="history-results-layout">
            <div class="history-main-column">
              <HistoryInsightsBlock insights={details.insights} />
              <HistoryRunActionsPanel
                details={details}
                historyExportUrl={historyExportUrl}
                onRunAction={onRunAction}
                onStopRowToggle={onStopRowToggle}
                row={row}
              />
            </div>
            <div class="history-evidence-column">
              <div class="history-evidence-panel">
                <HistoryHeatmap heatmap={details.heatmap} />
              </div>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}
