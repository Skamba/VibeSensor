import type { CSSProperties, JSX, TargetedMouseEvent } from "preact";

import { historyExportUrl } from "../../api/history";
import { navigate, speedUnit } from "../../app_store";
import { fmt, fmtTs, formatIntLocale } from "../../format";
import { lang, t } from "../../i18n";
import {
  buildDetails,
  buildRow,
  type CheckLine,
  type ChecksModel,
  type DetailsModel,
  EMPTY_RUN_DETAIL,
  type Formatters,
  type HeatmapModel,
  type InsightsModel,
  type RowModel,
  type SecondaryFinding,
} from "./history_model";
import {
  deleteAllInFlight,
  deleteAllRuns,
  deleteRun,
  details,
  downloadReport,
  expandedRunId,
  refreshHistory,
  reloadInsights,
  runs,
  toggleRun,
} from "./history_store";

function formatters(): Formatters {
  const language = lang.value;
  return {
    t,
    fmt,
    fmtTs,
    formatInt: (value) => formatIntLocale(value, language),
    speedUnit: speedUnit.value,
  };
}

/** Run buttons sit inside the clickable row; keep their clicks to themselves. */
function action(run: () => void) {
  return (event: TargetedMouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    run();
  };
}

function EmptyRow() {
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
              class="btn btn--primary"
              data-inline-state-action="open-live"
              onClick={() => navigate("dashboardView")}
            >
              {t("history.empty.action")}
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}

