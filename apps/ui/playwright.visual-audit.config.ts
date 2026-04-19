import { defineConfig } from "@playwright/test";

import { visualAuditProjects, visualBaseConfig } from "./playwright.config";

export default defineConfig({
  ...visualBaseConfig,
  projects: visualAuditProjects,
});
