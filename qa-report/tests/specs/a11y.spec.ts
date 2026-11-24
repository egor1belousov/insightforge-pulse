import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { demo, ready } from "./helpers";

const PAGES: [string | null, string][] = [
  [null, "/"], [null, "/login"], [null, "/register"],
  ["hr", "/dashboard"], ["hr", "/pairs"], ["hr", "/program"], ["hr", "/forms"], ["hr", "/learn"], ["hr", "/settings"],
  ["intern", "/me"], ["intern", "/learn"],
];

for (const [role, path] of PAGES) {
  test(`X01 axe: ${role || "аноним"} ${path} — без critical/serious`, async ({ page }, info) => {
    if (role) await demo(page, role);
    await page.goto(path);
    await ready(page);
    await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 50)); } scrollTo(0, 0); });
    await page.waitForTimeout(6000); // анимации появления завершились — проверяем итоговый вид
    const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const bad = res.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    await info.attach("axe.json", { body: JSON.stringify(res.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, n: v.nodes.length, sample: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })), null, 1), contentType: "application/json" });
    expect(bad.map((v) => `${v.impact} ${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
  });
}

test("X02 клавиатура: Tab по шапке, видимый фокус, Esc закрывает окно, фокус в окне", async ({ page }) => {
  await demo(page, "hr");
  await page.goto("/forms");
  await ready(page);
  const seen: string[] = [];
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const f = await page.evaluate(() => { const e = document.activeElement as HTMLElement; const cs = getComputedStyle(e); return { tag: e.tagName, txt: (e.textContent || e.getAttribute("aria-label") || "").trim().slice(0, 20), outline: cs.outlineStyle !== "none" || cs.boxShadow !== "none" }; });
    seen.push(f.txt);
    expect(f.outline, `видимый фокус на «${f.txt}»`).toBe(true);
  }
  expect(seen.join("|")).toMatch(/Дашборд|Пары/);
  // окно ответов открывается с клавиатуры и закрывается Esc
  await page.locator("[data-answers]").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".modal")).toBeVisible();
  const inModal = await page.evaluate(() => !!document.activeElement?.closest(".modal"));
  expect(inModal, "фокус переходит в окно").toBe(true);
  for (let i = 0; i < 6; i++) await page.keyboard.press("Tab");
  const stillIn = await page.evaluate(() => !!document.activeElement?.closest(".modal"));
  expect(stillIn, "Tab не уходит из окна (ловушка фокуса)").toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.locator(".modal")).toHaveCount(0);
});

test("X03 у полей есть подписи, у изображений — alt", async ({ page }) => {
  for (const [role, path] of PAGES) {
    if (role) await demo(page, role); else await page.context().clearCookies();
    await page.goto(path);
    await ready(page);
    const unlabeled = await page.$$eval("input:not([type=hidden]), select, textarea", (els) => els.filter((e) => { const id = e.id; return !(e.getAttribute("aria-label") || e.getAttribute("aria-labelledby") || (id && document.querySelector(`label[for="${id}"]`)) || e.closest("label")); }).map((e) => e.outerHTML.slice(0, 80)));
    expect(unlabeled, `${path}: поля без подписи`).toEqual([]);
    const noAlt = await page.$$eval("img:not([alt])", (els) => els.map((e) => (e as HTMLImageElement).src));
    expect(noAlt, `${path}: изображения без alt`).toEqual([]);
  }
});
