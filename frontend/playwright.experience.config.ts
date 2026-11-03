import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/** Focused A+C UI regression. The complete Golden Journey gate remains unchanged. */
export default defineConfig({
  ...base,
  testMatch: [
    "**/interactive-document.spec.ts",
    "**/interactive-live-replay.spec.ts",
    "**/interactive-cross-domain-replay.spec.ts",
    "**/experience-layout.spec.ts",
    "**/experience-visuals.spec.ts",
    "**/reading-panels.spec.ts",
    "**/panel-resizing.spec.ts",
    "**/typography-appearance.spec.ts",
    "**/sources-layers.spec.ts",
    "**/conversation-continuous.spec.ts",
    "**/chat-role-settings.spec.ts",
    "**/composer-layout.spec.ts",
    "**/accessibility-responsive.spec.ts",
  ],
  // This subset does not generate the complete Golden Journey artifact manifest.
  globalTeardown: undefined,
  projects: base.projects?.filter(project =>
    ["desktop-chromium", "mobile-chromium"].includes(project.name ?? ""),
  ),
});
