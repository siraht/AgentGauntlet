import { createRequire } from "node:module";

const requireFromAqg = createRequire(
  new URL("../../quality/tools/js/package.json", import.meta.url),
);
const { test, expect } = requireFromAqg("@playwright/test");
const AxeBuilder = requireFromAqg("@axe-core/playwright").default;

test("primary page loads without severe accessibility or console failures", async ({
  page,
}) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  const response = await page.goto("/");
  expect(response, "navigation should produce an HTTP response").not.toBeNull();
  expect(
    response.status(),
    "primary page should load successfully",
  ).toBeLessThan(400);
  await expect(page.locator("body")).toBeVisible();
  await expect(page).toHaveTitle(/\S+/);

  const accessibility = await new AxeBuilder({ page }).analyze();
  const severe = accessibility.violations.filter((item) =>
    ["serious", "critical"].includes(item.impact),
  );
  expect(severe, JSON.stringify(severe, null, 2)).toEqual([]);
  expect(browserErrors, browserErrors.join("\n")).toEqual([]);
});
