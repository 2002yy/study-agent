/** Offline M4-C impact set; golden-journey manifests belong to the full suite. */
import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig(base, {
  testMatch: ["**/acceptance/*.spec.ts"],
  globalSetup: undefined,
  globalTeardown: undefined,
});
