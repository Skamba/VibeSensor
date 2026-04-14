import { createElementNode, type RenderChild } from "./dom_render";
import type { HistoryRowViewModel, HistorySummaryChipTone } from "./history_table_models";

type HistoryTableRendererParams = {
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

function createSummaryChipsElement(
  chips: HistoryRowViewModel["summaryChips"],
): HTMLDivElement {
  return createElementNode("div", {
    className: "history-row__summary-chips",
    children: chips.map((chip) =>
      createElementNode("span", {
        className: `history-row__summary-chip${chipModifier(chip.tone)}`,
        text: chip.text,
      }),
    ),
  });
}

function createCollapsedRowActionsElement(
  row: HistoryRowViewModel,
): HTMLElement {
  if (row.collapsedAction.hintText) {
    return createElementNode("div", {
      className: "history-row__action-hint",
      text: row.collapsedAction.hintText,
    });
  }
  return createElementNode("div", {
    className: "table-actions history-row__actions",
    children: [
      createElementNode("button", {
        className: "btn btn--muted",
        attrs: {
          type: "button",
          disabled: row.collapsedAction.pdfLoading,
        },
        data: {
          runAction: "download-pdf",
          run: row.runId,
        },
        text: row.collapsedAction.pdfLabel ?? "",
      }),
    ],
  });
}

function createDiagnosisSummaryElement(row: HistoryRowViewModel): HTMLDivElement | null {
  if (!row.summaryHeadline && !row.summaryMeta) {
    return null;
  }
  return createElementNode("div", {
    className: "history-row__diagnosis",
    children: [
      row.summaryHeadline
        ? createElementNode("div", {
            className: "history-row__diagnosis-title",
            text: row.summaryHeadline,
          })
        : null,
      row.summaryMeta
        ? createElementNode("div", {
            className: "history-row__diagnosis-meta",
            text: row.summaryMeta,
          })
        : null,
    ],
  });
}

function createHeatmapElement(
  heatmap: NonNullable<HistoryRowViewModel["details"]>["heatmap"],
): HTMLDivElement {
  const header = createElementNode("div", {
    className: "history-heatmap__header",
    children: [
      createElementNode("div", {
        className: "history-heatmap__title",
        text: heatmap.title,
      }),
    ],
  });
  if (heatmap.stateMessage) {
    return createElementNode("div", {
      className: "history-heatmap",
      children: [
        header,
        createElementNode("p", {
          className: heatmap.stateTone === "error" ? "history-inline-error" : "subtle",
          text: heatmap.stateMessage,
        }),
      ],
    });
  }
  const zones = heatmap.zones.map((zone) => {
    const isEmpty =
      zone.valueLabel === null || zone.accentColor === null || zone.fillPercent === null;
    return createElementNode("div", {
      classes: [
        "history-heatmap__zone",
        isEmpty && "history-heatmap__zone--empty",
        !isEmpty && zone.strongest && "history-heatmap__zone--strongest",
      ],
      attrs: {
        style: isEmpty
          ? `grid-area:${zone.gridArea}`
          : `grid-area:${zone.gridArea};--history-heatmap-accent:${zone.accentColor};--history-heatmap-fill:${zone.fillPercent}%;`,
        title: isEmpty ? zone.label : `${zone.label}: ${zone.valueLabel}`,
      },
      data: {
        locationKey: zone.key,
      },
      children: [
        createElementNode("div", {
          className: "history-heatmap__zone-label",
          text: zone.label,
        }),
        createElementNode("div", {
          classes: [
            "history-heatmap__zone-value",
            isEmpty && "history-heatmap__zone-value--empty",
          ],
          text: zone.valueLabel ?? "",
        }),
        createElementNode("div", {
          className: "history-heatmap__zone-meter",
          attrs: { "aria-hidden": "true" },
          children: isEmpty
            ? []
            : [
                createElementNode("span", {
                  className: "history-heatmap__zone-meter-fill",
                }),
              ],
        }),
      ],
    });
  });
  const extras = heatmap.extras.length
    ? createElementNode("div", {
        className: "history-heatmap__extras",
        children: heatmap.extras.map((extra) =>
          createElementNode("div", {
            className: "history-heatmap__extra-chip",
            text: extra,
          }),
        ),
      })
    : null;
  return createElementNode("div", {
    className: "history-heatmap",
    children: [
      header,
      createElementNode("div", {
        className: "history-heatmap__grid",
        children: zones,
      }),
      extras,
    ],
  });
}

function createPrimaryFindingElement(
  primary: NonNullable<NonNullable<HistoryRowViewModel["details"]>["insights"]["primary"]>,
): HTMLDivElement {
  return createElementNode("div", {
    className: "history-findings-overview",
    children: [
      createElementNode("div", {
        className: "history-findings-overview__header",
        children: [
          createElementNode("div", {
            className: "history-findings-overview__eyebrow",
            text: primary.eyebrow,
          }),
        ],
      }),
      createElementNode("div", {
        className: `history-diagnosis-card history-diagnosis-card--${primary.tone}`,
        children: [
          createElementNode("div", {
            className: "history-diagnosis-card__header",
            children: [
              createElementNode("div", {
                className: "history-diagnosis-card__copy",
                children: [
                  createElementNode("div", {
                    className: "history-findings-overview__headline",
                    text: primary.headline,
                  }),
                  createElementNode("div", {
                    className: "history-diagnosis-card__signature",
                    text: primary.signature,
                  }),
                ],
              }),
              createElementNode("span", {
                className: `history-diagnosis-card__confidence history-diagnosis-card__confidence--${primary.tone}`,
                text: primary.confidence,
              }),
            ],
          }),
          primary.explanation
            ? createElementNode("p", {
                className: "history-findings-overview__explanation",
                text: primary.explanation,
              })
            : null,
          createElementNode("div", {
            className: "history-findings-overview__chips",
            children: primary.chips.map((chip) =>
              createElementNode("div", {
                className: "history-findings-chip",
                children: [
                  createElementNode("span", {
                    className: "history-findings-chip__label",
                    text: chip.label,
                  }),
                  createElementNode("strong", {
                    text: chip.value,
                  }),
                ],
              }),
            ),
          }),
          primary.nextStep && primary.nextStepLabel
            ? createElementNode("div", {
                className: "history-diagnosis-card__next-step",
                children: [
                  createElementNode("span", {
                    className: "history-diagnosis-card__next-step-label",
                    text: primary.nextStepLabel,
                  }),
                  createElementNode("strong", {
                    text: primary.nextStep,
                  }),
                ],
              })
            : null,
        ],
      }),
    ],
  });
}

function createSecondaryFindingElement(
  finding: NonNullable<HistoryRowViewModel["details"]>["insights"]["visibleSecondary"][number],
): HTMLLIElement {
  return createElementNode("li", {
    className: `history-finding-card history-finding-card--secondary history-finding-card--${finding.tone}`,
    children: [
      createElementNode("div", {
        className: "history-finding-card__header",
        children: [
          createElementNode("div", {
            className: "history-finding-card__title-group",
            children: [
              createElementNode("strong", {
                className: "history-finding-card__title",
                text: finding.source,
              }),
              createElementNode("span", {
                className: "history-finding-card__signal",
                text: finding.signature,
              }),
            ],
          }),
          createElementNode("span", {
            className: `history-finding-card__confidence history-finding-card__confidence--${finding.tone}`,
            text: finding.confidence,
          }),
        ],
      }),
      createElementNode("div", {
        className: "history-finding-card__meta",
        children: [
          createElementNode("div", {
            className: "history-finding-card__meta-item",
            children: [
              createElementNode("span", {
                className: "history-finding-card__label",
                text: finding.locationLabel,
              }),
              createElementNode("strong", {
                text: finding.location,
              }),
            ],
          }),
          createElementNode("div", {
            className: "history-finding-card__meta-item",
            children: [
              createElementNode("span", {
                className: "history-finding-card__label",
                text: finding.speedBandLabel,
              }),
              createElementNode("strong", {
                text: finding.speedBand,
              }),
            ],
          }),
        ],
      }),
      createElementNode("p", {
        className: "history-finding-card__summary",
        text: finding.evidenceSummary,
      }),
    ],
  });
}

function createInsightsElement(
  insights: NonNullable<HistoryRowViewModel["details"]>["insights"],
): HTMLDivElement {
  let body: RenderChild = createElementNode("div", {
    className: "history-panel-state",
    text: insights.stateMessage ?? "",
  });
  if (insights.primary) {
    body = [
      createPrimaryFindingElement(insights.primary),
      insights.secondaryTitle
        ? createElementNode("div", {
            className: "history-secondary-findings",
            children: [
              createElementNode("div", {
                className: "history-secondary-findings__title",
                text: insights.secondaryTitle,
              }),
              createElementNode("ul", {
                className: "history-findings-list history-findings-list--secondary",
                children: insights.visibleSecondary.map((finding) =>
                  createSecondaryFindingElement(finding),
                ),
              }),
              insights.hiddenSecondary.length > 0 && insights.showMoreLabel
                ? createElementNode("details", {
                    className: "history-secondary-findings__more",
                    children: [
                      createElementNode("summary", {
                        text: insights.showMoreLabel,
                      }),
                      createElementNode("ul", {
                        className: "history-findings-list history-findings-list--secondary",
                        children: insights.hiddenSecondary.map((finding) =>
                          createSecondaryFindingElement(finding),
                        ),
                      }),
                    ],
                  })
                : null,
            ],
          })
        : null,
    ];
  } else if (insights.emptyMessage) {
    body = createElementNode("ul", {
      className: "history-findings-list history-findings-list--secondary",
      children: [
        createElementNode("li", {
          className: "history-finding-card history-finding-card--empty",
          text: insights.emptyMessage,
        }),
      ],
    });
  }
  return createElementNode("div", {
    className: "history-insights-block",
    children: [
      createElementNode("div", {
        className: "history-panel-header",
        children: [
          createElementNode("div", {
            className: "history-panel-header__eyebrow",
            text: insights.headerEyebrow,
          }),
        ],
      }),
      body,
    ],
  });
}

function createWarningsElement(
  warnings: NonNullable<HistoryRowViewModel["details"]>["warnings"],
): HTMLDivElement | null {
  if (!warnings.length) {
    return null;
  }
  return createElementNode("div", {
    className: "history-warning-list",
    children: warnings.map((warning) =>
      createElementNode("div", {
        className: `history-warning-banner history-warning-banner--${warning.severity}`,
        children: [
          createElementNode("strong", {
            text: warning.title,
          }),
          warning.detail
            ? createElementNode("div", {
                className: "history-warning-banner__detail",
                text: warning.detail,
              })
            : null,
        ],
      }),
    ),
  });
}

function createRunActionsPanelElement(
  row: HistoryRowViewModel,
  details: NonNullable<HistoryRowViewModel["details"]>,
  params: HistoryTableRendererParams,
): HTMLDivElement {
  return createElementNode("div", {
    className: "history-details-footer",
    children: [
      createElementNode("div", {
        className: "history-details-footer__copy",
        children: [
          createElementNode("div", {
            className: "history-details-footer__eyebrow",
            text: details.footerEyebrow,
          }),
          createElementNode("div", {
            className: "history-details-footer__body",
            text: details.footerBody,
          }),
        ],
      }),
      createElementNode("div", {
        className: "history-details-footer__actions",
        children: [
          createElementNode("a", {
            className: "btn btn--muted",
            attrs: {
              href: params.historyExportUrl(row.runId),
              download: `${row.runId}.zip`,
            },
            data: {
              runAction: "download-raw",
              run: row.runId,
            },
            text: details.exportLabel,
          }),
          createElementNode("button", {
            className: "btn btn--danger-quiet",
            attrs: { type: "button" },
            data: {
              runAction: "delete-run",
              run: row.runId,
            },
            text: details.deleteLabel,
          }),
        ],
      }),
    ],
  });
}

function createDetailsRowElement(
  row: HistoryRowViewModel,
  details: NonNullable<HistoryRowViewModel["details"]>,
  params: HistoryTableRendererParams,
): HTMLTableRowElement {
  return createElementNode("tr", {
    className: "history-details-row",
    children: [
      createElementNode("td", {
        attrs: { colspan: 4 },
        children: [
          createElementNode("div", {
            className: "history-details-card",
            children: [
              createElementNode("div", {
                className: "history-details-header",
                children: [
                  createElementNode("div", {
                    className: "history-details-header__copy",
                    children: [
                      createElementNode("div", {
                        className: "history-details-header__eyebrow",
                        text: details.titleEyebrow,
                      }),
                      createElementNode("div", {
                        className: "history-details-header__title",
                        text: details.title,
                      }),
                      details.runSummary
                        ? createElementNode("div", {
                            className: "history-run-summary",
                            text: details.runSummary,
                          })
                        : null,
                    ],
                  }),
                  createElementNode("div", {
                    className: "history-details-header__actions",
                    children: [
                      details.reloadActionLabel
                        ? createElementNode("button", {
                            className: "btn btn--muted",
                            attrs: {
                              type: "button",
                              disabled: details.reloadActionDisabled,
                            },
                            data: {
                              runAction: "load-insights",
                            },
                            text: details.reloadActionLabel,
                          })
                        : details.loadingStatusText
                          ? createElementNode("div", {
                              className: "history-details-header__status",
                              text: details.loadingStatusText,
                            })
                          : null,
                      details.insightsError
                        ? createElementNode("span", {
                            className: "history-inline-error",
                            text: details.insightsError,
                          })
                        : null,
                    ],
                  }),
                ],
              }),
              createWarningsElement(details.warnings),
              createElementNode("div", {
                className: "history-results-layout",
                children: [
                  createElementNode("div", {
                    className: "history-main-column",
                    children: [
                      createInsightsElement(details.insights),
                      createRunActionsPanelElement(row, details, params),
                    ],
                  }),
                  createElementNode("div", {
                    className: "history-evidence-column",
                    children: [
                      createElementNode("div", {
                        className: "history-evidence-panel",
                        children: [createHeatmapElement(details.heatmap)],
                      }),
                    ],
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}

function createRowElement(
  row: HistoryRowViewModel,
): HTMLTableRowElement {
  const rowError = row.pdfError
    ? createElementNode("div", {
        className: "history-inline-error",
        text: row.pdfError,
      })
    : null;
  return createElementNode("tr", {
    className: `history-row${row.isExpanded ? " history-row--expanded" : ""}`,
    data: {
      runRow: 1,
      run: row.runId,
    },
    children: [
      createElementNode("td", {
        className: "history-row__primary-cell",
        children: [
          createElementNode("div", {
            className: "history-row__run",
            children: [
              createElementNode("div", {
                className: "history-row__run-heading",
                children: [
                  createElementNode("div", {
                    className: "history-row__car-context",
                    children: [
                      createElementNode("span", {
                        className: "history-row__car-label",
                        text: row.carLabel,
                      }),
                      createElementNode("span", {
                        className: "history-row__car-name",
                        text: row.carName,
                      }),
                    ],
                  }),
                  createElementNode("div", {
                    className: "history-row__run-id",
                    text: row.runId,
                  }),
                ],
              }),
              createSummaryChipsElement(row.summaryChips),
              createElementNode("div", {
                className: "history-row__detail-affordance",
                children: [
                  createDiagnosisSummaryElement(row),
                  createElementNode("button", {
                    className: `history-row__toggle${row.isExpanded ? " history-row__toggle--expanded" : ""}`,
                    attrs: {
                      type: "button",
                      "aria-expanded": row.isExpanded ? "true" : "false",
                      "aria-label": row.toggleTitle,
                      title: row.toggleTitle,
                    },
                    data: {
                      runToggle: "details",
                      run: row.runId,
                    },
                    children: [
                      createElementNode("span", {
                        className: "history-row__toggle-icon",
                        attrs: { "aria-hidden": "true" },
                      }),
                      createElementNode("span", {
                        className: "history-row__toggle-copy",
                        children: [
                          createElementNode("span", {
                            className: "history-row__toggle-title",
                            text: row.toggleLabel,
                          }),
                        ],
                      }),
                    ],
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
      createElementNode("td", {
        className: "history-row__meta-cell history-row__meta-cell--started",
        children: [
          createElementNode("span", {
            className: "history-row__meta-label",
            text: row.startedLabel,
          }),
          createElementNode("span", {
            className: "history-row__meta-value",
            text: row.startedAtText,
          }),
        ],
      }),
      createElementNode("td", {
        className: "history-row__meta-cell history-row__meta-cell--samples numeric",
        children: [
          createElementNode("span", {
            className: "history-row__meta-label",
            text: row.sizeLabel,
          }),
          createElementNode("span", {
            className: "history-row__meta-value",
            text: row.sampleCountText,
          }),
        ],
      }),
      createElementNode("td", {
        className: "history-row__meta-cell history-row__meta-cell--actions",
        children: [
          createElementNode("span", {
            className: "history-row__meta-label",
            text: row.quickReportLabel,
          }),
          createCollapsedRowActionsElement(row),
          rowError,
        ],
      }),
    ],
  });
}

export function createHistoryTableRowElements(
  rows: HistoryRowViewModel[],
  params: HistoryTableRendererParams,
): HTMLTableRowElement[] {
  return rows.flatMap((row) => {
    const renderedRow = createRowElement(row);
    return row.details ? [renderedRow, createDetailsRowElement(row, row.details, params)] : [renderedRow];
  });
}
