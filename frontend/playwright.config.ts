import { defineConfig } from "@playwright/test";

const REAL_STACK_TESTS = [
  "**/real-stack.spec.ts",
  "**/real-stack-recovery.spec.ts",
  "**/real-stack-research.spec.ts",
  "**/real-stack-deep-journey.spec.ts",
  // Boots its own real-stack webServer via playwright.g12-acceptance.config.ts.
  "**/g12-acceptance.spec.ts",
];
/**
 * Paid, real-model acceptance runs. They boot the real backend and the
 * configured provider (see playwright.real-acceptance.config.ts), so the
 * default suite must never collect them: this gate has no backend and no cost
 * authorization, and a PR must not be able to trigger paid model calls.
 */
const PAID_ACCEPTANCE_TESTS = ["**/real-acceptance.spec.ts"];
const DEFAULT_IGNORES = [...REAL_STACK_TESTS, ...PAID_ACCEPTANCE_TESTS];
const STANDARD_FIXTURE_IGNORES = [
  ...DEFAULT_IGNORES,
  "**/complex-content.spec.ts",
];

export default defineConfig({
  testDir: "./e2e",
  testIgnore: DEFAULT_IGNORES,
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 7_000,
  },
  outputDir: "test-results/artifacts",
  reporter: [
    ["line"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      testIgnore: STANDARD_FIXTURE_IGNORES,
      use: {
        browserName: "chromium",
        channel: process.env.PLAYWRIGHT_USE_SYSTEM_CHROME ? "chrome" : undefined,
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "mobile-chromium",
      testIgnore: STANDARD_FIXTURE_IGNORES,
      use: {
        browserName: "chromium",
        channel: process.env.PLAYWRIGHT_USE_SYSTEM_CHROME ? "chrome" : undefined,
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: "narrow-chromium",
      testMatch: [
        "**/complex-content.spec.ts",
        "**/extension-lab-journeys.spec.ts",
        "**/recovery-visibility.spec.ts",
      ],
      testIgnore: DEFAULT_IGNORES,
      use: {
        browserName: "chromium",
        channel: process.env.PLAYWRIGHT_USE_SYSTEM_CHROME ? "chrome" : undefined,
        viewport: { width: 360, height: 520 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: "desktop-firefox",
      testMatch: ["**/golden-journeys.spec.ts"],
      testIgnore: DEFAULT_IGNORES,
      use: {
        browserName: "firefox",
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "desktop-webkit",
      testMatch: ["**/golden-journeys.spec.ts"],
      testIgnore: DEFAULT_IGNORES,
      use: {
        browserName: "webkit",
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
