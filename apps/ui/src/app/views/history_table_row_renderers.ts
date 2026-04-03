import type { HistoryRowViewModel, HistorySummaryChipTone } from "./history_table_models";

type HistoryTableRendererParams = {
  escapeHtml: (value: unknown) => string;
  historyExportUrl: (runId: string) => string;
};

function chipModifier(tone: HistorySummaryChipTone): string {
  switch (tone) {
    case "default":
      return "";
    case "source":
      return " history-row__summary-chip--source";
    default:
      return ` history-row__summary-chip--${tone}`;
  }
}

function renderSummaryChips(
  chips: HistoryRowViewModel["summaryChips"],
  escapeHtml: HistoryTableRendererParams["escapeHtml"],
): string {
  return `<div class="history-row__summary-chips">${chips
    .map(
      (chip) =>
        `<span class="history-row__summary-chip${chipModifier(chip.tone)}">${escapeHtml(chip.text)}</span>`,
    )
    .join("")}</div>`;
}

function renderCollapsedRowActions(
  row: HistoryRowViewModel,
  params: HistoryTableRendererParams,
): string {
  const { escapeHtml } = params;
  if (row.collapsedAction.hintText) {
    return `<div class="history-row__action-hint">${escapeHtml(row.collapsedAction.hintText)}</div>`;
  }
  return `
      <div class="table-actions history-row__actions">
        <button class="btn btn--muted" data-run-action="download-pdf" data-run="${escapeHtml(row.runId)}" ${row.collapsedAction.pdfLoading ? "disabled" : ""}>${escapeHtml(row.collapsedAction.pdfLabel ?? "")}</button>
      </div>
    `;
}

function renderHeatmap(
  heatmap: NonNullable<HistoryRowViewModel["details"]>["heatmap"],
  escapeHtml: HistoryTableRendererParams["escapeHtml"],
): string {
  if (heatmap.stateMessage) {
    const messageClass =
      heatmap.stateTone === "error" ? "history-inline-error" : "subtle";
    return `
      <div class="history-heatmap">
        <div class="history-heatmap__header">
          <div class="history-heatmap__title">${escapeHtml(heatmap.title)}</div>
        </div>
        <p class="${messageClass}">${escapeHtml(heatmap.stateMessage)}</p>
      </div>
    `;
  }
  const zones = heatmap.zones
    .map((zone) => {
      if (zone.valueLabel === null || zone.accentColor === null || zone.fillPercent === null) {
        return `
          <div
            class="history-heatmap__zone history-heatmap__zone--empty"
            data-location-key="${escapeHtml(zone.key)}"
            style="grid-area:${zone.gridArea}"
            title="${escapeHtml(zone.label)}"
          >
            <div class="history-heatmap__zone-label">${escapeHtml(zone.label)}</div>
            <div class="history-heatmap__zone-value history-heatmap__zone-value--empty">${escapeHtml(zone.valueLabel)}</div>
            <div class="history-heatmap__zone-meter" aria-hidden="true"></div>
          </div>
        `;
      }
      return `
        <div
          class="history-heatmap__zone${zone.strongest ? " history-heatmap__zone--strongest" : ""}"
          data-location-key="${escapeHtml(zone.key)}"
          style="grid-area:${zone.gridArea};--history-heatmap-accent:${zone.accentColor};--history-heatmap-fill:${zone.fillPercent}%;"
          title="${escapeHtml(zone.label)}: ${escapeHtml(zone.valueLabel)}"
        >
          <div class="history-heatmap__zone-label">${escapeHtml(zone.label)}</div>
          <div class="history-heatmap__zone-value">${escapeHtml(zone.valueLabel)}</div>
          <div class="history-heatmap__zone-meter" aria-hidden="true">
            <span class="history-heatmap__zone-meter-fill"></span>
          </div>
        </div>
      `;
    })
    .join("");
  const extrasMarkup = heatmap.extras.length
    ? `<div class="history-heatmap__extras">${heatmap.extras
        .map((extra) => `<div class="history-heatmap__extra-chip">${escapeHtml(extra)}</div>`)
        .join("")}</div>`
    : "";
  return `
      <div class="history-heatmap">
        <div class="history-heatmap__header">
          <div class="history-heatmap__title">${escapeHtml(heatmap.title)}</div>
        </div>
        <div class="history-heatmap__grid">${zones}</div>
        ${extrasMarkup}
      </div>
    `;
}

