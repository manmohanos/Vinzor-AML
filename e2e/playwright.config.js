// How the officer journey is driven.
//
// The server is started by Playwright rather than by hand, against a
// throwaway workspace, so a run leaves nothing behind and two runs cannot
// see each other's records. `--workspace` is given an absolute path in a
// temp directory: the log is append-only, so a test that wrote into a real
// workspace would have written there permanently.
//
// One browser, not five. This suite exists to prove the officer journey
// works and to catch a screen that renders nothing -- not to certify
// Safari. A matrix here would triple CI time for a product whose users are
// compliance officers on desktop Chrome.

const { defineConfig, devices } = require("@playwright/test");
const os = require("os");
const path = require("path");

const PORT = process.env.VINZOR_E2E_PORT || 8891;
const WORKSPACE = path.join(
  os.tmpdir(),
  `vinzor-e2e-${process.pid}.db`
);

module.exports = defineConfig({
  testDir: "./tests",
  // A failing journey is a real failure. Retrying it once in CI would turn
  // an intermittent bug -- exactly the kind a compliance product must not
  // have -- into a green tick.
  retries: 0,
  reporter: process.env.CI ? "list" : "html",
  timeout: 60_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],

  webServer: {
    // No VINZOR_NIGHTLY: the overnight sweep must not start screening a
    // whole book in the middle of a test run, and its absence is itself
    // something the journey asserts on.
    command:
      `python -m vinzor serve --workspace "${WORKSPACE}" --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 120_000,
    cwd: path.join(__dirname, ".."),
    stdout: "pipe",
    stderr: "pipe",
  },
});
