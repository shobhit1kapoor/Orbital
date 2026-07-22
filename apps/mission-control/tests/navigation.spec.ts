import { expect, test } from "@playwright/test";

test("renders all seven Mission Control screens", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Every autonomous agent must earn")).toBeVisible();
  for (const label of ["Evidence Parity", "Replay Theater", "Causal Graph", "Authority Frontier", "Safety Case", "Certificate"]) {
    await page.getByRole("button", { name: label }).click();
    await expect(page.getByRole("heading", { name: label, exact: false }).first()).toBeVisible();
  }
});
