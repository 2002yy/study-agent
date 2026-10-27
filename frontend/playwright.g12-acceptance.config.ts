import { defineConfig } from "@playwright/test";
import { API_HEADERS } from "./e2e/apiAuth";

// G12 manual/timing gate acceptance (docs/PROJECT_STATUS.md 10.6).
// Runs against the real stack: real SQLite, real server-side terminal truth.
export default defineConfig({
  testDir: "./e2e",
  testMatch: ["g12-acceptance.spec.ts"],
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  outputDir: "test-results/g12-artifacts",
  reporter: [
    ["line"],
    ["html", { outputFolder: "playwright-g12-report", open: "never" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5175",
    channel: process.env.PLAYWRIGHT_USE_SYSTEM_CHROME ? "chrome" : undefined,
    extraHTTPHeaders: API_HEADERS,
    trace: "retain-on-failure",
    screenshot: "on",
    video: "on",
  },
  projects: [
    {
      name: "g12-desktop",
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "g12-narrow-landscape",
      use: {
        browserName: "chromium",
        viewport: { width: 768, height: 430 },
      },
    },
    {
      name: "g12-mobile",
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
      command: process.env.G12_PYTHON
        ? `"${process.env.G12_PYTHON}" -m uvicorn tools.real_stack_research_test_server:app --host 127.0.0.1 --port 8000`
        : "python -m uvicorn tools.real_stack_research_test_server:app --host 127.0.0.1 --port 8000",
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        STUDY_AGENT_E2E_RESET: "1",
        STUDY_AGENT_E2E_ROOT: "frontend/test-results/g12-runtime",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5175",
      cwd: ".",
      url: "http://127.0.0.1:5175",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        VITE_DEV_API_TARGET: "http://127.0.0.1:8000",
      },
    },
  ],
});
