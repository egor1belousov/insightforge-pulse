import { APIRequestContext, BrowserContext, Page, expect } from "@playwright/test";

export const ROLES = ["hr", "lead", "mentor", "intern"] as const;
export const HOME: Record<string, string> = { hr: "/dashboard", lead: "/dashboard", mentor: "/me", intern: "/me" };
export const PREFIX = "qa_test_";
export const stamp = () => Date.now().toString(36) + Math.floor(Math.random() * 1e4).toString(36);

/** Вход в демо под ролью: своя песочница на браузерный контекст. */
export async function demo(page: Page, role: string) {
  await page.goto(`/demo/${role}`);
  await page.waitForLoadState("networkidle");
}

/** CSRF-заголовок из cookie контекста. */
export async function csrf(ctx: BrowserContext): Promise<Record<string, string>> {
  const c = (await ctx.cookies()).find((x) => x.name === "pulse_csrf");
  return { "x-csrf-token": c ? c.value : "" };
}

/** Запрос к API от имени пользователя страницы. */
export async function api(page: Page, method: string, url: string, data?: unknown) {
  const headers = await csrf(page.context());
  return page.request.fetch(url, { method, data: data as any, headers });
}

/** Регистрация тестового HR (данные с префиксом qa_test_). */
export async function registerHr(request: APIRequestContext, tag = stamp()) {
  const email = `${PREFIX}hr_${tag}@example.com`;
  const r = await request.post("/api/auth/register", {
    data: { name: `${PREFIX}HR ${tag}`, email, password: "QaTest!Passw0rd", organization: `${PREFIX}org_${tag}`, program: `${PREFIX}поток` },
  });
  return { r, email, tag };
}

export async function ready(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
}

/** Собираем ошибки консоли и упавшие запросы страницы. */
export function watch(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 200)); });
  page.on("pageerror", (e) => errors.push("pageerror: " + String(e).slice(0, 200)));
  page.on("response", (r) => { if (r.status() >= 500) errors.push(`HTTP ${r.status()} ${r.url()}`); });
  page.on("requestfailed", (r) => { const f = r.failure()?.errorText || ""; if (!/ERR_ABORTED|NS_BINDING_ABORTED/.test(f)) errors.push(`failed ${r.url()} ${f}`); });
  return errors;
}

export async function noHScroll(page: Page) {
  const extra = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(extra, "горизонтальная прокрутка").toBeLessThanOrEqual(0);
}
