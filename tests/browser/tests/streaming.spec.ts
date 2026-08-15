import { test, expect } from "@playwright/test";

const targets = [
  ["envoy", process.env.ENVOY_URL ?? "http://127.0.0.1:18081"],
  // Enable the identical target after M5. No NGINX-specific client code is allowed.
  // ["nginx", process.env.NGINX_URL ?? "http://127.0.0.1:18080"],
] as const;

for (const [name, endpoint] of targets) {
  test(`${name}: React client receives server stream incrementally`, async ({ page }) => {
    const query = new URLSearchParams({
      endpoint,
      count: "3",
      delayMs: "200",
      message: "browser",
    });

    await page.goto(`/?${query.toString()}`);
    await expect(page.getByTestId("status")).toHaveText("done");

    const result = await page.evaluate(() => (window as any).__grpcWebHarness);
    expect(result.error).toBeNull();
    expect(result.events.map((x: any) => x.sequence)).toEqual([1, 2, 3]);
    expect(result.events.map((x: any) => x.message)).toEqual([
      "browser",
      "browser",
      "browser",
    ]);

    // Catch obvious whole-stream buffering while allowing CI scheduling jitter.
    expect(result.events[0].t).toBeLessThan(result.events[2].t - 80);
  });
}
