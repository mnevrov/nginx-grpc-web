import { test, expect } from "@playwright/test";

const targets = [
  ["envoy", process.env.ENVOY_URL ?? "http://127.0.0.1:18081"],
  ["nginx", process.env.NGINX_URL ?? "http://127.0.0.1:18080"],
] as const;

for (const [name, endpoint] of targets) {
  test(`${name}: React client completes text unary call`, async ({ page }) => {
    const query = new URLSearchParams({
      endpoint,
      rpc: "unary-text",
      message: "browser-text",
    });

    await page.goto(`/?${query.toString()}`);
    await expect(page.getByTestId("status")).toHaveText("done");
    await expect(page.getByTestId("event-count")).toHaveText("1");

    const result = await page.evaluate(() => (window as any).__grpcWebHarness);
    expect(result.error).toBeNull();
    expect(result.events).toHaveLength(1);
    expect(result.events[0].message).toBe("browser-text");
    expect(result.events[0].sequence).toBe(1);
  });

  test(`${name}: React client receives text unary grpc error`, async ({ page }) => {
    const query = new URLSearchParams({
      endpoint,
      rpc: "fail-text",
      code: "3",
      message: "browser text failure",
    });

    await page.goto(`/?${query.toString()}`);
    await expect(page.getByTestId("status")).toHaveText("error");

    const result = await page.evaluate(() => (window as any).__grpcWebHarness);
    expect(result.events).toHaveLength(0);
    expect(result.error.code).toBe(3);
    expect(result.error.message).toContain("browser text failure");
  });
}
