/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "pages-must-not-import-other-pages",
      comment:
        "Each page under src/pages/<page>/ stands alone; share code through src/ modules outside pages/.",
      severity: "error",
      from: { path: "^src/pages/([^/]+)/" },
      to: { path: "^src/pages/", pathNot: "^src/pages/$1/" },
    },
  ],
  options: {
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
