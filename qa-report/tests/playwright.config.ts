import { defineConfig, devices } from "@playwright/test";

// Стенд по умолчанию — https://mgtspulse.ru; другой адрес: QA_BASE=http://localhost:8000
const baseURL = process.env.QA_BASE || "https://mgtspulse.ru";

export default defineConfig({
  testDir: "./specs",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  retries: 0,
  workers: 3,
  outputDir: "../test-results",
  reporter: [["list"], ["html", { outputFolder: "../playwright-report", open: "never" }], ["json", { outputFile: "../results.json" }]],
  use: { baseURL, screenshot: "only-on-failure", trace: "retain-on-failure", locale: "ru-RU" },
  projects: [
    // функционал, безопасность, доступность, SEO — на десктопном Chromium
    { name: "chromium-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
    // вёрстка и мобильные сценарии
    { name: "chromium-768", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 }, hasTouch: true }, grep: /@ui/ },
    { name: "chromium-375", use: { ...devices["iPhone SE"], defaultBrowserType: "chromium" }, grep: /@ui|@mobile/ },
    { name: "firefox-1440", use: { ...devices["Desktop Firefox"], viewport: { width: 1440, height: 900 } }, grep: /@ui/ },
    { name: "firefox-375", use: { ...devices["Desktop Firefox"], viewport: { width: 375, height: 667 } }, grep: /@ui/ },
  ],
});
