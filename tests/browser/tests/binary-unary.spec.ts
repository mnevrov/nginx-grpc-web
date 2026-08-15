import { test, expect } from "@playwright/test";

const targets = [
  ["envoy", process.env.ENVOY_URL ?? "http://127.0.0.1:18081"],
  ["nginx", process.env.NGINX_URL ?? "http://127.0.0.1:18080"],
] as const;

for (const [name, endpoint] of targets) {
  test(`${name}: React client completes binary unary call`, async ({ page }) => {
    const query = new URLSearchParams({
      endpoint,
      rpc: "unary-binary",
      message: "browser-binary",
    });

    await page.goto(`/?${query.toString()}`);
    await expect(page.getByTestId("status")).toHaveText("done");
    await expect(page.getByTestId("event-count")).toHaveText("1");

    const result = await page.evaluate(() => (window as any).__grpcWebHarness);
    expect(result.error).toBeNull();
    expect(result.events).toHaveLength(1);
    expect(result.events[0].message).toBe("browser-binary");
    expect(result.events[0].sequence).toBe(1);
  });
}
