from __future__ import annotations

from pathlib import Path

from vibesensor.reports import build_report_pdf, summarize_log


def test_summarize_log_and_pdf(tmp_path: Path) -> None:
    csv_path = tmp_path / "metrics_20260215_120000.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp_iso,client_id,axis,rms,p2p,peak1_hz,peak1_amp,peak2_hz,peak2_amp,peak3_hz,peak3_amp,frames_dropped_total,queue_overflow_drops,speed_mps",
                "2026-02-15T12:00:00+00:00,c1,x,1,2,12.0,5,20,3,35,2,0,0,22",
                "2026-02-15T12:00:02+00:00,c2,y,2,3,24.0,6,11,2,36,1,5,0,22",
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_log(csv_path)
    assert summary["rows"] == 2
    assert summary["duration_s"] == 2.0
    assert summary["dropped_frames_max"] == 5
    assert summary["top_causes"]
    assert "diagnostic_result" in summary
    assert "totals" in summary

    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")