function renderPrimaryFinding(
  primary: NonNullable<NonNullable<HistoryRowViewModel["details"]>["insights"]["primary"]>,
  escapeHtml: HistoryTableRendererParams["escapeHtml"],
): string {
  return `
      <div class="history-findings-overview">
        <div class="history-findings-overview__header">
          <div class="history-findings-overview__eyebrow">${escapeHtml(primary.eyebrow)}</div>
        </div>
        <div class="history-diagnosis-card history-diagnosis-card--${primary.tone}">
          <div class="history-diagnosis-card__header">
            <div class="history-diagnosis-card__copy">
              <div class="history-findings-overview__headline">${escapeHtml(primary.headline)}</div>
              <div class="history-diagnosis-card__signature">${escapeHtml(primary.signature)}</div>
            </div>
            <span class="history-diagnosis-card__confidence history-diagnosis-card__confidence--${primary.tone}">${escapeHtml(primary.confidence)}</span>
          </div>
          ${primary.explanation ? `<p class="history-findings-overview__explanation">${escapeHtml(primary.explanation)}</p>` : ""}
          <div class="history-findings-overview__chips">${primary.chips
            .map(
              (chip) => `
                <div class="history-findings-chip">
                  <span class="history-findings-chip__label">${escapeHtml(chip.label)}</span>
                  <strong>${escapeHtml(chip.value)}</strong>
                </div>
              `,
            )
            .join("")}</div>
          ${primary.nextStep && primary.nextStepLabel
            ? `<div class="history-diagnosis-card__next-step"><span class="history-diagnosis-card__next-step-label">${escapeHtml(primary.nextStepLabel)}</span><strong>${escapeHtml(primary.nextStep)}</strong></div>`
            : ""}
        </div>
      </div>
    `;
}

function renderSecondaryFinding(
  finding: NonNullable<HistoryRowViewModel["details"]>["insights"]["visibleSecondary"][number],
  escapeHtml: HistoryTableRendererParams["escapeHtml"],
): string {
  return `
      <li class="history-finding-card history-finding-card--secondary history-finding-card--${finding.tone}">
        <div class="history-finding-card__header">
          <div class="history-finding-card__title-group">
            <strong class="history-finding-card__title">${escapeHtml(finding.source)}</strong>
            <span class="history-finding-card__signal">${escapeHtml(finding.signature)}</span>
          </div>
          <span class="history-finding-card__confidence history-finding-card__confidence--${finding.tone}">${escapeHtml(finding.confidence)}</span>
        </div>
        <div class="history-finding-card__meta">
          <div class="history-finding-card__meta-item">
            <span class="history-finding-card__label">${escapeHtml(finding.locationLabel)}</span>
            <strong>${escapeHtml(finding.location)}</strong>
          </div>
          <div class="history-finding-card__meta-item">
            <span class="history-finding-card__label">${escapeHtml(finding.speedBandLabel)}</span>
            <strong>${escapeHtml(finding.speedBand)}</strong>
          </div>
        </div>
        <p class="history-finding-card__summary">${escapeHtml(finding.evidenceSummary)}</p>
      </li>`;
}

function renderInsights(
  insights: NonNullable<HistoryRowViewModel["details"]>["insights"],
  escapeHtml: HistoryTableRendererParams["escapeHtml"],
): string {
  let body = `<div class="history-panel-state">${escapeHtml(insights.stateMessage ?? "")}</div>`;
  if (insights.primary) {
    body = `${renderPrimaryFinding(insights.primary, escapeHtml)}${insights.secondaryTitle
      ? `
            <div class="history-secondary-findings">
              <div class="history-secondary-findings__title">${escapeHtml(insights.secondaryTitle)}</div>
              <ul class="history-findings-list history-findings-list--secondary">
                ${insights.visibleSecondary
                  .map((finding) => renderSecondaryFinding(finding, escapeHtml))
                  .join("")}
              </ul>
              ${insights.hiddenSecondary.length && insights.showMoreLabel
                ? `
                    <details class="history-secondary-findings__more">
                      <summary>${escapeHtml(insights.showMoreLabel)}</summary>
                      <ul class="history-findings-list history-findings-list--secondary">
                        ${insights.hiddenSecondary
                          .map((finding) => renderSecondaryFinding(finding, escapeHtml))
                          .join("")}
                      </ul>
                    </details>
                  `
                : ""}
            </div>
          `
      : ""}`;
  } else if (insights.emptyMessage) {
    body = `<ul class="history-findings-list history-findings-list--secondary"><li class="history-finding-card history-finding-card--empty">${escapeHtml(insights.emptyMessage)}</li></ul>`;
  }
  return `
      <div class="history-insights-block">
        <div class="history-panel-header">
          <div class="history-panel-header__eyebrow">${escapeHtml(insights.headerEyebrow)}</div>
        </div>
        ${body}
      </div>
    `;
}

function renderWarnings(
  warnings: NonNullable<HistoryRowViewModel["details"]>["warnings"],
  escapeHtml: HistoryTableRendererParams["escapeHtml"],
): string {
  if (!warnings.length) {
    return "";
  }
  return `
      <div class="history-warning-list">
        ${warnings
          .map((warning) => {
            const detailText = warning.detail
              ? `<div class="history-warning-banner__detail">${escapeHtml(warning.detail)}</div>`
              : "";
            return `<div class="history-warning-banner history-warning-banner--${escapeHtml(warning.severity)}"><strong>${escapeHtml(warning.title)}</strong>${detailText}</div>`;
          })
          .join("")}
      </div>
    `;
}

