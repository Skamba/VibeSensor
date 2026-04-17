import type { JSX } from "preact";

import { useComputed, useSignal, type ReadonlySignal } from "../ui_signals";
import { inlineStateActionClass } from "./dom_helpers";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelTableRenderModel,
  HistoryRunAction,
} from "./history_table_view";
import type {
  HistoryDetailsViewModel,
  HistoryHeatmapViewModel,
  HistoryInsightsViewModel,
  HistoryPrimaryFindingViewModel,
  HistoryRowViewModel,
  HistorySecondaryFindingViewModel,
  HistorySummaryChipTone,
} from "./history_table_models";
import { createHistoryTableRowsMemo } from "./history_table_presenters";

type HistoryHeatmapZoneStyle = JSX.CSSProperties & {
  "--history-heatmap-accent"?: string;
  "--history-heatmap-fill"?: string;
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

function heatmapZoneStyle(zone: HistoryHeatmapViewModel["zones"][number]): HistoryHeatmapZoneStyle {
  const style: HistoryHeatmapZoneStyle = {
    gridArea: zone.gridArea,
  };
  if (zone.valueLabel !== null && zone.accentColor !== null && zone.fillPercent !== null) {
    style["--history-heatmap-accent"] = zone.accentColor;
    style["--history-heatmap-fill"] = `${zone.fillPercent}%`;
  }
  return style;
}

function stopRowToggle(event: JSX.TargetedMouseEvent<HTMLElement>): void {
  event.stopPropagation();
}

function handleRunAction(
  event: JSX.TargetedMouseEvent<HTMLElement>,
  handlers: HistoryPanelActionHandlers | null,
  action: HistoryRunAction,
  runId: string,
): void {
  event.preventDefault();
  event.stopPropagation();
  handlers?.onTableInteraction({
    type: "run-action",
    action,
    runId,
  });
}

function useHistoryTableRows(
  table: ReadonlySignal<HistoryPanelTableRenderModel | null>,
): ReadonlySignal<HistoryRowViewModel[] | null> {
  const rowsMemo = useSignal(createHistoryTableRowsMemo());

  return useComputed(() => {
    const nextTable = table.value;
    if (nextTable === null || nextTable.kind !== "rows") {
      return null;
    }
    return rowsMemo.value(nextTable.params);
  });
}

function HistoryEmptyStateRow(props: {
  handlers: HistoryPanelActionHandlers | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
}) {
  const { handlers, t } = props;
  return (
    <tr>
      <td colSpan={4}>
        <div class="empty-state empty-state--inline empty-state--actionable">
          <strong class="empty-state__title">{t("history.empty.title")}</strong>
          <span class="empty-state__body">{t("history.empty.body")}</span>
          <span class="empty-state__detail">{t("history.empty.detail")}</span>
          <div class="empty-state__actions">
            <button
              type="button"
              class={inlineStateActionClass(undefined)}
              data-inline-state-action="open-live"
              onClick={() => handlers?.onTableInteraction({ type: "open-live" })}
            >
              {t("history.empty.action")}
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}

function HistorySummaryChips(props: { row: HistoryRowViewModel }) {
  return (
    <div class="history-row__summary-chips">
      {props.row.summaryChips.map((chip, index) => (
        <span
          key={`${chip.tone}:${chip.text}:${index}`}
          class={`history-row__summary-chip${chipModifier(chip.tone)}`}
        >
          {chip.text}
        </span>
      ))}
    </div>
  );
}

function HistoryDiagnosisSummary(props: { row: HistoryRowViewModel }) {
  const { row } = props;
  if (!row.summaryHeadline && !row.summaryMeta) {
    return null;
  }
  return (
    <div class="history-row__diagnosis">
      {row.summaryHeadline ? (
        <div class="history-row__diagnosis-title">{row.summaryHeadline}</div>
      ) : null}
      {row.summaryMeta ? (
        <div class="history-row__diagnosis-meta">{row.summaryMeta}</div>
      ) : null}
    </div>
  );
}

function HistoryCollapsedRowActions(props: {
  handlers: HistoryPanelActionHandlers | null;
  row: HistoryRowViewModel;
}) {
  const { handlers, row } = props;
  if (row.collapsedAction.hintText) {
    return <div class="history-row__action-hint">{row.collapsedAction.hintText}</div>;
  }
  return (
    <div class="table-actions history-row__actions">
      <button
        class="btn btn--muted"
        type="button"
        disabled={row.collapsedAction.pdfLoading}
        data-run-action="download-pdf"
        data-run={row.runId}
        onClick={(event) => handleRunAction(event, handlers, "download-pdf", row.runId)}
      >
        {row.collapsedAction.pdfLabel ?? ""}
      </button>
    </div>
  );
}

function HistoryHeatmap(props: { heatmap: HistoryHeatmapViewModel }) {
  const { heatmap } = props;
  return (
    <div class="history-heatmap">
      <div class="history-heatmap__header">
        <div class="history-heatmap__title">{heatmap.title}</div>
      </div>
      {heatmap.stateMessage ? (
        <p class={heatmap.stateTone === "error" ? "history-inline-error" : "subtle"}>
          {heatmap.stateMessage}
        </p>
      ) : (
        <>
          <div class="history-heatmap__grid">
            {heatmap.zones.map((zone) => {
              const isEmpty =
                zone.valueLabel === null
                || zone.accentColor === null
                || zone.fillPercent === null;
              return (
                <div
                  key={zone.key}
                  class={[
                    "history-heatmap__zone",
                    isEmpty ? "history-heatmap__zone--empty" : "",
                    !isEmpty && zone.strongest ? "history-heatmap__zone--strongest" : "",
                  ].filter(Boolean).join(" ")}
                  style={heatmapZoneStyle(zone)}
                  title={isEmpty ? zone.label : `${zone.label}: ${zone.valueLabel}`}
                  data-location-key={zone.key}
                >
                  <div class="history-heatmap__zone-label">{zone.label}</div>
                  <div
                    class={[
                      "history-heatmap__zone-value",
                      isEmpty ? "history-heatmap__zone-value--empty" : "",
                    ].filter(Boolean).join(" ")}
                  >
                    {zone.valueLabel ?? ""}
                  </div>
                  <div class="history-heatmap__zone-meter" aria-hidden="true">
                    {!isEmpty ? <span class="history-heatmap__zone-meter-fill" /> : null}
                  </div>
                </div>
              );
            })}
          </div>
          {heatmap.extras.length ? (
            <div class="history-heatmap__extras">
              {heatmap.extras.map((extra, index) => (
                <div key={`${extra}:${index}`} class="history-heatmap__extra-chip">
                  {extra}
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

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
  handlers: HistoryPanelActionHandlers | null;
  historyExportUrl: (runId: string) => string;
  row: HistoryRowViewModel;
}) {
  const { details, handlers, historyExportUrl, row } = props;
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
          onClick={stopRowToggle}
        >
          {details.exportLabel}
        </a>
        <button
          class="btn btn--danger-quiet"
          type="button"
          data-run-action="delete-run"
          data-run={row.runId}
          onClick={(event) => handleRunAction(event, handlers, "delete-run", row.runId)}
        >
          {details.deleteLabel}
        </button>
      </div>
    </div>
  );
}

function HistoryDetailsRow(props: {
  details: HistoryDetailsViewModel;
  handlers: HistoryPanelActionHandlers | null;
  historyExportUrl: (runId: string) => string;
  row: HistoryRowViewModel;
}) {
  const { details, handlers, historyExportUrl, row } = props;
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
                  onClick={(event) => handleRunAction(event, handlers, "load-insights", row.runId)}
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
                handlers={handlers}
                historyExportUrl={historyExportUrl}
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

function HistoryRow(props: {
  handlers: HistoryPanelActionHandlers | null;
  row: HistoryRowViewModel;
}) {
  const { handlers, row } = props;
  return (
    <tr
      class={`history-row${row.isExpanded ? " history-row--expanded" : ""}`}
      data-run-row="1"
      data-run={row.runId}
      onClick={() => handlers?.onTableInteraction({ type: "toggle-run", runId: row.runId })}
    >
      <td class="history-row__primary-cell">
        <div class="history-row__run">
          <div class="history-row__run-heading">
            <div class="history-row__car-context">
              <span class="history-row__car-label">{row.carLabel}</span>
              <span class="history-row__car-name">{row.carName}</span>
            </div>
            <div class="history-row__run-id">{row.runId}</div>
          </div>
          <HistorySummaryChips row={row} />
          <div class="history-row__detail-affordance">
            <HistoryDiagnosisSummary row={row} />
            <button
              class={`history-row__toggle${row.isExpanded ? " history-row__toggle--expanded" : ""}`}
              type="button"
              aria-expanded={row.isExpanded ? "true" : "false"}
              aria-label={row.toggleTitle}
              title={row.toggleTitle}
              data-run-toggle="details"
              data-run={row.runId}
              onClick={(event) => {
                event.stopPropagation();
                handlers?.onTableInteraction({ type: "toggle-run", runId: row.runId });
              }}
            >
              <span class="history-row__toggle-icon" aria-hidden="true" />
              <span class="history-row__toggle-copy">
                <span class="history-row__toggle-title">{row.toggleLabel}</span>
              </span>
            </button>
          </div>
        </div>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--started">
        <span class="history-row__meta-label">{row.startedLabel}</span>
        <span class="history-row__meta-value">{row.startedAtText}</span>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--samples numeric">
        <span class="history-row__meta-label">{row.sizeLabel}</span>
        <span class="history-row__meta-value">{row.sampleCountText}</span>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--actions">
        <span class="history-row__meta-label">{row.quickReportLabel}</span>
        <HistoryCollapsedRowActions handlers={handlers} row={row} />
        {row.pdfError ? <div class="history-inline-error">{row.pdfError}</div> : null}
      </td>
    </tr>
  );
}

export function HistoryTableBody(props: {
  handlers: HistoryPanelActionHandlers | null;
  table: ReadonlySignal<HistoryPanelTableRenderModel | null>;
}) {
  const { handlers } = props;
  const tableKind = useComputed(() => props.table.value?.kind ?? null);
  const emptyStateTranslate = useComputed(() =>
    props.table.value?.kind === "empty" ? props.table.value.t : null
  );
  const historyExportUrl = useComputed(() =>
    props.table.value?.kind === "rows" ? props.table.value.params.historyExportUrl : null
  );
  const rows = useHistoryTableRows(props.table);

  if (tableKind.value === null) {
    return (
      <tr>
        <td colSpan={4}>No runs found.</td>
      </tr>
    );
  }
  if (tableKind.value === "empty") {
    const translate = emptyStateTranslate.value;
    if (translate === null) {
      throw new Error("History empty-state translation missing");
    }
    return <HistoryEmptyStateRow handlers={handlers} t={translate} />;
  }

  const currentRows = rows.value;
  const currentHistoryExportUrl = historyExportUrl.value;
  if (currentRows === null || currentHistoryExportUrl === null) {
    throw new Error("History row params missing");
  }
  return (
    <>
      {currentRows.flatMap((row) => [
        <HistoryRow key={`row:${row.runId}`} handlers={handlers} row={row} />,
        row.details ? (
          <HistoryDetailsRow
            key={`details:${row.runId}`}
            details={row.details}
            handlers={handlers}
            historyExportUrl={currentHistoryExportUrl}
            row={row}
          />
        ) : null,
      ])}
    </>
  );
}
