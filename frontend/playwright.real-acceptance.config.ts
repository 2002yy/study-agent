import { defineConfig } from "@playwright/test";

/**
 * REAL-MODEL acceptance harness (not the stubbed real-stack gate).
 *
 * Boots the actual application (`src.api:app`) with the locally configured
 * provider (.env -> DeepSeek) and real search, then drives the frozen
 * scenarios in `docs/evidence/real-acceptance-2026/`.
 *
 * Budget is the operator-approved total across all three scenarios; the
 * 300s per-scenario cap is the test timeout.
 */

const PYTHON = String.raw`C:\Users\Zhang\Desktop\study agent\.venv\Scripts\python.exe`;
const TARGET = process.env.REAL_ACCEPTANCE_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "real-acceptance.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 300_000,
  expect: { timeout: 300_000 },
  outputDir: "test-results/real-acceptance",
  reporter: [["line"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "real-acceptance-desktop",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: [
    {
      command:
        `"${PYTHON}" -m uvicorn src.api:app --host 127.0.0.1 --port 8000`,
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        STUDY_AGENT_API_TOKEN: "",
        STUDY_AGENT_RUNTIME_DB:
          "frontend/test-results/real-acceptance/runtime/runtime.db",
        STUDY_AGENT_CURRENT_EXPORT_DIR:
          "frontend/test-results/real-acceptance/runtime/current",
        STUDY_AGENT_ARCHIVE_EXPORT_DIR:
          "frontend/test-results/real-acceptance/runtime/archive",
        RAG_VECTOR_BACKEND: "local",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: ".",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_DEV_API_TARGET: TARGET },
    },
  ],
});