function RunRow(props: { row: RowModel }) {
  const { row } = props;
  return (
    <tr
      class="history-row"
      data-expanded={row.isExpanded ? "true" : undefined}
      data-run-row="1"
      data-run={row.runId}
      onClick={() => toggleRun(row.runId)}
    >
      <td class="history-row__primary-cell">
        <div class="history-row__run">
          <div class="history-row__run-heading">
            <div class="history-row__car-context">
              <span class="history-row__car-label">
                {t("history.car_label")}
              </span>
              <span class="history-row__car-name">{row.carName}</span>
            </div>
            <div class="history-row__run-id">{row.runId}</div>
          </div>
          <div class="history-row__summary-chips">
            {row.chips.map((chip) => (
              <span
                key={chip.key}
                class={`history-row__summary-chip history-row__summary-chip--${chip.tone}`}
              >
                {chip.text}
              </span>
            ))}
          </div>
          <div class="history-row__detail-affordance">
            {row.headline || row.meta ? (
              <div class="history-row__diagnosis">
                {row.headline ? (
                  <div class="history-row__diagnosis-title">{row.headline}</div>
                ) : null}
                {row.meta ? (
                  <div class="history-row__diagnosis-meta">{row.meta}</div>
                ) : null}
              </div>
            ) : null}
            <button
              class="history-row__toggle"
              data-expanded={row.isExpanded ? "true" : undefined}
              type="button"
              aria-expanded={row.isExpanded ? "true" : "false"}
              aria-label={row.toggleTitle}
              title={row.toggleTitle}
              data-run-toggle="details"
              data-run={row.runId}
              onClick={(event) => {
                event.stopPropagation();
                toggleRun(row.runId);
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
        <span class="history-row__meta-label">
          {t("history.table.updated")}
        </span>
        <span class="history-row__meta-value">{row.startedAt}</span>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--samples numeric">
        <span class="history-row__meta-label">
          {t("history.table.raw_samples")}
        </span>
        <span class="history-row__meta-value">{row.rawSampleCount}</span>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--actions">
        <span class="history-row__meta-label">{t("history.quick_report")}</span>
        {row.reportPendingHint ? (
          <div class="history-row__action-hint">{row.reportPendingHint}</div>
        ) : (
          <div class="table-actions history-row__actions">
            <button
              class="btn btn--muted"
              type="button"
              disabled={row.pdfLoading}
              data-run-action="download-pdf"
              data-run={row.runId}
              onClick={action(() => void downloadReport(row.runId))}
            >
              {row.pdfLabel}
            </button>
          </div>
        )}
        {row.pdfError ? (
          <div class="history-inline-error">{row.pdfError}</div>
        ) : null}
      </td>
    </tr>
  );
}

function SecondaryCard(props: { finding: SecondaryFinding }) {
  const { finding } = props;
  return (
    <li
      class={`history-finding-card history-finding-card--secondary history-finding-card--${finding.tone}`}
    >
      <div class="history-finding-card__header">
        <div class="history-finding-card__title-group">
          <strong class="history-finding-card__title">{finding.source}</strong>
          <span class="history-finding-card__signal">{finding.signature}</span>
        </div>
        {finding.confidence ? (
          <span
            class={`history-finding-card__confidence history-finding-card__confidence--${finding.tone}`}
          >
            {finding.confidence}
          </span>
        ) : null}
      </div>
      <div class="history-finding-card__meta">
        <div class="history-finding-card__meta-item">
          <span class="history-finding-card__label">
            {t("history.findings_location")}
          </span>
          <strong>{finding.location}</strong>
        </div>
        <div class="history-finding-card__meta-item">
          <span class="history-finding-card__label">
            {t("history.findings_speed_band")}
          </span>
          <strong>{finding.speedBand}</strong>
        </div>
      </div>
      <p class="history-finding-card__summary">{finding.evidence}</p>
    </li>
  );
}

function CheckList(props: { title: string; lines: CheckLine[]; tone: string }) {
  const { title, lines, tone } = props;
  if (lines.length === 0) {
    return null;
  }
  return (
    <div class={`history-checks__group history-checks__group--${tone}`}>
      <div class="history-checks__title">{title}</div>
      <ul class="history-checks__list">
        {lines.map((line) => (
          <li key={line.label} class="history-checks__item">
            <strong>{line.label}</strong>: {line.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Checks(props: { checks: ChecksModel }) {
  const { checks } = props;
  return (
    <div class="history-checks">
      <CheckList
        title={checks.checkedTitle}
        lines={checks.checked}
        tone="checked"
      />
      <CheckList
        title={checks.notCheckedTitle}
        lines={checks.notChecked}
        tone="not-checked"
      />
      <CheckList
        title={checks.referencesTitle}
        lines={checks.references}
        tone="references"
      />
    </div>
  );
}

function Insights(props: { insights: InsightsModel }) {
  const { insights } = props;
  let body: JSX.Element;
  if (insights.kind === "state") {
    body = <div class="history-panel-state">{insights.message}</div>;
  } else {
    const { primary } = insights;
    body = (
      <>
        {primary ? (
          <div class="history-findings-overview">
            <div class="history-findings-overview__header">
              <div class="history-findings-overview__eyebrow">
                {primary.eyebrow}
              </div>
            </div>
            <div
              class={`history-diagnosis-card history-diagnosis-card--${primary.tone}`}
            >
              <div class="history-diagnosis-card__header">
                <div class="history-diagnosis-card__copy">
                  <div class="history-findings-overview__headline">
                    {primary.headline}
                  </div>
                  {primary.signature ? (
                    <div class="history-diagnosis-card__signature">
                      {primary.signature}
                    </div>
                  ) : null}
                </div>
                {primary.confidence ? (
                  <span
                    class={`history-diagnosis-card__confidence history-diagnosis-card__confidence--${primary.tone}`}
                  >
                    {primary.confidence}
                  </span>
                ) : null}
              </div>
              {primary.explanation ? (
                <p class="history-findings-overview__explanation">
                  {primary.explanation}
                </p>
              ) : null}
              <div class="history-findings-overview__chips">
                {primary.chips.map((chip, index) => (
                  <div
                    key={`${chip.label}:${index}`}
                    class="history-findings-chip"
                  >
                    <span class="history-findings-chip__label">
                      {chip.label}
                    </span>
                    <strong>{chip.value}</strong>
                  </div>
                ))}
              </div>
              {primary.nextStep && primary.nextStepLabel ? (
                <div class="history-diagnosis-card__next-step">
                  <span class="history-diagnosis-card__next-step-label">
                    {primary.nextStepLabel}
                  </span>{" "}
                  <strong>{primary.nextStep}</strong>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
        <Checks checks={insights.checks} />
        {insights.secondaryTitle ? (
          <div class="history-secondary-findings">
            <div class="history-secondary-findings__title">
              {insights.secondaryTitle}
            </div>
            <ul class="history-findings-list history-findings-list--secondary">
              {insights.visibleSecondary.map((finding, index) => (
                <SecondaryCard
                  key={`${finding.source}:${finding.signature}:${index}`}
                  finding={finding}
                />
              ))}
            </ul>
            {insights.showMoreLabel ? (
              <details class="history-secondary-findings__more">
                <summary>{insights.showMoreLabel}</summary>
                <ul class="history-findings-list history-findings-list--secondary">
                  {insights.hiddenSecondary.map((finding, index) => (
                    <SecondaryCard
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
  }
  return (
    <div class="history-insights-block">
      <div class="history-panel-header">
        <div class="history-panel-header__eyebrow">
          {t("history.findings_title")}
        </div>
      </div>
      {body}
    </div>
  );
}

function Heatmap(props: { heatmap: HeatmapModel }) {
  const { heatmap } = props;
  return (
    <div class="history-heatmap">
      <div class="history-heatmap__header">
        <div class="history-heatmap__title">
          {t("history.preview_heatmap_title")}
        </div>
      </div>
      {heatmap.kind === "state" ? (
        <p class={heatmap.tone === "error" ? "history-inline-error" : "subtle"}>
          {heatmap.message}
        </p>
      ) : (
        <>
          <div class="history-heatmap__grid">
            {heatmap.zones.map((zone) => {
              const empty = zone.accent === null;
              const style: CSSProperties & Record<string, string> = {
                gridArea: zone.gridArea,
              };
              if (zone.accent) {
                style["--history-heatmap-accent"] = zone.accent.color;
                style["--history-heatmap-fill"] = `${zone.accent.fillPercent}%`;
              }
              return (
                <div
                  key={zone.key}
                  class={[
                    "history-heatmap__zone",
                    empty ? "history-heatmap__zone--empty" : "",
                    !empty && zone.strongest
                      ? "history-heatmap__zone--strongest"
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  style={style}
                  title={
                    empty ? zone.label : `${zone.label}: ${zone.valueLabel}`
                  }
                  data-location-key={zone.key}
                >
                  <div class="history-heatmap__zone-label">{zone.label}</div>
                  <div
                    class={
                      empty
                        ? "history-heatmap__zone-value history-heatmap__zone-value--empty"
                        : "history-heatmap__zone-value"
                    }
                  >
                    {zone.valueLabel}
                  </div>
                  <div class="history-heatmap__zone-meter" aria-hidden="true">
                    {empty ? null : (
                      <span class="history-heatmap__zone-meter-fill" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {heatmap.extras.length ? (
            <div class="history-heatmap__extras">
              {heatmap.extras.map((extra, index) => (
                <div
                  key={`${extra}:${index}`}
                  class="history-heatmap__extra-chip"
                >
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

function DetailsRow(props: { runId: string; model: DetailsModel }) {
  const { runId, model } = props;
  return (
    <tr class="history-details-row">
      <td colSpan={4}>
        <div class="history-details-card">
          <div class="history-details-header">
            <div class="history-details-header__copy">
              <div class="history-details-header__eyebrow">
                {t("history.details_title")}
              </div>
              <div class="history-details-header__title">{model.title}</div>
              {model.runSummary ? (
                <div class="history-run-summary">{model.runSummary}</div>
              ) : null}
            </div>
            <div class="history-details-header__actions">
              {model.reloadLabel ? (
                <button
                  class="btn btn--muted"
                  type="button"
                  disabled={model.reloadDisabled}
                  data-run-action="load-insights"
                  data-run={runId}
                  onClick={action(() => void reloadInsights(runId))}
                >
                  {model.reloadLabel}
                </button>
              ) : model.loadingStatus ? (
                <div class="history-details-header__status">
                  {model.loadingStatus}
                </div>
              ) : null}
              {model.insightsError ? (
                <span class="history-inline-error">{model.insightsError}</span>
              ) : null}
            </div>
          </div>
          {model.warnings.length ? (
            <div class="history-warning-list">
              {model.warnings.map((warning, index) => (
                <div
                  key={`${warning.severity}:${warning.title}:${index}`}
                  class={`history-warning-banner history-warning-banner--${warning.severity}`}
                >
                  <strong>{warning.title}</strong>
                  {warning.detail ? (
                    <div class="history-warning-banner__detail">
                      {warning.detail}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          <div class="history-results-layout">
            <div class="history-main-column">
              <Insights insights={model.insights} />
              <div class="history-details-footer">
                <div class="history-details-footer__copy">
                  <div class="history-details-footer__eyebrow">
                    {t("history.run_actions_title")}
                  </div>
                  <div class="history-details-footer__body">
                    {t("history.run_actions_body")}
                  </div>
                </div>
                <div class="history-details-footer__actions">
                  <a
                    class="btn btn--muted"
                    href={historyExportUrl(runId)}
                    download={`${runId}.zip`}
                    data-run-action="download-raw"
                    data-run={runId}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {t("history.export")}
                  </a>
                  <button
                    class="btn btn--danger-quiet"
                    type="button"
                    data-run-action="delete-run"
                    data-run={runId}
                    onClick={action(() => void deleteRun(runId))}
                  >
                    {t("history.delete")}
                  </button>
                </div>
              </div>
            </div>
            <div class="history-evidence-column">
              <div class="history-evidence-panel">
                <Heatmap heatmap={model.heatmap} />
              </div>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

export function History() {
  const list = runs.value;
  const expanded = expandedRunId.value;
  const detailById = details.value;
  const f = formatters();
  return (
    <>
      <div class="history-toolbar">
        <div class="history-toolbar__copy">
          <div id="historySummary" class="history-toolbar__summary subtle">
            {list.length
              ? t("history.available_count", { count: list.length })
              : t("history.none")}
          </div>
        </div>
        <div class="history-toolbar__actions">
          <button
            id="refreshHistoryBtn"
            class="btn btn--muted"
            type="button"
            onClick={() => void refreshHistory()}
          >
            {t("history.refresh")}
          </button>
          <button
            id="deleteAllRunsBtn"
            class="btn btn--danger-quiet"
            type="button"
            disabled={deleteAllInFlight.value || list.length === 0}
            onClick={() => void deleteAllRuns()}
          >
            {t("history.delete_all")}
          </button>
        </div>
      </div>
      <table class="history-table">
        <thead>
          <tr>
            <th>{t("history.table.file")}</th>
            <th>{t("history.table.updated")}</th>
            <th class="numeric">{t("history.table.raw_samples")}</th>
            <th>{t("history.table.actions")}</th>
          </tr>
        </thead>
        <tbody id="historyTableBody">
          {list.length === 0 ? (
            <EmptyRow />
          ) : (
            list.flatMap((run) => {
              const detail = detailById[run.run_id] ?? EMPTY_RUN_DETAIL;
              const isExpanded = expanded === run.run_id;
              return [
                <RunRow
                  key={`row:${run.run_id}`}
                  row={buildRow(run, detail, isExpanded, f)}
                />,
                isExpanded ? (
                  <DetailsRow
                    key={`details:${run.run_id}`}
                    runId={run.run_id}
                    model={buildDetails(run, detail, f)}
                  />
                ) : null,
              ];
            })
          )}
        </tbody>
      </table>
    </>
  );
}
