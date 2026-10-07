import type { CSSProperties, TargetedMouseEvent } from "preact";

import { historyExportUrl } from "../../api/history";
import { navigate, speedUnit } from "../../app_store";
import { fmt, fmtShortTs, fmtTs, formatIntLocale } from "../../format";
import { lang, t } from "../../i18n";
import {
  buildDetails,
  buildRow,
  type CheckLine,
  type ChecksModel,
  type DetailsModel,
  type DiagramModel,
  EMPTY_RUN_DETAIL,
  type FindingsModel,
  type Formatters,
  type HeatmapModel,
  type OwnerPage,
  ownerDiagram,
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
  reloadDiagnosis,
  runs,
  toggleRun,
} from "./history_store";

function formatters(): Formatters {
  const language = lang.value;
  return {
    t,
    fmt,
    fmtTs,
    fmtShortTs: (iso) => fmtShortTs(iso, language),
    formatInt: (value) => formatIntLocale(value, language),
    speedUnit: speedUnit.value,
  };
}

/** Run buttons sit inside the run card; keep their clicks to themselves. */
function action(run: () => void) {
  return (event: TargetedMouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    run();
  };
}

function EmptyState() {
  return (
    <li class="empty-state empty-state--inline empty-state--actionable">
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
    </li>
  );
}

function RunRow(props: { row: RowModel }) {
  const { row } = props;
  return (
    <div
      class="history-row"
      data-expanded={row.isExpanded ? "true" : undefined}
      data-run-row="1"
      data-run={row.runId}
    >
      <button
        class="history-row__toggle"
        type="button"
        aria-expanded={row.isExpanded ? "true" : "false"}
        aria-label={row.toggleTitle}
        title={row.toggleTitle}
        data-run-toggle="details"
        data-run={row.runId}
        onClick={() => toggleRun(row.runId)}
      >
        <span class="history-row__toggle-icon" aria-hidden="true" />
        <span class="history-row__heading">
          <span class="history-row__title">{row.title}</span>
          <span class="history-row__subtitle">{row.subtitle}</span>
        </span>
      </button>
      <div class="history-row__actions">
        {row.reportPendingHint ? (
          <span class="history-row__action-hint">{row.reportPendingHint}</span>
        ) : (
          <button
            class="btn btn--muted history-row__pdf"
            type="button"
            disabled={row.pdfLoading}
            data-run-action="download-pdf"
            data-run={row.runId}
            onClick={action(() => void downloadReport(row.runId))}
          >
            {row.pdfLabel}
          </button>
        )}
      </div>
      {row.chips.length ? (
        <div class="history-row__chips">
          {row.chips.map((chip) => (
            <span
              key={chip.key}
              class={`history-row__chip history-row__chip--${chip.tone}`}
            >
              {chip.text}
            </span>
          ))}
        </div>
      ) : null}
      {row.pdfError ? (
        <div class="history-inline-error history-row__error">
          {row.pdfError}
        </div>
      ) : null}
    </div>
  );
}

/** The PDF's top-view car diagram: the suspected zone and each sensor's level. */
function CarDiagram(props: { diagram: DiagramModel }) {
  const { diagram } = props;
  return (
    <svg
      class="history-car"
      viewBox={`0 0 ${diagram.width} ${diagram.height}`}
      role="img"
      aria-label={diagram.markers
        .map((marker) => `${marker.label}: ${marker.value}`)
        .join(", ")}
    >
      <text
        class="history-car__front"
        x={diagram.width / 2}
        y={5.5}
        text-anchor="middle"
      >
        {diagram.frontLabel}
      </text>
      <rect
        class="history-car__body"
        x={diagram.body.x}
        y={diagram.body.y}
        width={diagram.body.width}
        height={diagram.body.height}
        rx={diagram.body.radius}
      />
      {diagram.windows.map((box, index) => (
        <rect
          key={`window:${index}`}
          class="history-car__window"
          x={box.x}
          y={box.y}
          width={box.width}
          height={box.height}
          rx={1.5}
        />
      ))}
      {diagram.zone ? (
        <rect
          class="history-car__zone"
          x={diagram.zone.x}
          y={diagram.zone.y}
          width={diagram.zone.width}
          height={diagram.zone.height}
          rx={2}
        />
      ) : null}
      {diagram.wheels.map((wheel) => (
        <rect
          key={wheel.code}
          class={
            wheel.highlighted
              ? "history-car__wheel history-car__wheel--highlighted"
              : "history-car__wheel"
          }
          data-wheel={wheel.code}
          x={wheel.x}
          y={wheel.y}
          width={wheel.width}
          height={wheel.height}
          rx={1.2}
        />
      ))}
      {diagram.markers.map((marker) => (
        <g
          key={marker.code}
          class={
            marker.strongest
              ? "history-car__marker history-car__marker--strongest"
              : "history-car__marker"
          }
          data-location-key={marker.code}
        >
          <circle cx={marker.cx} cy={marker.cy} r={marker.r} />
          <text
            x={marker.text.x}
            y={marker.text.y}
            text-anchor={marker.text.anchor}
          >
            {marker.value}
          </text>
        </g>
      ))}
    </svg>
  );
}

