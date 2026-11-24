import { expect, request as pwRequest, test } from "@playwright/test";
import { PREFIX, api, csrf, demo, ready, registerHr, stamp } from "./helpers";

test.describe("Безопасность (пассивно)", () => {
  test("B01 http → https и HSTS", async ({ baseURL }) => {
    test.skip(!baseURL!.startsWith("https"), "только для стенда с HTTPS");
    const ctx = await pwRequest.newContext();
    const r = await ctx.get(baseURL!.replace("https://", "http://") + "/", { maxRedirects: 0 });
    expect([301, 308]).toContain(r.status());
    expect(r.headers()["location"]).toMatch(/^https:\/\//);
    const s = await ctx.get(baseURL! + "/");
    expect(s.headers()["strict-transport-security"]).toMatch(/max-age=\d{7,}/);
  });

  test("B02a X-Content-Type-Options и Referrer-Policy", async ({ request }) => {
    const h = (await request.get("/")).headers();
    expect(h["x-content-type-options"]).toBe("nosniff");
    expect(h["referrer-policy"]).toBeTruthy();
  });

  test("B02b Content-Security-Policy задана", async ({ request }) => {
    expect((await request.get("/")).headers()["content-security-policy"], "заголовок CSP").toBeTruthy();
  });

  test("B02c защита от встраивания во фрейм (X-Frame-Options или frame-ancestors)", async ({ request }) => {
    const h = (await request.get("/login")).headers();
    expect(h["x-frame-options"] || (h["content-security-policy"] || "").match(/frame-ancestors/), "кликджекинг").toBeTruthy();
  });

  test("B03 флаги cookie сессии и CSRF", async ({ page, baseURL }) => {
    await demo(page, "hr");
    const cookies = await page.context().cookies();
    const session = cookies.find((c) => c.name === "pulse_session")!;
    expect(session.httpOnly).toBe(true);
    expect(["Lax", "Strict"]).toContain(session.sameSite);
    if (baseURL!.startsWith("https")) expect(session.secure).toBe(true);
    const c = cookies.find((x) => x.name === "pulse_csrf")!;
    expect(["Lax", "Strict"]).toContain(c.sameSite);
    if (baseURL!.startsWith("https")) expect(c.secure).toBe(true);
  });

  test("B04 в JS и ответах об ошибках нет секретов и stack trace", async ({ request }) => {
    const home = await (await request.get("/dashboard", { maxRedirects: 0 })).text();
    const scripts = ["core", "orbs", "shell", "chat", "dashboard", "pairs", "program", "forms", "learn", "settings", "me", "survey", "import"];
    const leaks: string[] = [];
    for (const s of scripts) {
      const js = await (await request.get(`/static/js/${s}.js`)).text();
      for (const re of [/sk-[A-Za-z0-9]{20,}/, /AAG[A-Za-z0-9_-]{30,}/, /y0__[A-Za-z0-9_-]{20,}/, /-----BEGIN/, /secret_key\s*=/i, /client_secret/i]) if (re.test(js)) leaks.push(`${s}.js ${re}`);
    }
    expect(leaks, "секреты в бандлах").toEqual([]);
    expect(home.length).toBeLessThan(10_000);
    const errs = [await request.post("/api/auth/login", { data: "{bad json", headers: { "content-type": "application/json" } }), await request.get("/api/pairs/abc/diagnosis")];
    for (const e of errs) expect(await e.text(), "stack trace в ответе").not.toMatch(/Traceback|File ".*\.py"|sqlalchemy|psycopg/);
  });

  test("B05 XSS: пейлоады в полях выводятся экранированными", async ({ browser }) => {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    let alerted = false;
    p.on("dialog", async (d) => { alerted = true; await d.dismiss(); });
    const payload = `"><svg onload=alert(1)><b>${PREFIX}x</b>`;
    const tag = stamp();
    await p.request.post("/api/auth/register", { data: { name: payload, email: `${PREFIX}xss_${tag}@example.com`, password: "QaTest!Passw0rd", organization: payload, program: payload } });
    await p.goto("/dashboard");
    await ready(p);
    await p.click("#menu-btn");
    await p.click("#stream-btn");
    await p.waitForTimeout(800);
    // заметка HR с пейлоадом в карточке пары (демо)
    const d = await ctx.newPage();
    await demo(d, "hr");
    const pid = (await (await d.request.get("/api/dashboard")).json()).pairs[0].id;
    await api(d, "POST", `/api/pairs/${pid}/notes`, { text: payload });
    await d.goto(`/pairs?id=${pid}&tab=people`);
    await ready(d);
    for (const page of [p, d]) {
      expect(await page.locator("svg[onload]").count(), "внедрённый svg onload").toBe(0);
      // внедрённый тег — <b>, у которого весь текст ровно qa_test_x (экранированный текст пейлоада длиннее)
      const injected = await page.$$eval("b", (els, t) => els.filter((e) => e.textContent === t).length, `${PREFIX}x`);
      expect(injected, "внедрённый тег <b>").toBe(0);
    }
    await expect(d.getByText(payload).first()).toBeVisible();
    expect(alerted, "сработал alert()").toBe(false);
  });

  test("B06 IDOR: чужие пара, ответ, курс и тест недоступны", async ({ browser }) => {
    const a = await (await browser.newContext()).newPage();
    const b = await (await browser.newContext()).newPage();
    await demo(a, "hr");
    await demo(b, "hr");
    const pairB = (await (await b.request.get("/api/dashboard")).json()).pairs[0].id;
    const respB = (await (await b.request.get("/api/forms/mailing")).json()).rows.find((r: any) => r.response_id).response_id;
    const learnB = await (await b.request.get("/api/learn")).json();
    const checks: [string, string][] = [
      ["GET", `/api/pairs/${pairB}/diagnosis`],
      ["GET", `/api/pairs/${pairB}/notes`],
      ["GET", `/api/forms/responses/${respB}`],
      ["GET", `/api/courses/${learnB.courses[0].id}`],
    ];
    for (const [m, url] of checks) expect([403, 404], `${m} ${url}`).toContain((await a.request.fetch(url, { method: m })).status());
    const notes = await api(a, "POST", `/api/pairs/${pairB}/notes`, { text: `${PREFIX}чужая` });
    expect([403, 404]).toContain(notes.status());
    const pub = await api(a, "POST", `/api/tests/${learnB.tests[0].id}/publish`);
    expect([403, 404]).toContain(pub.status());
  });

  test("B07 CORS: чужой Origin не получает разрешающих заголовков", async ({ request }) => {
    const r = await request.get("/api/auth/me", { headers: { Origin: "https://evil.example" } });
    expect(r.headers()["access-control-allow-origin"]).toBeUndefined();
    const pre = await request.fetch("/api/auth/login", { method: "OPTIONS", headers: { Origin: "https://evil.example", "Access-Control-Request-Method": "POST" } });
    expect(pre.headers()["access-control-allow-origin"]).toBeUndefined();
  });
});

test.describe("SEO и отдача", () => {
  test("P03a главная: title, description, lang, favicon", async ({ page }) => {
    await page.goto("/");
    expect((await page.title()).length).toBeGreaterThan(10);
    expect(await page.getAttribute("html", "lang")).toBe("ru");
    expect(await page.locator('link[rel="icon"]').count()).toBeGreaterThan(0);
    expect(await page.locator('meta[name="description"]').count(), "meta description").toBeGreaterThan(0);
  });

  test("P03b Open Graph и canonical", async ({ page }) => {
    await page.goto("/");
    expect(await page.locator('meta[property="og:title"]').count(), "og:title").toBeGreaterThan(0);
    expect(await page.locator('meta[property="og:image"]').count(), "og:image").toBeGreaterThan(0);
    expect(await page.locator('link[rel="canonical"]').count(), "canonical").toBeGreaterThan(0);
  });

  test("P03c robots.txt, sitemap.xml, favicon.ico", async ({ request }) => {
    for (const u of ["/robots.txt", "/sitemap.xml", "/favicon.ico"]) expect((await request.get(u)).status(), u).toBe(200);
  });

  test("P03d HEAD-запрос к главной (проверки доступности, превью ссылок)", async ({ request }) => {
    expect((await request.head("/")).status()).toBe(200);
  });

  test("P02 статика сжимается и кешируется", async ({ request }) => {
    const r = await request.get("/static/css/app.css", { headers: { "Accept-Encoding": "gzip, zstd, br" } });
    const h = r.headers();
    test.info().annotations.push({ type: "app.css", description: `encoding=${h["content-encoding"]} cache-control=${h["cache-control"]} etag=${h["etag"] ? "да" : "нет"}` });
    expect(h["content-encoding"], "сжатие").toMatch(/gzip|zstd|br/);
    expect(h["etag"] || h["last-modified"], "валидатор кеша").toBeTruthy();
  });
});
