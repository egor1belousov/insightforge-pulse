import { expect, test } from "@playwright/test";
import { PREFIX, api, demo, ready, registerHr } from "./helpers";

test.describe("Состояния", () => {
  test("S01 сервер отвечает 500 → понятное сообщение, не пустой экран", async ({ page }) => {
    await demo(page, "hr");
    await page.route("**/api/dashboard?*", (r) => r.fulfill({ status: 500, body: "Internal Server Error" }));
    await page.route("**/api/dashboard", (r) => r.fulfill({ status: 500, body: "Internal Server Error" }));
    await page.goto("/dashboard");
    await ready(page);
    await expect(page.locator(".topbar")).toBeVisible();
    const text = await page.locator("#main").innerText();
    expect(text.trim().length, "в основной области есть текст").toBeGreaterThan(10);
    await expect(page.getByText(/не так|ошибк|повтор|не удалось/i).first()).toBeVisible();
  });

  test("S02 API отвечает очень долго → видно состояние загрузки", async ({ page }) => {
    await demo(page, "hr");
    await page.route("**/api/dashboard*", async (r) => { await new Promise((res) => setTimeout(res, 15_000)); await r.continue(); });
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    const text = await page.locator("#main").innerText();
    expect(text, "пока данные грузятся, пользователь видит, что идёт загрузка").toMatch(/Загруж|загрузк|…/);
  });

  test("S03 медленная сеть (3G) — дашборд открывается за 30 секунд", async ({ page, browserName }) => {
    test.skip(browserName !== "chromium", "эмуляция сети — только Chromium (CDP)");
    await demo(page, "hr");
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 400, downloadThroughput: (400 * 1024) / 8, uploadThroughput: (400 * 1024) / 8 });
    const t0 = Date.now();
    await page.goto("/dashboard", { timeout: 60_000 });
    await expect(page.locator(".hero h1")).toBeVisible({ timeout: 30_000 });
    test.info().annotations.push({ type: "3G, мс", description: String(Date.now() - t0) });
  });

  test("S04 офлайн во время работы → понятное сообщение", async ({ page }) => {
    await demo(page, "hr");
    await page.goto("/forms");
    await ready(page);
    await page.context().setOffline(true);
    await page.getByRole("tab", { name: "Конструктор" }).click();
    await page.waitForTimeout(1500);
    const visible = await page.locator("#toast:visible, .form-error:visible").allInnerTexts();
    await page.context().setOffline(false);
    expect(visible.join(" "), "сообщение об отсутствии сети").toMatch(/сет|интернет|подключ|не удалось/i);
  });

  test("S05 пустой поток: дашборд, рассылка, пары — пустые состояния", async ({ page }) => {
    await registerHr(page.request);
    await page.goto("/dashboard");
    await ready(page);
    await expect(page.getByText(/Поток готов к запуску/)).toBeVisible();
    await page.goto("/forms");
    await ready(page);
    await expect(page.getByText(/В потоке пока нет пар/)).toBeVisible();
    await page.goto("/program");
    await ready(page);
    await expect(page.getByText(/Пар пока нет/)).toBeVisible();
    await page.goto("/pairs");
    await ready(page);
    expect((await page.locator("#main").innerText()).length).toBeGreaterThan(20);
  });
});

test.describe("Навигация", () => {
  test("V01 все ссылки отвечают без 4xx/5xx (аноним и HR)", async ({ browser }) => {
    test.setTimeout(240_000);
    const broken: string[] = [];
    for (const role of [null, "hr"]) {
      const p = await (await browser.newContext()).newPage();
      if (role) await demo(p, role);
      const seen = new Set<string>();
      const queue = role ? ["/dashboard", "/pairs", "/program", "/forms", "/learn", "/settings"] : ["/", "/login", "/register"];
      for (const start of queue) {
        await p.goto(start);
        await ready(p);
        const hrefs = await p.$$eval("a[href]", (as) => as.map((a) => (a as HTMLAnchorElement).href));
        for (const h of hrefs) {
          const u = new URL(h);
          if (u.origin !== new URL(p.url()).origin || u.pathname.startsWith("/demo/") || seen.has(u.pathname + u.search)) continue;
          seen.add(u.pathname + u.search);
          const r = await p.request.get(u.pathname + u.search, { maxRedirects: 0 });
          if (r.status() >= 400) broken.push(`${r.status()} ${u.pathname}${u.search} (со страницы ${start})`);
        }
      }
    }
    expect(broken, "битые ссылки").toEqual([]);
  });

  test("V02 несуществующая страница → HTML-страница 404 с выходом на главную", async ({ page }) => {
    const r = await page.goto(`/${PREFIX}missing_page`);
    expect(r!.status()).toBe(404);
    expect(r!.headers()["content-type"], "страница 404 — HTML, а не JSON").toContain("text/html");
    await expect(page.getByRole("link", { name: /глав|назад|Пульс/i }).first()).toBeVisible();
  });

  test("V03 глубокие ссылки открывают нужную вкладку", async ({ page }) => {
    await demo(page, "hr");
    const pid = (await (await page.request.get("/api/dashboard")).json()).pairs[0].id;
    await page.goto(`/pairs?id=${pid}&tab=act`);
    await ready(page);
    await expect(page.getByRole("tab", { name: "Действия" })).toHaveAttribute("aria-selected", "true");
    await page.goto("/learn?tab=tests");
    await ready(page);
    await expect(page.getByRole("tab", { name: "Тесты" })).toHaveAttribute("aria-selected", "true");
    await page.goto("/forms?tab=build");
    await ready(page);
    await expect(page.getByRole("tab", { name: "Конструктор" })).toHaveAttribute("aria-selected", "true");
  });

  test("V04 обновление страницы и кнопки назад/вперёд сохраняют вкладку", async ({ page }) => {
    await demo(page, "hr");
    await page.goto("/pairs");
    await ready(page);
    await page.getByRole("tab", { name: /Люди/ }).click();
    await ready(page);
    await page.reload();
    await ready(page);
    await expect(page.getByRole("tab", { name: /Люди/ })).toHaveAttribute("aria-selected", "true");
    await page.goto("/forms");
    await ready(page);
    await page.goBack();
    await ready(page);
    await expect(page).toHaveURL(/\/pairs/);
    await page.goForward();
    await ready(page);
    await expect(page).toHaveURL(/\/forms/);
  });
});