function StepBox(props: {
  title: string;
  body: string;
  fallback?: string | null;
  tone: "confirm" | "next";
}) {
  return (
    <div class={`history-owner__step history-owner__step--${props.tone}`}>
      <div class="history-owner__step-title">{props.title}</div>
      <strong class="history-owner__step-body">{props.body}</strong>
      {props.fallback ? (
        <p class="history-owner__step-fallback">{props.fallback}</p>
      ) : null}
    </div>
  );
}

/** Page 1 of the PDF, as the server words it: the verdict, then what to do. */
function OwnerSummary(props: { owner: OwnerPage }) {
  const { owner } = props;
  return (
    <div class={`history-owner history-owner--${owner.tone}`}>
      <div class="history-owner__verdict">
        <h3 class="history-owner__headline">{owner.headline}</h3>
        {owner.level_word && owner.level_meaning ? (
          <div class="history-owner__confidence">
            <span class="history-owner__confidence-label">
              {owner.confidence_label}
            </span>
            <span class="history-owner__level">{owner.level_word}</span>
            <span>{owner.level_meaning}</span>
          </div>
        ) : null}
        <p class="history-owner__description">{owner.description}</p>
        {owner.candidate ? (
          <p class="history-owner__candidate">{owner.candidate}</p>
        ) : null}
      </div>
      <div class="history-owner__body">
        <CarDiagram diagram={ownerDiagram(owner.diagram)} />
        <div class="history-owner__steps">
          {owner.reasons_title && owner.reasons.length ? (
            <section>
              <h4 class="history-owner__title">{owner.reasons_title}</h4>
              <ol class="history-owner__list">
                {owner.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ol>
            </section>
          ) : null}
          {owner.covered_title && owner.covered ? (
            <section>
              <h4 class="history-owner__title">{owner.covered_title}</h4>
              <p class="history-owner__text">{owner.covered}</p>
            </section>
          ) : null}
          {owner.not_covered_title && owner.not_covered.length ? (
            <section>
              <h4 class="history-owner__title">{owner.not_covered_title}</h4>
              <ul class="history-owner__list">
                {owner.not_covered.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {owner.confirm_title && owner.confirm ? (
            <StepBox
              title={owner.confirm_title}
              body={owner.confirm}
              tone="confirm"
            />
          ) : null}
          {owner.recapture_title && owner.recapture.length ? (
            <section>
              <h4 class="history-owner__title">{owner.recapture_title}</h4>
              <ol class="history-owner__list">
                {owner.recapture.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
            </section>
          ) : (
            <StepBox
              title={owner.next_step_title}
              body={owner.next_step}
              fallback={owner.fallback_step}
              tone="next"
            />
          )}
          {owner.verify_title && owner.verify ? (
            <section>
              <h4 class="history-owner__title">{owner.verify_title}</h4>
              <p class="history-owner__text">{owner.verify}</p>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SecondaryCard(props: { finding: SecondaryFinding }) {
  const { finding } = props;
  return (
    <li class={`history-finding-card history-finding-card--${finding.tone}`}>
      <div class="history-finding-card__header">
        <strong class="history-finding-card__title">{finding.source}</strong>
        <span class="history-finding-card__signal">{finding.signature}</span>
        {finding.confidence ? (
          <span
            class={`history-finding-card__confidence history-finding-card__confidence--${finding.tone}`}
          >
            {finding.confidence}
          </span>
        ) : null}
      </div>
      <div class="history-finding-card__meta">
        {t("history.findings_location")}: <strong>{finding.location}</strong>
        {" · "}
        {t("history.findings_speed_band")}: <strong>{finding.speedBand}</strong>
      </div>
      {finding.evidence ? (
        <p class="history-finding-card__summary">{finding.evidence}</p>
      ) : null}
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
        title={checks.notApplicableTitle}
        lines={checks.notApplicable}
        tone="not-applicable"
      />
      <CheckList
        title={checks.referencesTitle}
        lines={checks.references}
        tone="references"
      />
    </div>
  );
}

/** The workshop view: the diagnosed finding with its harmonics, the other
 * candidates, and what the run could and couldn't check. */
function Findings(props: { findings: FindingsModel }) {
  const { primary, secondaryTitle, visibleSecondary, hiddenSecondary } =
    props.findings;
  return (
    <>
      {primary ? (
        <div
          class={`history-finding-card history-finding-card--primary history-finding-card--${primary.tone}`}
        >
          <div class="history-finding-card__header">
            <strong class="history-finding-card__title">
              {primary.source}
            </strong>
            <span class="history-finding-card__signal">
              {primary.signature}
            </span>
            {primary.confidence ? (
              <span
                class={`history-finding-card__confidence history-finding-card__confidence--${primary.tone}`}
              >
                {primary.confidence}
              </span>
            ) : null}
          </div>
          <div class="history-finding-card__meta">
            {t("history.findings_location")}:{" "}
            <strong>{primary.location}</strong>
            {" · "}
            {t("history.findings_speed_band")}:{" "}
            <strong>{primary.speedBand}</strong>
          </div>
          {primary.alsoAt ? (
            <div class="history-finding-card__also">{primary.alsoAt}</div>
          ) : null}
          {primary.evidence ? (
            <p class="history-finding-card__summary">{primary.evidence}</p>
          ) : null}
        </div>
      ) : null}
      {secondaryTitle ? (
        <div class="history-secondary-findings">
          <div class="history-section-title">{secondaryTitle}</div>
          <ul class="history-findings-list">
            {visibleSecondary.map((finding, index) => (
              <SecondaryCard
                key={`${finding.source}:${finding.signature}:${index}`}
                finding={finding}
              />
            ))}
          </ul>
          {props.findings.showMoreLabel ? (
            <details class="history-secondary-findings__more">
              <summary>{props.findings.showMoreLabel}</summary>
              <ul class="history-findings-list">
                {hiddenSecondary.map((finding, index) => (
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
      <Checks checks={props.findings.checks} />
    </>
  );
}

function Heatmap(props: { heatmap: HeatmapModel }) {
  const { heatmap } = props;
  return (
    <div class="history-heatmap">
      <div class="history-section-title">
        {t("history.preview_heatmap_title")}
      </div>
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
              title={empty ? zone.label : `${zone.label}: ${zone.valueLabel}`}
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
            <div key={`${extra}:${index}`} class="history-heatmap__extra-chip">
              {extra}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RunDetails(props: {
  runId: string;
  name: string;
  model: DetailsModel;
}) {
  const { runId, name, model } = props;
  return (
    <div class="history-details-card">
      {model.owner ? (
        <OwnerSummary owner={model.owner} />
      ) : model.stateMessage ? (
        <div class="history-panel-state">{model.stateMessage}</div>
      ) : null}
      {model.error ? (
        <div class="history-inline-error">{model.error}</div>
      ) : null}
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
      {model.more ? (
        <details class="history-more">
          <summary class="history-more__summary">
            {t("history.more_details")}
          </summary>
          <div class="history-more__body">
            <Findings findings={model.more.findings} />
            <Heatmap heatmap={model.more.heatmap} />
          </div>
        </details>
      ) : null}
      <div class="history-details-footer">
        <dl class="history-details-footer__facts">
          {model.facts.map((fact) => (
            <div key={fact.label} class="history-details-footer__fact">
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
        <div class="history-details-footer__actions">
          <button
            class="btn btn--muted"
            type="button"
            disabled={model.reloadDisabled}
            data-run-action="load-insights"
            data-run={runId}
            onClick={action(() => void reloadDiagnosis(runId))}
          >
            {model.reloadLabel}
          </button>
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
            onClick={action(() => void deleteRun(runId, name))}
          >
            {t("history.delete")}
          </button>
        </div>
      </div>
    </div>
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
        <div id="historySummary" class="history-toolbar__summary subtle">
          {list.length
            ? t("history.available_count", { count: list.length })
            : t("history.none")}
        </div>
        <button
          id="refreshHistoryBtn"
          class="btn btn--muted history-toolbar__refresh"
          type="button"
          onClick={() => void refreshHistory()}
        >
          {t("history.refresh")}
        </button>
      </div>
      <ol id="historyTableBody" class="history-list">
        {list.length === 0 ? (
          <EmptyState />
        ) : (
          list.map((run) => {
            const detail = detailById[run.run_id] ?? EMPTY_RUN_DETAIL;
            const isExpanded = expanded === run.run_id;
            const row = buildRow(run, detail, isExpanded, f);
            return (
              <li
                key={run.run_id}
                class="history-list__item"
                data-expanded={isExpanded ? "true" : undefined}
              >
                <RunRow row={row} />
                {isExpanded ? (
                  <RunDetails
                    runId={run.run_id}
                    name={row.title}
                    model={buildDetails(run, detail, f)}
                  />
                ) : null}
              </li>
            );
          })
        )}
      </ol>
      {list.length ? (
        <div class="history-list-footer">
          <button
            id="deleteAllRunsBtn"
            class="history-quiet-action"
            type="button"
            disabled={deleteAllInFlight.value}
            onClick={() => void deleteAllRuns()}
          >
            {t("history.delete_all")}
          </button>
        </div>
      ) : null}
    </>
  );
}
