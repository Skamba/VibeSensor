/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "features-must-not-import-runtime",
      comment:
        "Feature workflows and state owners must stay independent from runtime controllers.",
      severity: "error",
      from: { path: "^src/app/features/" },
      to: { path: "^src/app/runtime/" },
    },
    {
      name: "views-must-not-import-runtime",
      comment:
        "View modules render or decode state but should not reach into runtime controllers.",
      severity: "error",
      from: { path: "^src/app/views/" },
      to: { path: "^src/app/runtime/", dependencyTypesNot: ["type-only"] },
    },
    {
      name: "api-must-not-import-app",
      comment:
        "HTTP transport wrappers stay outside app composition and feature/view state.",
      severity: "error",
      from: { path: "^src/api/" },
      to: { path: "^src/app/" },
    },
    {
      name: "transport-must-not-import-app",
      comment:
        "Transport adapters stay below app state and UI ownership layers.",
      severity: "error",
      from: { path: "^src/transport/" },
      to: { path: "^src/app/" },
    },
    {
      name: "dom-utils-must-stay-dom-only",
      comment:
        "app/dom helpers should stay isolated from feature, runtime, and view modules.",
      severity: "error",
      from: { path: "^src/app/dom/" },
      to: { path: "^src/app/(features|runtime|views)/" },
    },
    {
      name: "generated-http-contracts-behind-api-types",
      comment:
        "Import HTTP contract aliases through src/api/types.ts, not the generated file.",
      severity: "error",
      from: { pathNot: "^src/api/types\\.ts$" },
      to: { path: "^src/generated/http_api_contracts\\.ts$" },
    },
    {
      name: "generated-ws-types-behind-transport",
      comment:
        "Import WS contract data through transport/live_models.ts, server_payload.ts, ws.ts, or ws_payload_validator.ts.",
      severity: "error",
      from: {
        pathNot:
          "^src/(server_payload|ws|ws_payload_validator)\\.ts$|^src/transport/live_models\\.ts$",
      },
      to: { path: "^src/contracts/ws_payload_types\\.ts$" },
    },
    {
      name: "generated-ws-schema-behind-validator",
      comment: "Only ws_payload_validator.ts may import the generated WS schema.",
      severity: "error",
      from: { pathNot: "^src/ws_payload_validator\\.ts$" },
      to: { path: "^src/contracts/ws_payload_schema\\.generated\\.ts$" },
    },
  ],
  options: {
    // Track `import type` edges so the generated-contract rules see type-only imports.
    tsPreCompilationDeps: true,
    tsConfig: {
      fileName: "tsconfig.json",
    },
    includeOnly: "^src",
    doNotFollow: {
      path: "node_modules",
    },
    exclude: {
      path: "^(dist|tests|node_modules)",
    },
  },
};
