import { expect, test } from "@playwright/test";
import { HOME, PREFIX, ROLES, api, csrf, demo, ready, registerHr, stamp } from "./helpers";

test.describe("Функционал", () => {
  test("F01 главная → «Открыть демо» → дашборд HR с меткой «демо»", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Открыть демо/ }).first().click();
    await ready(page);
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator(".demo-chip").first()).toBeVisible();
    await expect(page.locator(".hero h1")).toBeVisible();
  });

  for (const role of ROLES) {
    test(`F02 вход в демо под ролью ${role}`, async ({ page }) => {
      await demo(page, role);
      await expect(page).toHaveURL(new RegExp(HOME[role]));
      const me = await (await page.request.get("/api/auth/me")).json();
      expect(me.role).toBe(role);
    });
  }

  test("F03 регистрация HR: кабинет, поток, стандартная анкета", async ({ page }) => {
    const { r } = await registerHr(page.request);
    expect(r.status()).toBe(200);
    await page.goto("/dashboard");
    await ready(page);
    await expect(page.locator(".demo-chip")).toHaveCount(0);
    const q = await (await page.request.get("/api/questionnaires")).json();
    expect(q.intern.questions.length).toBeGreaterThan(0);
    expect(q.mentor.questions.length).toBeGreaterThan(0);
  });

  test("F04 приглашение наставника → вход по ссылке → виден у HR", async ({ browser }) => {
    const hrCtx = await browser.newContext();
    const hr = await hrCtx.newPage();
    await registerHr(hr.request);
    await hr.goto("/program");
    const tag = stamp();
    const inv = await (await api(hr, "POST", "/api/auth/invites", { email: `${PREFIX}mentor_${tag}@example.com`, role: "mentor" })).json();
    const mCtx = await browser.newContext();
    const m = await mCtx.newPage();
    await m.goto(inv.link);
    await m.locator("#name").fill(`${PREFIX}Наставник`);
    await m.locator("#password").fill("QaTest!Passw0rd");
    await m.getByRole("button", { name: /Войти/ }).click();
    await m.waitForURL(/\/me/);
    const rows = (await (await hr.request.get("/api/forms/mailing")).json()).rows;
    expect(rows.length).toBe(1);
    expect(rows[0].pair).toBe("без пары");
    await hrCtx.close();
    await mCtx.close();
  });

  test("F05 стажёр заполняет анкету в кабинете → у HR «заполнено»", async ({ browser }) => {
    const hrCtx = await browser.newContext();
    const hr = await hrCtx.newPage();
    await registerHr(hr.request);
    await hr.goto("/program");
    const inv = await (await api(hr, "POST", "/api/auth/invites", { email: `${PREFIX}intern_${stamp()}@example.com`, role: "intern" })).json();
    const iCtx = await browser.newContext();
    const i = await iCtx.newPage();
    const r = await i.request.post(`/api/auth/invites/${inv.link.split("/").pop()}/accept`, { data: { name: `${PREFIX}Стажёр`, password: "QaTest!Passw0rd" } });
    expect(r.status()).toBe(200);
    await i.goto("/me");
    await ready(i);
    await expect(i.locator("#survey-box")).toBeVisible();
    const me = await (await i.request.get("/api/me")).json();
    const answers: Record<string, string> = {};
    for (const q of me.questionnaire.questions) if (q.qtype !== "text") answers[q.id] = "7";
    const sent = await api(i, "POST", "/api/responses", { answers, comment: `${PREFIX}комментарий` });
    expect(sent.status()).toBe(200);
    const rows = (await (await hr.request.get("/api/forms/mailing")).json()).rows;
    expect(rows[0].status).toBe("заполнено");
    await hrCtx.close();
    await iCtx.close();
  });

  test("F06 анкета по личной ссылке без входа", async ({ browser }) => {
    const hr = await (await browser.newContext()).newPage();
    await demo(hr, "hr");
    const link = (await (await hr.request.get("/api/survey-links")).json())[0].link;
    const anon = await (await browser.newContext()).newPage();
    await anon.goto(link);
    await ready(anon);
    await expect(anon.locator("form, #survey, .survey, [data-survey]").first()).toBeVisible();
    const info = await (await anon.request.get(link.replace("/survey/", "/api/survey/"))).json();
    const answers: Record<string, string> = {};
    for (const q of info.questionnaire.questions) if (q.qtype !== "text") answers[q.id] = "6";
    const r = await anon.request.post(link.replace("/survey/", "/api/survey/"), { data: { answers, comment: "" } });
    expect(r.status()).toBe(200);
  });

  test("F07 HR открывает карточку пары и все вкладки", async ({ page }) => {
    await demo(page, "hr");
    await page.goto("/pairs");
    await ready(page);
    await expect(page.locator("#explain-btn")).toBeVisible();
    for (const tab of ["Люди", "Действия", "Диагноз"]) {
      await page.getByRole("tab", { name: new RegExp(tab) }).click();
      await ready(page);
      await expect(page.getByRole("tab", { name: new RegExp(tab) })).toHaveAttribute("aria-selected", "true");
    }
  });

  test("F08 HR открывает ответы анкеты (только чтение) и закрывает окно", async ({ page }) => {
    await demo(page, "hr");
    await page.goto("/forms");
    await ready(page);
    await page.locator("[data-answers]").first().click();
    await expect(page.locator(".modal")).toBeVisible();
    await expect(page.locator(".modal input, .modal textarea")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(page.locator(".modal")).toHaveCount(0);
  });

  test("F09 материал: создать → назначить → стажёр читает → прогресс", async ({ browser }) => {
    const ctx = await browser.newContext();
    const hr = await ctx.newPage();
    await demo(hr, "hr");
    const sections = [{ kind: "text", title: `${PREFIX}раздел`, body: "Проверьте инструмент перед выездом." }, { kind: "check", title: "Чек-лист", body: "Каска\nПерчатки" }];
    const form = { title: `${PREFIX}материал`, kind: "Чек-лист", audience: "intern", topic: "", tags: "Оборудование", sections: JSON.stringify(sections) };
    const c = await (await hr.request.post("/api/courses", { multipart: form, headers: await csrf(ctx) })).json();
    const pairs = (await (await hr.request.get("/api/dashboard")).json()).pairs;
    const pid = pairs.find((p: any) => p.code === "П-04").id;
    const a = await api(hr, "POST", `/api/courses/${c.id}/assign`, { pair_ids: [pid], side: "intern" });
    expect((await a.json()).assigned).toBe(1);
    // тот же браузер → та же песочница
    await hr.goto("/demo/intern");
    const r = await api(hr, "POST", `/api/courses/${c.id}/progress`, { section: 0 });
    expect((await r.json()).progress).toBe(50);
    await ctx.close();
  });

  test("F10 тест по материалу: черновик → публикация → прохождение", async ({ browser }) => {
    test.setTimeout(180_000);
    const ctx = await browser.newContext();
    const hr = await ctx.newPage();
    await demo(hr, "hr");
    const learn = await (await hr.request.get("/api/learn")).json();
    const course = learn.courses.find((c: any) => c.title === "Оборудование ШПД");
    const t = await (await api(hr, "POST", "/api/tests/generate", { course_id: course.id, n: 5, difficulty: "easy", types: ["single", "truefalse"], pass_score: 0.6 })).json();
    expect(t.questions.length).toBeGreaterThanOrEqual(3);
    for (const q of t.questions) expect(q.source.length).toBeGreaterThan(5);
    expect((await api(hr, "POST", `/api/tests/${t.id}/publish`)).status()).toBe(200);
    await hr.goto("/demo/intern");
    const mine = (await (await hr.request.get("/api/learn")).json()).tests.find((x: any) => x.id === t.id);
    expect(mine).toBeTruthy();
    const answers: Record<string, number> = {};
    for (const q of mine.questions) answers[q.id] = 0;
    const res = await (await api(hr, "POST", `/api/tests/${t.id}/answer`, { answers })).json();
    expect(res.attempts).toBe(1);
    await ctx.close();
  });

  test("F11 новый поток: создание и переключение", async ({ page }) => {
    await registerHr(page.request);
    await page.goto("/dashboard");
    const r = await api(page, "POST", "/api/programs", { name: `${PREFIX}поток 2`, months: 4, copy_questionnaires: true });
    expect(r.status()).toBe(200);
    const list = await (await page.request.get("/api/programs")).json();
    expect(list[0].name).toBe(`${PREFIX}поток 2`);
    expect(list[0].current).toBe(true);
  });

  test("F12 «Хочу поговорить с HR» → уведомление у HR", async ({ browser }) => {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    await demo(p, "intern");
    await p.goto("/me");
    const r = await api(p, "POST", "/api/me/talk", { topic: "Нагрузка", text: `${PREFIX}нужно поговорить` });
    expect(r.status()).toBe(200);
    await p.goto("/demo/hr");
    const n = await (await p.request.get("/api/notifications")).json();
    expect(JSON.stringify(n)).toContain("просит разговор с HR");
    await ctx.close();
  });

  test("F13 отчёт PDF и Excel скачиваются", async ({ page }) => {
    await demo(page, "hr");
    const pdf = await page.request.get("/api/reports?fmt=pdf&period=all");
    expect(pdf.status()).toBe(200);
    expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
    const xlsx = await page.request.get("/api/reports?fmt=xlsx&period=last");
    expect(xlsx.status()).toBe(200);
  });

  test("F14 песочницы изолированы между браузерами", async ({ browser }) => {
    const a = await (await browser.newContext()).newPage();
    const b = await (await browser.newContext()).newPage();
    await demo(a, "hr");
    await demo(b, "hr");
    const name = `${PREFIX}поток изоляции ${stamp()}`;
    await api(a, "POST", "/api/programs", { name, months: 3, copy_questionnaires: false });
    const listB = await (await b.request.get("/api/programs")).json();
    expect(listB.map((x: any) => x.name)).not.toContain(name);
  });
});
