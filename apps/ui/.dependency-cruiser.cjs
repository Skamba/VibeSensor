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
      to: { path: "^src/app/runtime/" },
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
  ],
  options: {
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
