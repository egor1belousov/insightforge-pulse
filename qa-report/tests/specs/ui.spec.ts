import { expect, test } from "@playwright/test";
import { demo, noHScroll, ready, watch } from "./helpers";

// Скриншоты и проверки вёрстки — на всех вьюпортах и браузерах (тег @ui)
const PAGES: [string | null, string][] = [
  [null, "/"], [null, "/login"], [null, "/register"],
  ["hr", "/dashboard"], ["hr", "/pairs"], ["hr", "/program"], ["hr", "/forms"], ["hr", "/learn"], ["hr", "/settings"],
  ["lead", "/dashboard"], ["intern", "/me"], ["intern", "/learn"], ["mentor", "/me"],
];

for (const [role, path] of PAGES) {
  test(`U01/U02 ${role || "аноним"} ${path}: скриншот, без скролла вбок, консоль и сеть чистые @ui`, async ({ page }, info) => {
    const errors = watch(page);
    if (role) await demo(page, role);
    await page.goto(path);
    await ready(page);
    // прокрутка, чтобы проявились блоки с анимацией появления
    await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); } scrollTo(0, 0); });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `../screenshots/pages/${info.project.name}/${(role || "anon")}${path.replace(/\//g, "_")}.png`, fullPage: true });
    await noHScroll(page);
    const broken = await page.$$eval("img", (imgs) => imgs.filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src));
    expect(broken, "сломанные изображения").toEqual([]);
    expect(errors, "ошибки консоли и упавшие запросы").toEqual([]);
  });
}

test("U03 мобильная панель вкладок, модалка и выпадающее меню на тач-экране @mobile", async ({ page }) => {
  await demo(page, "hr");
  await page.goto("/dashboard");
  await ready(page);
  await expect(page.locator(".tabbar")).toBeVisible();
  await page.locator(".tabbar a", { hasText: "Анкеты" }).tap();
  await expect(page).toHaveURL(/\/forms/);
  await ready(page);
  await page.locator("[data-answers]").first().tap();
  await expect(page.locator(".modal")).toBeVisible();
  const box = (await page.locator(".modal").boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1);
  await page.locator(".modal [data-close]").tap();
  await expect(page.locator(".modal")).toHaveCount(0);
  await page.locator("#menu-btn").tap();
  await expect(page.locator("#menu-pop")).toBeVisible();
  await page.locator("#stream-btn").tap();
  await expect(page.locator("#stream-pop")).toBeVisible();
  await page.locator("#chat-fab").tap();
  await expect(page.locator(".ai-panel")).toBeVisible();
});
