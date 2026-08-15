import { test, expect, Page } from "@playwright/test";

const faultTargets = {
  envoy: process.env.ENVOY_FAULT_URL ?? "http://127.0.0.1:18087",
  nginx: process.env.NGINX_FAULT_URL ?? "http://127.0.0.1:18086",
};

async function runTerminalFault(page: Page, endpoint: string, faultMode: string) {
  const query = new URLSearchParams({
    endpoint,
    rpc: "stream-text",
    count: "2",
    delayMs: "50",
    message: `fault-${faultMode}`,
    faultMode,
  });

  await page.goto(`/?${query.toString()}`);

  await expect
    .poll(
      () => page.evaluate(() => (window as any).__grpcWebHarness?.status),
      { timeout: 8_000 },
    )
    .not.toBe("running");

  return page.evaluate(() => (window as any).__grpcWebHarness);
}

test("rst-before-headers: NGINX matches Envoy before downstream DATA", async ({ page }) => {
  const envoy = await runTerminalFault(page, faultTargets.envoy, "rst-before-headers");
  const nginx = await runTerminalFault(page, faultTargets.nginx, "rst-before-headers");

  expect(envoy.status).toBe("error");
  expect(nginx.status).toBe("error");
  expect(envoy.events).toEqual([]);
  expect(nginx.events).toEqual([]);
  expect(nginx.error.code).toBe(envoy.error.code);
});

// Do not assert a synthetic terminal grpc-status after DATA for raw upstream
// transport resets. The Envoy grpc-web reference itself keeps the browser RPC
// in `running` after delivering prior DATA for this fault shape, so demanding
// an immediate error/status/end event from NGINX would be stricter than the
// reference implementation. M7 verifies DATA preservation, worker health and
// bounded lifecycle for these after-DATA faults at the protocol layer instead.
