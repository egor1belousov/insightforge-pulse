import { expect, test } from "@playwright/test";
import { PREFIX, api, demo, ready, registerHr, stamp } from "./helpers";

const LONG = "Я".repeat(6000);

test.describe("Формы: негативные проверки", () => {
  test("N01 пустые поля входа и регистрации → понятная ошибка, не 500", async ({ page }) => {
    const login = await page.request.post("/api/auth/login", { data: { email: "", password: "" } });
    expect(login.status()).toBeLessThan(500);
    expect([400, 401, 422]).toContain(login.status());
    const reg = await page.request.post("/api/auth/register", { data: { name: "", email: "", password: "", organization: "", program: "" } });
    expect([400, 422]).toContain(reg.status());
    await page.goto("/login");
    await page.locator("form button[type=submit]").click();
    // браузер не даёт отправить пустую форму (required) или показывает ошибку
    const invalid = await page.locator("input:invalid").count();
    const err = await page.locator(".form-error:visible").count();
    expect(invalid + err).toBeGreaterThan(0);
  });

  for (const bad of ["abc", "a@", "@b.ru", "qa test@example.com"]) {
    test(`N02 невалидная почта «${bad}» при регистрации → 400`, async ({ page }) => {
      const r = await page.request.post("/api/auth/register", { data: { name: `${PREFIX}x`, email: bad, password: "QaTest!Passw0rd", organization: `${PREFIX}o`, program: "p" } });
      expect([400, 422]).toContain(r.status());
    });
  }

  test("N03 строки 6000 символов: регистрация, анкета, заметка, запрос к HR — без 500", async ({ browser }) => {
    const p = await (await browser.newContext()).newPage();
    const tag = stamp();
    const reg = await p.request.post("/api/auth/register", { data: { name: LONG, email: `${PREFIX}long_${tag}@example.com`, password: "QaTest!Passw0rd", organization: LONG, program: LONG } });
    expect(reg.status(), "регистрация с длинными полями").toBeLessThan(500);
    const d = await (await browser.newContext()).newPage();
    await demo(d, "hr");
    const pid = (await (await d.request.get("/api/dashboard")).json()).pairs[0].id;
    const note = await api(d, "POST", `/api/pairs/${pid}/notes`, { text: LONG });
    expect(note.status(), "заметка 6000 символов").toBeLessThan(500);
    const course = await api(d, "PUT", "/api/forms/channels", { email: true, tg: true, site: true, junk: LONG });
    expect(course.status()).toBeLessThan(500);
    const s = await (await browser.newContext()).newPage();
    await demo(s, "intern");
    const me = await (await s.request.get("/api/me")).json();
    const answers: Record<string, string> = {};
    for (const q of me.questionnaire.questions) if (q.qtype !== "text") answers[q.id] = "5";
    const resp = await api(s, "POST", "/api/responses", { answers, comment: LONG });
    expect(resp.status(), "анкета с комментарием 6000 символов").toBeLessThan(500);
    const talk = await api(s, "POST", "/api/me/talk", { topic: LONG, text: LONG });
    expect(talk.status(), "запрос к HR 6000 символов").toBeLessThan(500);
  });

  test("N04 эмодзи, кириллица, пробелы по краям сохраняются корректно", async ({ page }) => {
    const tag = stamp();
    const name = `  ${PREFIX}Иван Пётр 😀 ${tag}  `;
    const r = await page.request.post("/api/auth/register", { data: { name, email: `  ${PREFIX}emoji_${tag}@Example.com  `, password: "QaTest!Passw0rd", organization: `${PREFIX}ёж «кавычки»`, program: "p" } });
    expect(r.status()).toBe(200);
    const me = await r.json();
    expect(me.name).toBe(name.trim());
    expect(me.email).toBe(`${PREFIX}emoji_${tag}@example.com`);
  });

  test("N05 двойная отправка: регистрация одной почты — одна учётная запись", async ({ browser }) => {
    const tag = stamp();
    const data = { name: `${PREFIX}dbl`, email: `${PREFIX}dbl_${tag}@example.com`, password: "QaTest!Passw0rd", organization: `${PREFIX}o`, program: "p" };
    const a = await browser.newContext();
    const b = await browser.newContext();
    const [r1, r2] = await Promise.all([a.request.post("/api/auth/register", { data }), b.request.post("/api/auth/register", { data })]);
    const codes = [r1.status(), r2.status()].sort();
    expect(codes[0]).toBe(200);
    expect(codes[1], "вторая регистрация той же почты").toBeGreaterThanOrEqual(400);
    expect(codes[1]).toBeLessThan(500);
  });

  test("N05b двойная отправка анкеты — одна запись за месяц", async ({ browser }) => {
    const s = await (await browser.newContext()).newPage();
    await demo(s, "intern");
    const me = await (await s.request.get("/api/me")).json();
    const answers: Record<string, string> = {};
    for (const q of me.questionnaire.questions) if (q.qtype !== "text") answers[q.id] = "4";
    const [a, b] = await Promise.all([api(s, "POST", "/api/responses", { answers, comment: "" }), api(s, "POST", "/api/responses", { answers, comment: "" })]);
    expect(a.status()).toBe(200);
    expect(b.status()).toBeLessThan(500);
    await s.goto("/demo/hr");
    const rows = (await (await s.request.get("/api/forms/mailing")).json()).rows.filter((r: any) => r.external_id === "С-104");
    expect(rows.length).toBe(1);
  });

  test("N06 API в обход формы: неверные типы, нет полей, нет CSRF", async ({ page }) => {
    expect((await page.request.post("/api/auth/login", { data: { email: 123, password: ["x"] } })).status()).toBe(422);
    expect((await page.request.post("/api/auth/login", { data: "not json", headers: { "content-type": "application/json" } })).status()).toBe(422);
    await demo(page, "hr");
    const noCsrf = await page.request.post("/api/programs", { data: { name: `${PREFIX}без csrf` } });
    expect(noCsrf.status(), "изменение без CSRF-заголовка").toBe(403);
    const wrongType = await api(page, "PUT", "/api/forms/reminders", { on: "да", first_days: "много" });
    expect(wrongType.status()).toBe(422);
  });
});

