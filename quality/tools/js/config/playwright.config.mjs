import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const project = JSON.parse(
  fs.readFileSync(new URL("../../../project.json", import.meta.url), "utf8"),
);
const web = project.web || {};
const webServer = web.start_command?.length
  ? {
      command: web.start_command.join(" "),
      url: web.base_url || "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
      stdout: "pipe",
      stderr: "pipe",
    }
  : undefined;

export default defineConfig({
  testDir: process.cwd(),
  testMatch: [
    "**/e2e/**/*.{spec,test}.{js,mjs,ts}",
    "**/acceptance/**/*.{spec,test}.{js,mjs,ts}",
    "**/tests/aqg-browser/**/*.{spec,test}.{js,mjs,ts}",
  ],
  outputDir: ".aqg/work/playwright/results",
  reporter: [
    ["list"],
    ["json", { outputFile: ".aqg/work/playwright/results.json" }],
    ["html", { outputFolder: ".aqg/work/playwright/html", open: "never" }],
  ],
  forbidOnly: true,
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  use: {
    baseURL: web.base_url || "http://127.0.0.1:4173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },
  webServer,
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
