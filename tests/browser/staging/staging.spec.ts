import { expect, Page, test } from "@playwright/test";

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for M15 staging acceptance`);
  }
  return value.replace(/\/$/, "");
}

const endpoint = requiredEnv("STAGING_ENDPOINT");
const unavailableEndpoint = requiredEnv("STAGING_UNAVAILABLE_ENDPOINT");
const timeoutEndpoint = requiredEnv("STAGING_TIMEOUT_ENDPOINT");

async function start(page: Page, target: string, options: Record<string, string>) {
  const query = new URLSearchParams({ endpoint: target, ...options });
  await page.goto(`/?${query.toString()}`);
}

async function waitTerminal(page: Page, timeout = 10_000) {
  await expect
    .poll(() => page.evaluate(() => (window as any).__grpcWebHarness?.status), { timeout })
    .not.toBe("running");
  return page.evaluate(() => (window as any).__grpcWebHarness);
}

test("staging: binary unary uses the unchanged React grpc-web client", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "unary-binary",
    message: "m15-staging-binary",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("done");
  expect(result.error).toBeNull();
  expect(result.events).toHaveLength(1);
  expect(result.events[0].message).toBe("m15-staging-binary");
});

test("staging: grpc-web-text unary completes", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "unary-text",
    message: "m15-staging-text",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("done");
  expect(result.error).toBeNull();
  expect(result.events[0].message).toBe("m15-staging-text");
});

test("staging: server stream is incremental before RPC completion", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "stream-text",
    count: "3",
    delayMs: "500",
    message: "m15-staging-stream",
  });

  await expect
    .poll(() => page.evaluate(() => (window as any).__grpcWebHarness?.events?.length ?? 0), { timeout: 5_000 })
    .toBeGreaterThan(0);
  const intermediate = await page.evaluate(() => (window as any).__grpcWebHarness);
  expect(intermediate.status).toBe("running");
  expect(intermediate.events[0].sequence).toBe(1);

  const result = await waitTerminal(page, 10_000);
  expect(result.status).toBe("done");
  expect(result.events.map((item: any) => item.sequence)).toEqual([1, 2, 3]);
  expect(result.events.every((item: any) => item.message === "m15-staging-stream")).toBe(true);
});

test("staging: non-zero grpc-status/message reaches React", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "fail-text",
    code: "3",
    message: "m15-staging-invalid-argument",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("error");
  expect(result.error.code).toBe(3);
  expect(result.error.message).toContain("m15-staging-invalid-argument");
});

test("staging: browser cancellation remains terminal after first DATA", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "stream-text",
    count: "20",
    delayMs: "80",
    cancelAfter: "1",
    message: "m15-staging-cancel",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("cancelled");
  expect(result.error).toBeNull();
  expect(result.events.map((item: any) => item.sequence)).toEqual([1]);
  await page.waitForTimeout(350);
  const stable = await page.evaluate(() => (window as any).__grpcWebHarness);
  expect(stable.status).toBe("cancelled");
  expect(stable.events.map((item: any) => item.sequence)).toEqual([1]);
});

test("staging: grpc-timeout becomes DEADLINE_EXCEEDED", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "stream-text",
    count: "3",
    delayMs: "500",
    grpcTimeout: "150m",
    message: "m15-staging-deadline",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("error");
  expect(result.error.code).toBe(4);
});

test("staging: local unavailable normalization is UNAVAILABLE", async ({ page }) => {
  await start(page, unavailableEndpoint, {
    rpc: "stream-text",
    count: "1",
    delayMs: "50",
    message: "m15-staging-unavailable",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("error");
  expect(result.error.code).toBe(14);
});

test("staging: local proxy timeout normalization is DEADLINE_EXCEEDED", async ({ page }) => {
  await start(page, timeoutEndpoint, {
    rpc: "stream-text",
    count: "1",
    delayMs: "500",
    message: "m15-staging-timeout",
  });
  const result = await waitTerminal(page);
  expect(result.status).toBe("error");
  expect(result.error.code).toBe(4);
});

test("staging: longer stream completes without browser-side buffering/corruption", async ({ page }) => {
  await start(page, endpoint, {
    rpc: "stream-text",
    count: "50",
    delayMs: "50",
    message: "m15-staging-long-stream",
  });
  const result = await waitTerminal(page, 20_000);
  expect(result.status).toBe("done");
  expect(result.error).toBeNull();
  expect(result.events).toHaveLength(50);
  expect(result.events[0].sequence).toBe(1);
  expect(result.events[49].sequence).toBe(50);
});