test.describe("Авторизация", () => {
  test("A01 неверный пароль → 401 и сообщение в форме", async ({ page }) => {
    const r = await page.request.post("/api/auth/login", { data: { email: "hr@pulse.demo", password: "wrong-password" } });
    expect(r.status()).toBe(401);
    await page.goto("/login");
    await page.locator("#email").fill(`${PREFIX}nobody@example.com`);
    await page.locator("#password").fill("wrong-password-1");
    await page.locator("form button[type=submit]").click();
    await expect(page.locator(".form-error")).toContainText(/Неверн/);
  });

  test("A02 выход и кнопка «назад» — данных нет, API отвечает 401", async ({ page }) => {
    await demo(page, "hr");
    await page.goto("/dashboard");
    await ready(page);
    await page.click("#menu-btn");
    await page.click("#logout-btn");
    await page.waitForURL(/\/login/);
    await page.goBack();
    await ready(page);
    expect((await page.request.get("/api/dashboard")).status()).toBe(401);
    await page.reload();
    await ready(page);
    await expect(page).toHaveURL(/\/login/);
  });

  for (const path of ["/dashboard", "/pairs", "/program", "/forms", "/settings", "/learn", "/me", "/import"]) {
    test(`A03 без входа ${path} → редирект на вход`, async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login\?next=/);
    });
  }

  for (const [role, path] of [["intern", "/dashboard"], ["intern", "/settings"], ["intern", "/program"], ["mentor", "/forms"], ["lead", "/settings"], ["lead", "/program"]]) {
    test(`A04 ${role} на ${path} → своя стартовая страница`, async ({ page }) => {
      await demo(page, role);
      await page.goto(path);
      await expect(page).not.toHaveURL(new RegExp(path + "$"));
    });
  }

  test("A05 чужая роль в API → 403", async ({ browser }) => {
    const intern = await (await browser.newContext()).newPage();
    await demo(intern, "intern");
    const lead = await (await browser.newContext()).newPage();
    await demo(lead, "lead");
    for (const url of ["/api/dashboard", "/api/forms/mailing", "/api/settings", "/api/integrations", "/api/program/overview", "/api/reports"]) {
      expect((await intern.request.get(url)).status(), `стажёр ${url}`).toBe(403);
    }
    for (const url of ["/api/forms/mailing", "/api/settings", "/api/integrations"]) {
      expect((await lead.request.get(url)).status(), `руководитель ${url}`).toBe(403);
    }
    expect((await api(lead, "POST", "/api/auth/invites", { email: `${PREFIX}x@example.com`, role: "intern" })).status()).toBe(403);
  });

  test("A06 подделанная или истёкшая сессия → 401 и вход", async ({ browser }) => {
    const ctx = await browser.newContext();
    await ctx.addCookies([{ name: "pulse_session", value: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.forged", url: test.info().project.use.baseURL! }]);
    const p = await ctx.newPage();
    expect((await p.request.get("/api/auth/me")).status()).toBe(401);
    await p.goto("/dashboard");
    await expect(p).toHaveURL(/\/login/);
  });

  test("A07 ограничение попыток входа: шестая подряд → 429", async ({ page }) => {
    const email = `${PREFIX}ratelimit_${stamp()}@example.com`;
    const codes: number[] = [];
    for (let i = 0; i < 6; i++) codes.push((await page.request.post("/api/auth/login", { data: { email, password: "wrong-" + i } })).status());
    expect(codes.slice(0, 5).every((c) => c === 401)).toBe(true);
    expect(codes[5]).toBe(429);
  });
});
