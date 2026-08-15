import { test, expect, Page } from "@playwright/test";

const normalTargets = [
  ["envoy", process.env.ENVOY_URL ?? "http://127.0.0.1:18081"],
  ["nginx", process.env.NGINX_URL ?? "http://127.0.0.1:18080"],
] as const;

const unavailableTargets = {
  envoy: process.env.ENVOY_UNAVAILABLE_URL ?? "http://127.0.0.1:18083",
  nginx: process.env.NGINX_UNAVAILABLE_URL ?? "http://127.0.0.1:18082",
};

const timeoutTargets = {
  envoy: process.env.ENVOY_TIMEOUT_URL ?? "http://127.0.0.1:18085",
  nginx: process.env.NGINX_TIMEOUT_URL ?? "http://127.0.0.1:18084",
};

async function run(page: Page, endpoint: string, options: Record<string, string>) {
  const query = new URLSearchParams({ endpoint, ...options });
  await page.goto(`/?${query.toString()}`);

  await expect
    .poll(
      () => page.evaluate(() => (window as any).__grpcWebHarness?.status),
      { timeout: 5_000 },
    )
    .not.toBe("running");

  return page.evaluate(() => (window as any).__grpcWebHarness);
}

for (const [name, endpoint] of normalTargets) {
  test(`${name}: empty server stream completes cleanly`, async ({ page }) => {
    const result = await run(page, endpoint, {
      rpc: "stream-text",
      empty: "1",
      message: "empty-browser",
    });

    expect(result.status).toBe("done");
    expect(result.events).toEqual([]);
    expect(result.error).toBeNull();
  });

  test(`${name}: mid-stream gRPC failure preserves prior DATA`, async ({ page }) => {
    const result = await run(page, endpoint, {
      rpc: "stream-text",
      count: "4",
      delayMs: "80",
      failAfter: "1",
      failCode: "13",
      failMessage: "midstream-browser-failure",
      message: "before-failure",
    });

    expect(result.status).toBe("error");
    expect(result.events.map((x: any) => x.sequence)).toEqual([1]);
    expect(result.events[0].message).toBe("before-failure");
    expect(result.error.code).toBe(13);
  });

  test(`${name}: grpc-timeout becomes DEADLINE_EXCEEDED`, async ({ page }) => {
    const result = await run(page, endpoint, {
      rpc: "stream-text",
      count: "3",
      delayMs: "500",
      grpcTimeout: "150m",
      message: "deadline-browser",
    });

    expect(result.status).toBe("error");
    expect(result.events).toEqual([]);
    expect(result.error.code).toBe(4);
  });

  test(`${name}: browser cancel stops the stream after first DATA`, async ({ page }) => {
    const result = await run(page, endpoint, {
      rpc: "stream-text",
      count: "20",
      delayMs: "80",
      cancelAfter: "1",
      message: `cancel-${name}`,
    });

    expect(result.status).toBe("cancelled");
    expect(result.events.map((x: any) => x.sequence)).toEqual([1]);
    expect(result.error).toBeNull();

    await page.waitForTimeout(350);
    const stable = await page.evaluate(() => (window as any).__grpcWebHarness);
    expect(stable.status).toBe("cancelled");
    expect(stable.events.map((x: any) => x.sequence)).toEqual([1]);
  });
}

test("unavailable backend: NGINX matches Envoy browser error code", async ({ page }) => {
  const envoy = await run(page, unavailableTargets.envoy, {
    rpc: "stream-text",
    count: "1",
    delayMs: "50",
    message: "unavailable-envoy",
  });
  const nginx = await run(page, unavailableTargets.nginx, {
    rpc: "stream-text",
    count: "1",
    delayMs: "50",
    message: "unavailable-nginx",
  });

  expect(envoy.status).toBe("error");
  expect(nginx.status).toBe("error");
  expect(nginx.error.code).toBe(envoy.error.code);
});

test("proxy timeout: NGINX matches Envoy browser error code", async ({ page }) => {
  const envoy = await run(page, timeoutTargets.envoy, {
    rpc: "stream-text",
    count: "1",
    delayMs: "500",
    message: "timeout-envoy",
  });
  const nginx = await run(page, timeoutTargets.nginx, {
    rpc: "stream-text",
    count: "1",
    delayMs: "500",
    message: "timeout-nginx",
  });

  expect(envoy.status).toBe("error");
  expect(nginx.status).toBe("error");
  expect(nginx.error.code).toBe(envoy.error.code);
});
