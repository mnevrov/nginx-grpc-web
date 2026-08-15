import { test, expect, Page } from "@playwright/test";

const faultTargets = {
  envoy: process.env.ENVOY_FAULT_URL ?? "http://127.0.0.1:18087",
  nginx: process.env.NGINX_FAULT_URL ?? "http://127.0.0.1:18086",
};

async function runFault(page: Page, endpoint: string, faultMode: string) {
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
      {
        timeout: 8_000,
        message: `fault=${faultMode} snapshot=${JSON.stringify(
          await page.evaluate(() => (window as any).__grpcWebHarness),
        )}`,
      },
    )
    .not.toBe("running");

  return page.evaluate(() => (window as any).__grpcWebHarness);
}

for (const mode of ["rst-before-headers"] as const) {
  test(`${mode}: NGINX matches Envoy before downstream DATA`, async ({ page }) => {
    const envoy = await runFault(page, faultTargets.envoy, mode);
    const nginx = await runFault(page, faultTargets.nginx, mode);

    expect(envoy.status).toBe("error");
    expect(nginx.status).toBe("error");
    expect(envoy.events).toEqual([]);
    expect(nginx.events).toEqual([]);
    expect(nginx.error.code).toBe(envoy.error.code);
  });
}

for (const mode of ["rst-after-data", "tcp-reset-after-data"] as const) {
  test(`${mode}: prior DATA survives and terminal behavior matches Envoy`, async ({ page }) => {
    const envoy = await runFault(page, faultTargets.envoy, mode);
    const nginx = await runFault(page, faultTargets.nginx, mode);

    expect(envoy.status).toBe("error");
    expect(nginx.status).toBe("error");
    expect(envoy.events.map((x: any) => x.sequence)).toEqual([1]);
    expect(nginx.events.map((x: any) => x.sequence)).toEqual([1]);
    expect(envoy.events[0].message).toBe("before-transport-fault");
    expect(nginx.events[0].message).toBe("before-transport-fault");
    expect(nginx.error.code).toBe(envoy.error.code);
  });
}
