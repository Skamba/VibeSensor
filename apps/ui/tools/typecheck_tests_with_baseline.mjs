import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

const project = "tsconfig.test.json";
const baselinePath = "tests/typecheck-baseline.txt";
const diagnosticPattern = /^.+\(\d+,\d+\): error TS\d+: .+$/gm;

function readBaseline(path) {
  if (!existsSync(path)) {
    return [];
  }
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

const tscBin = process.platform === "win32" ? "tsc.cmd" : "tsc";
const result = spawnSync(tscBin, ["--noEmit", "--pretty", "false", "-p", project], {
  encoding: "utf8",
  shell: process.platform === "win32",
});

if (result.error) {
  throw result.error;
}

const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
const diagnostics = uniqueSorted(output.match(diagnosticPattern) ?? []);
const baseline = uniqueSorted(readBaseline(baselinePath));
const baselineSet = new Set(baseline);
const diagnosticSet = new Set(diagnostics);
const unexpected = diagnostics.filter((diagnostic) => !baselineSet.has(diagnostic));
const resolved = baseline.filter((diagnostic) => !diagnosticSet.has(diagnostic));

if (result.status !== 0 && diagnostics.length === 0) {
  process.stderr.write(output);
  process.exit(result.status ?? 1);
}

if (unexpected.length > 0 || resolved.length > 0) {
  if (unexpected.length > 0) {
    console.error("Unexpected UI test typecheck diagnostics:");
    for (const diagnostic of unexpected) {
      console.error(diagnostic);
    }
  }

  if (resolved.length > 0) {
    console.error("Resolved UI test typecheck diagnostics still listed in baseline:");
    for (const diagnostic of resolved) {
      console.error(diagnostic);
    }
  }

  console.error(
    `Update ${baselinePath} so the UI test typecheck baseline matches the current diagnostics.`,
  );
  process.exit(1);
}

if (diagnostics.length > 0) {
  console.log(`UI test typecheck matched ${diagnostics.length} known baseline diagnostics.`);
} else {
  console.log("UI test typecheck passed with no diagnostics.");
}
