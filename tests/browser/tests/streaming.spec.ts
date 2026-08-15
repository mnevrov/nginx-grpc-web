import { test, expect } from "@playwright/test";

const targets = [
  ["envoy", process.env.ENVOY_URL ?? "http://127.0.0.1:18081"],
  ["nginx", process.env.NGINX_URL ?? "http://127.0.0.1:18080"],
] as const;

for (const [name, endpoint] of targets) {
  test(`${name}: React client receives server stream incrementally`, async ({ page }) => {
    const query = new URLSearchParams({
      endpoint,
      count: "3",
      delayMs: "300",
      message: "browser",
    });

    await page.goto(`/?${query.toString()}`);

    // Prove that the real grpc-web client observes DATA before the RPC ends.
    await expect
      .poll(
        () =>
          page.evaluate(
            () => (window as any).__grpcWebHarness?.events?.length ?? 0,
          ),
        { timeout: 4_000 },
      )
      .toBeGreaterThan(0);

    const midStream = await page.evaluate(
      () => (window as any).__grpcWebHarness,
    );
    expect(midStream.status).toBe("running");

    await expect(page.getByTestId("status")).toHaveText("done");

    const result = await page.evaluate(() => (window as any).__grpcWebHarness);
    expect(result.error).toBeNull();
    expect(result.events.map((x: any) => x.sequence)).toEqual([1, 2, 3]);
    expect(result.events.map((x: any) => x.message)).toEqual([
      "browser",
      "browser",
      "browser",
    ]);

    // Whole-stream buffering would make these timestamps nearly identical.
    const gaps = [
      result.events[1].t - result.events[0].t,
      result.events[2].t - result.events[1].t,
    ];
    for (const gap of gaps) {
      expect(gap).toBeGreaterThan(100);
    }
    expect(result.events[2].t - result.events[0].t).toBeGreaterThan(250);
  });
}
