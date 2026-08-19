import { test, expect } from "@playwright/test";

test("login as admin and loads seeded patients", async ({ page }) => {
  await page.goto("/he/login");

  await page.locator('input[name="username"]').fill("admin");
  await page.locator('input[name="password"]').fill("admin-password");

  await page.getByRole("button", { name: /התחבר/i }).click();

  // Should land on /he (dashboard) after successful credentials login.
  await expect(page).toHaveURL(/\/he\/?$/);

  await page.goto("/he/patients");

  // Seeded sample patient (see prisma/seed.ts).
  await expect(page.getByText("Test Patient")).toBeVisible();
});

