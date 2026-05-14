import { expect, test } from "vitest";
import { createAppState } from "../src/app/ui_app_state";
import {
  createFeatureHarness,
  ensureRunDetail,
  historyListRun,
  installHistoryFeatureTestLifecycle,
  mswServer,
} from "./history_feature_test_support";
import {
  buildHistoryHandlers,
  makeDeleteHistoryRunPayload,
  makeHistoryListPayload,
} from "./msw/handlers/history";

installHistoryFeatureTestLifecycle();

test("history feature skips deletion when confirmation is declined", async () => {
  const state = createAppState();
  state.history.runs.value = [historyListRun("run-42")];
  const confirmationMessages: string[] = [];
  const { feature } = createFeatureHarness(state, {
    requestConfirmation: async (message) => {
      confirmationMessages.push(message);
      return false;
    },
  });

  await feature.onHistoryTableAction("delete-run", "run-42");

  expect(confirmationMessages).toEqual([
    'history.delete_confirm:{"name":"run-42"}',
  ]);
  expect(state.history.runs.value.map((run) => run.run_id)).toEqual(["run-42"]);
});

test("history feature reports partial delete failures", async () => {
  const state = createAppState();
  state.history.runs.value = [
    historyListRun("run-001"),
    historyListRun("run-002"),
  ];
  state.history.expandedRunId.value = "run-001";
  ensureRunDetail(state, "run-001");
  ensureRunDetail(state, "run-002");

  const { feature, errors, getRenderCount, getLatestModel } =
    createFeatureHarness(state);
  const deleteRequests: string[] = [];
  mswServer.use(
    ...buildHistoryHandlers({
      list: makeHistoryListPayload({
        runs: [historyListRun("run-002", { status: "analyzing" })],
      }),
      deleteRun: (request) => {
        const url = new URL(request.url);
        deleteRequests.push(url.pathname);
        if (url.pathname === "/api/history/run-001") {
          return makeDeleteHistoryRunPayload({ run_id: "run-001" });
        }
        if (url.pathname === "/api/history/run-002") {
          return { detail: "delete failed", status: 500 };
        }
        return { detail: `Unexpected request: ${url.pathname}`, status: 500 };
      },
    }),
  );

  await feature.deleteAllRuns();

  expect(deleteRequests).toEqual([
    "/api/history/run-001",
    "/api/history/run-002",
  ]);
  expect(state.history.deleteAllRunsInFlight.value).toBe(false);
  expect(state.history.expandedRunId.value).toBeNull();
  expect(getRenderCount()).toBeGreaterThanOrEqual(2);
  expect(errors).toHaveLength(1);
  expect(errors[0]).toContain("history.delete_all_partial");
  expect(errors[0]).toContain("delete failed");
  expect(getLatestModel()?.table?.kind).toBe("rows");
});
