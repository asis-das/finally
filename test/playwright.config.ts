import { defineConfig, devices } from "@playwright/test";

/**
 * FinAlly E2E configuration.
 *
 * Two supported ways to run (see README.md):
 *   1. BASE_URL against an already-running instance (default http://localhost:8000)
 *   2. docker-compose.test.yml, which sets BASE_URL=http://app:8000 inside the network
 *
 * Workers are pinned to 1 on purpose. FinAlly is a single-user application: every
 * test mutates the same cash balance, the same positions and the same watchlist.
 * Parallel workers would not be testing the app, they would be testing SQLite.
 */

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./fixtures/global-setup.ts",

  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,

  // Deliberately 0 by default: a retry that turns a red into a green hides a real
  // race. Set PW_RETRIES=1 only when you are chasing an intermittent failure.
  retries: Number(process.env.PW_RETRIES ?? 0),

  // Prices tick every ~500ms and the LLM mock is instant, but a cold container
  // plus a first paint of three Recharts surfaces is not.
  timeout: 90_000,
  expect: { timeout: 20_000 },

  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["json", { outputFile: "playwright-report/results.json" }],
  ],

  outputDir: "test-results",

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Desktop-first layout: the xl breakpoint (1280px) is where the real
        // three-column terminal appears, so that is what we test.
        viewport: { width: 1600, height: 1000 },
      },
    },
  ],
});