function renderDetails(
  row: HistoryRowViewModel,
  details: NonNullable<HistoryRowViewModel["details"]>,
  params: HistoryTableRendererParams,
): string {
  const { escapeHtml, historyExportUrl } = params;
  const heatmapMarkup = renderHeatmap(details.heatmap, escapeHtml);
  return `
      <tr class="history-details-row">
        <td colspan="4">
          <div class="history-details-card">
            <div class="history-details-header">
              <div class="history-details-header__copy">
                <div class="history-details-header__eyebrow">${escapeHtml(details.titleEyebrow)}</div>
                <div class="history-details-header__title">${escapeHtml(details.title)}</div>
                ${details.runSummary ? `<div class="history-run-summary">${escapeHtml(details.runSummary)}</div>` : ""}
              </div>
              <div class="history-details-header__actions">
                ${details.reloadActionLabel
                  ? `<button class="btn btn--muted" data-run-action="load-insights" ${details.reloadActionDisabled ? "disabled" : ""}>${escapeHtml(details.reloadActionLabel)}</button>`
                  : details.loadingStatusText
                    ? `<div class="history-details-header__status">${escapeHtml(details.loadingStatusText)}</div>`
                    : ""}
                ${details.insightsError ? `<span class="history-inline-error">${escapeHtml(details.insightsError)}</span>` : ""}
              </div>
            </div>
            ${renderWarnings(details.warnings, escapeHtml)}
            <div class="history-results-layout">
              ${renderInsights(details.insights, escapeHtml)}
              <div class="history-evidence-column">
                <div class="history-evidence-panel">
                  ${heatmapMarkup}
                </div>
              </div>
            </div>
            <div class="history-details-footer">
              <div class="history-details-footer__copy">
                <div class="history-details-footer__eyebrow">${escapeHtml(details.footerEyebrow)}</div>
                <div class="history-details-footer__body">${escapeHtml(details.footerBody)}</div>
              </div>
              <div class="history-details-footer__actions">
                <a class="btn btn--muted" href="${historyExportUrl(row.runId)}" download="${escapeHtml(row.runId)}.zip" data-run-action="download-raw" data-run="${escapeHtml(row.runId)}">${escapeHtml(details.exportLabel)}</a>
                <button class="btn btn--danger-quiet" data-run-action="delete-run" data-run="${escapeHtml(row.runId)}">${escapeHtml(details.deleteLabel)}</button>
              </div>
            </div>
          </div>
        </td>
      </tr>
    `;
}

export function renderHistoryTableRows(
  rows: HistoryRowViewModel[],
  params: HistoryTableRendererParams,
): string {
  const { escapeHtml } = params;
  return rows
    .flatMap((row) => {
      const rowError = row.pdfError
        ? `<div class="history-inline-error">${escapeHtml(row.pdfError)}</div>`
        : "";
      const renderedRow = `
        <tr class="history-row${row.isExpanded ? " history-row--expanded" : ""}" data-run-row="1" data-run="${escapeHtml(row.runId)}">
          <td class="history-row__primary-cell">
            <div class="history-row__run">
              <div class="history-row__run-heading">
                <div class="history-row__car-context">
                  <span class="history-row__car-label">${escapeHtml(row.carLabel)}</span>
                  <span class="history-row__car-name">${escapeHtml(row.carName)}</span>
                </div>
                <div class="history-row__run-id">${escapeHtml(row.runId)}</div>
              </div>
              ${renderSummaryChips(row.summaryChips, escapeHtml)}
              <div class="history-row__detail-affordance">
                <button
                  type="button"
                  class="history-row__toggle${row.isExpanded ? " history-row__toggle--expanded" : ""}"
                  data-run-toggle="details"
                  data-run="${escapeHtml(row.runId)}"
                  aria-expanded="${row.isExpanded ? "true" : "false"}"
                  aria-label="${escapeHtml(row.toggleTitle)}"
                  title="${escapeHtml(row.toggleTitle)}"
                >
                  <span class="history-row__toggle-icon" aria-hidden="true"></span>
                  <span class="history-row__toggle-copy">
                    <span class="history-row__toggle-title">${escapeHtml(row.toggleLabel)}</span>
                    <span class="history-row__toggle-hint">${escapeHtml(row.previewHint)}</span>
                  </span>
                </button>
              </div>
            </div>
          </td>
          <td class="history-row__meta-cell history-row__meta-cell--started">
            <span class="history-row__meta-label">${escapeHtml(row.startedLabel)}</span>
            <span class="history-row__meta-value">${escapeHtml(row.startedAtText)}</span>
          </td>
          <td class="history-row__meta-cell history-row__meta-cell--samples numeric">
            <span class="history-row__meta-label">${escapeHtml(row.sizeLabel)}</span>
            <span class="history-row__meta-value">${escapeHtml(row.sampleCountText)}</span>
          </td>
          <td class="history-row__meta-cell history-row__meta-cell--actions">
            <span class="history-row__meta-label">${escapeHtml(row.quickReportLabel)}</span>
            ${renderCollapsedRowActions(row, params)}
            ${rowError}
          </td>
        </tr>`;
      return row.details ? [renderedRow, renderDetails(row, row.details, params)] : [renderedRow];
    })
    .join("");
}
