import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./staging",
  timeout: 60_000,
  workers: 1,
  outputDir: "test-results/staging-artifacts",
  reporter: [
    ["line"],
    ["json", { outputFile: "test-results/staging-results.json" }],
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { browserName: "webkit" } },
  ],
});
