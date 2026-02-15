import {
  deleteLog as deleteLogApi,
  getLogInsights,
  getLogs,
  logDownloadUrl,
  reportPdfUrl,
} from "../api";
import { escapeHtml, fmt, fmtBytes, fmtTs } from "../format";

type LogReportDeps = {
  els: Record<string, any>;
  state: Record<string, any>;
  t: (key: string, vars?: Record<string, any>) => string;
  setActiveView: (viewId: string) => void;
};

export function createLogReportController({ els, state, t, setActiveView }: LogReportDeps) {
  function selectLog(logName: string | null) {
    state.selectedLogName = logName || null;
    if (state.selectedLogName) {
      els.reportLogSelect.value = state.selectedLogName;
    }
  }

  function renderReportSelect() {
    els.reportLogSelect.innerHTML = "";
    if (!state.logs.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = t("logs.no_available");
      els.reportLogSelect.appendChild(opt);
      state.selectedLogName = null;
      return;
    }
    for (const row of state.logs) {
      const opt = document.createElement("option");
      opt.value = row.name;
      opt.textContent = row.name;
      els.reportLogSelect.appendChild(opt);
    }
    if (!state.selectedLogName || !state.logs.some((l: any) => l.name === state.selectedLogName)) {
      state.selectedLogName = state.logs[0].name;
    }
    els.reportLogSelect.value = state.selectedLogName;
  }

  async function deleteLog(logName: string) {
    if (!logName) return;
    const ok = window.confirm(t("logs.delete_confirm", { name: logName }));
    if (!ok) return;
    try {
      await deleteLogApi(logName);
    } catch (err: any) {
      window.alert(err?.message || t("logs.delete_failed"));
      return;
    }
    if (state.selectedLogName === logName) {
      state.selectedLogName = null;
    }
    await refreshLogs();
  }

  async function deleteAllLogs() {
    const logNames = state.logs
      .map((row: any) => row?.name)
      .filter((name: unknown) => typeof name === "string" && name.length > 0);
    if (!logNames.length) return;
    const ok = window.confirm(t("logs.delete_all_confirm", { count: logNames.length }));
    if (!ok) return;

    let deleted = 0;
    let failed = 0;
    let firstError = "";
    for (const logName of logNames) {
      try {
        await deleteLogApi(logName);
        deleted += 1;
      } catch (err: any) {
        failed += 1;
        if (!firstError && err?.message) {
          firstError = String(err.message);
        }
      }
    }

    if (failed > 0) {
      const summary = t("logs.delete_all_partial", {
        deleted,
        total: logNames.length,
        failed,
      });
      window.alert(firstError ? `${summary}\n${firstError}` : summary);
    }

    if (deleted > 0 && state.selectedLogName && logNames.includes(state.selectedLogName)) {
      state.selectedLogName = null;
    }
    await refreshLogs();
  }

  function renderLogsTable() {
    if (els.deleteAllLogsBtn) {
      els.deleteAllLogsBtn.disabled = state.logs.length === 0;
    }
    if (!state.logs.length) {
      els.logsSummary.textContent = t("logs.none");
      els.logsTableBody.innerHTML = `<tr><td colspan="4">${escapeHtml(t("logs.none_found"))}</td></tr>`;
      renderReportSelect();
      return;
    }
    els.logsSummary.textContent = t("logs.available_count", { count: state.logs.length });
    els.logsTableBody.innerHTML = state.logs
      .map(
        (row: any) => `
      <tr>
        <td>${row.name}</td>
        <td>${fmtTs(row.updated_at)}</td>
        <td class="numeric">${fmtBytes(row.size_bytes)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn--primary select-log-btn" data-log="${row.name}">${escapeHtml(t("logs.use_in_report"))}</button>
            <a class="btn btn--muted" href="${logDownloadUrl(row.name)}" target="_blank" rel="noopener">${escapeHtml(t("logs.raw"))}</a>
            <button class="btn btn--danger delete-log-btn" data-log="${row.name}">${escapeHtml(t("logs.delete"))}</button>
          </div>
        </td>
      </tr>`,
      )
      .join("");
    els.logsTableBody.querySelectorAll(".select-log-btn").forEach((btn: any) => {
      btn.addEventListener("click", () => {
        const logName = btn.dataset.log || null;
        selectLog(logName);
        setActiveView("reportView");
      });
    });
    els.logsTableBody.querySelectorAll(".delete-log-btn").forEach((btn: any) => {
      btn.addEventListener("click", async () => {
        const logName = btn.dataset.log || "";
        await deleteLog(logName);
      });
    });
    renderReportSelect();
  }

  async function refreshLogs() {
    try {
      const payload = await getLogs();
      state.logs = Array.isArray(payload.logs) ? payload.logs : [];
      renderLogsTable();
    } catch (_err) {
      state.logs = [];
      renderLogsTable();
    }
  }

  function renderInsights(summary: any) {
    if (!summary || typeof summary !== "object") {
      els.reportInsights.textContent = t("report.no_insights");
      return;
    }
    const findings = Array.isArray(summary.findings) ? summary.findings : [];
    const topFindings = findings
      .slice(0, 4)
      .map((f: any) => {
        const confidence = typeof f.confidence_0_to_1 === "number" ? fmt(f.confidence_0_to_1, 2) : "0.00";
        const source = f.suspected_source || "unknown";
        const detail = f.evidence_summary || "";
        return `<p><strong>${source}</strong> (${escapeHtml(t("report.confidence", { value: confidence }))}): ${detail}</p>`;
      })
      .join("");
    const speedCoverage = summary?.data_quality?.speed_coverage || {};
    const speedPct =
      typeof speedCoverage.non_null_pct === "number"
        ? `${fmt(speedCoverage.non_null_pct, 1)}%`
        : t("report.missing");
    const speedMin =
      typeof speedCoverage.min_kmh === "number" ? fmt(speedCoverage.min_kmh, 1) : t("report.missing");
    const speedMax =
      typeof speedCoverage.max_kmh === "number" ? fmt(speedCoverage.max_kmh, 1) : t("report.missing");
    const rawSampleRate =
      typeof summary.raw_sample_rate_hz === "number"
        ? `${fmt(summary.raw_sample_rate_hz, 1)} Hz`
        : t("report.missing");
    const skippedReason =
      typeof summary.speed_breakdown_skipped_reason === "string"
        ? `<p><strong>${escapeHtml(t("report.speed_analysis"))}:</strong> ${summary.speed_breakdown_skipped_reason}</p>`
        : "";
    els.reportInsights.innerHTML = `
      <p><strong>${escapeHtml(t("report.file"))}:</strong> ${summary.file_name || "--"}</p>
      <p><strong>${escapeHtml(t("report.run_id"))}:</strong> ${summary.run_id || t("report.missing")}</p>
      <p><strong>${escapeHtml(t("report.duration"))}:</strong> ${fmt(summary.duration_s, 1)} s</p>
      <p><strong>${escapeHtml(t("report.rows"))}:</strong> ${summary.rows || 0}</p>
      <p><strong>${escapeHtml(t("report.raw_sample_rate"))}:</strong> ${rawSampleRate}</p>
      <p><strong>${escapeHtml(t("report.speed_coverage"))}:</strong> ${speedPct} (${speedMin}-${speedMax} km/h)</p>
      <hr />
      ${skippedReason}
      ${topFindings || `<p>${escapeHtml(t("report.no_findings_for_run"))}</p>`}
    `;
  }

  async function loadReportInsights() {
    const logName = els.reportLogSelect.value;
    if (!logName) return;
    selectLog(logName);
    try {
      const summary = await getLogInsights(logName, state.lang);
      renderInsights(summary);
    } catch (_err) {
      els.reportInsights.textContent = t("report.unable_load_insights");
    }
  }

  function downloadReportPdf() {
    const logName = els.reportLogSelect.value;
    if (!logName) return;
    selectLog(logName);
    window.open(reportPdfUrl(logName, state.lang), "_blank", "noopener");
  }

  function bindEvents() {
    els.refreshLogsBtn.addEventListener("click", refreshLogs);
    if (els.deleteAllLogsBtn) {
      els.deleteAllLogsBtn.addEventListener("click", deleteAllLogs);
    }
    els.reportLogSelect.addEventListener("change", () => selectLog(els.reportLogSelect.value || null));
    els.loadInsightsBtn.addEventListener("click", loadReportInsights);
    els.downloadReportBtn.addEventListener("click", downloadReportPdf);
  }

  return {
    renderReportSelect,
    renderLogsTable,
    refreshLogs,
    loadReportInsights,
    bindEvents,
  };
}
