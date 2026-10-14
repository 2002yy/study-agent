import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e", testMatch: "conversation-continuous.spec.ts", workers: 1,
  timeout: 30_000, outputDir: "test-results/conversation-continuous", reporter: "line",
  use: { baseURL: "http://127.0.0.1:5178", browserName: "chromium", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 5178 --strictPort", url: "http://127.0.0.1:5178", reuseExistingServer: false },
});
