import * as v from "valibot";

type IssuePathItem = { key?: unknown };

function formatIssuePath(
  path: ReadonlyArray<IssuePathItem> | undefined,
): string {
  if (!path || path.length === 0) {
    return "/";
  }

  const segments: string[] = [];
  for (const item of path) {
    if (item.key === undefined) {
      continue;
    }
    segments.push(String(item.key));
  }
  return segments.length > 0 ? `/${segments.join("/")}` : "/";
}

export function parseRuntimeBoundary<T>(options: {
  boundary: string;
  payload: unknown;
  schema: v.GenericSchema<T>;
}): T {
  if (v.is(options.schema, options.payload)) {
    // These boundary schemas assert shape only; keep original object identity for hot paths.
    return options.payload as T;
  }
  const result = v.safeParse(options.schema, options.payload);
  if (result.success) {
    return options.payload as T;
  }
  const issue = result.issues[0];
  throw new Error(
    `Invalid ${options.boundary}: ${formatIssuePath(issue?.path)} ${issue?.message ?? "is invalid"}`,
  );
}
