"""Разведка: обход сайта анонимно и за каждую роль, ссылки, страницы, сетевые запросы к API.

python qa-report/recon/crawl.py  → qa-report/recon/{pages,api,links}.json
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

BASE = "https://mgtspulse.ru"
OUT = Path(__file__).parent
ROLES = [None, "hr", "lead", "mentor", "intern"]
START = {
    None: ["/", "/login", "/register"],
    "hr": ["/dashboard"],
    "lead": ["/dashboard"],
    "mentor": ["/me"],
    "intern": ["/me"],
}

norm = lambda p: re.sub(r"/[0-9]+(?=/|$)", "/{id}", re.sub(r"/(survey|invite)/[^/?]+", r"/\1/{token}", p))  # noqa: E731


def main() -> None:
    pages, api, links = {}, {}, {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for role in ROLES:
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            pg = ctx.new_page()
            errors = []
            pg.on(
                "console",
                lambda m: (
                    errors.append(f"{m.type}: {m.text}"[:200]) if m.type in ("error", "warning") else None
                ),
            )
            pg.on("pageerror", lambda e, errors=errors: errors.append(f"pageerror: {e}"[:200]))

            def on_resp(r, role=role):
                u = urlparse(r.url)
                if u.netloc != urlparse(BASE).netloc or not u.path.startswith("/api"):
                    return
                req = r.request
                key = f"{req.method} {norm(u.path)}"
                body = req.post_data or ""
                api.setdefault(key, {"roles": set(), "status": set(), "payload": "", "query": set()})
                api[key]["roles"].add(role or "anon")
                api[key]["status"].add(r.status)
                if u.query:
                    api[key]["query"].add(re.sub(r"=\d+", "={n}", u.query)[:80])
                if body and not api[key]["payload"]:
                    api[key]["payload"] = body[:160]

            pg.on("response", on_resp)
            if role:
                pg.goto(f"{BASE}/demo/{role}")
            queue, seen = list(START[role]), set()
            while queue and len(seen) < 40:
                path = queue.pop(0)
                if path in seen:
                    continue
                seen.add(path)
                errors.clear()
                resp = pg.goto(BASE + path)
                pg.wait_for_load_state("networkidle")
                time.sleep(0.8)
                found = pg.eval_on_selector_all("a[href]", "as => as.map(a => a.getAttribute('href'))")
                forms = pg.eval_on_selector_all(
                    "form, input, textarea, select",
                    "els => els.map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.type ? '[' + e.type + ']' : ''))",
                )
                buttons = pg.eval_on_selector_all(
                    "button",
                    "bs => bs.map(b => (b.textContent || b.getAttribute('aria-label') || '').trim().slice(0, 40)).filter(Boolean)",
                )
                pages[f"{role or 'anon'} {path}"] = {
                    "status": resp.status if resp else None,
                    "title": pg.title(),
                    "final": urlparse(pg.url).path
                    + ("?" + urlparse(pg.url).query if urlparse(pg.url).query else ""),
                    "forms": sorted(set(forms))[:30],
                    "buttons": sorted(set(buttons))[:40],
                    "console": list(errors)[:10],
                }
                for h in found:
                    full = urljoin(BASE + path, h)
                    u = urlparse(full)
                    links.setdefault(full.split("#")[0], set()).add(f"{role or 'anon'} {path}")
                    if (
                        u.netloc == urlparse(BASE).netloc
                        and not h.startswith(("#", "mailto:", "tel:"))
                        and "/demo/" not in u.path
                        and u.path not in ("/logout",)
                    ):
                        nxt = u.path + ("?" + u.query if u.query else "")
                        if nxt not in seen and nxt not in queue:
                            queue.append(nxt)
            ctx.close()
        b.close()
    for v in api.values():
        for k in ("roles", "status", "query"):
            v[k] = sorted(v[k], key=str)
    (OUT / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1))
    (OUT / "api.json").write_text(json.dumps(dict(sorted(api.items())), ensure_ascii=False, indent=1))
    (OUT / "links.json").write_text(
        json.dumps({k: sorted(v) for k, v in links.items()}, ensure_ascii=False, indent=1)
    )
    print("страниц:", len(pages), "эндпоинтов:", len(api), "ссылок:", len(links))


if __name__ == "__main__":
    main()
