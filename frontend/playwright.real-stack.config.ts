import { defineConfig } from "@playwright/test";
import { API_HEADERS } from "./e2e/apiAuth";

export default defineConfig({
  testDir: "./e2e",
  testMatch: [
    "real-stack.spec.ts",
    "real-stack-recovery.spec.ts",
    "real-stack-research.spec.ts",
    "real-stack-deep-journey.spec.ts",
    "api-token-required.spec.ts",
  ],
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
  },
  outputDir: "test-results/real-stack-artifacts",
  reporter: [
    ["line"],
    ["html", { outputFolder: "playwright-real-stack-report", open: "never" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5173",
    channel: process.env.PLAYWRIGHT_USE_SYSTEM_CHROME ? "chrome" : undefined,
    // The server now refuses every private request without its token; fixture
    // calls made with `request` / `page.request` need the same header the app
    // sends. The app's own token path is exercised by api-token-required.spec.ts.
    extraHTTPHeaders: API_HEADERS,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "real-stack-desktop",
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "real-stack-mobile",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  webServer: [
    {
      command:
        "python -m uvicorn tools.real_stack_research_test_server:app --host 127.0.0.1 --port 8000",
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        STUDY_AGENT_E2E_RESET: "1",
        STUDY_AGENT_E2E_ROOT: "frontend/test-results/real-stack-runtime",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: ".",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        VITE_DEV_API_TARGET: "http://127.0.0.1:8000",
      },
    },
  ],
});
