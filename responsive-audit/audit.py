"""Аудит адаптивности: скриншоты всех экранов на всех ширинах и метрики проблем.

Запуск (стенд на http://localhost:8000, Playwright установлен):
    python responsive-audit/audit.py before        # скриншоты в responsive-audit/before/
    python responsive-audit/audit.py after
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
OUT = Path(__file__).parent / (sys.argv[1] if len(sys.argv) > 1 else "before")
# необязательно: какие ширины снимать, например 320,360 — для параллельного запуска
ONLY = {int(x) for x in sys.argv[2].split(",")} if len(sys.argv) > 2 else None
SIZES = [
    (320, 568),
    (360, 740),
    (375, 667),
    (390, 844),
    (414, 896),
    (430, 932),
    (768, 1024),
    (820, 1180),
    (1024, 768),
    (1180, 820),
    (1280, 800),
    (1440, 900),
    (1920, 1080),
    (2560, 1440),
    (844, 390),
]
PAGES = [
    ("landing", None, "/"),
    ("login", None, "/login"),
    ("register", None, "/register"),
    ("survey", None, "SURVEY"),
    ("dashboard", "hr", "/dashboard"),
    ("pairs", "hr", "/pairs"),
    ("program", "hr", "/program"),
    ("program-people", "hr", "/program?tab=people"),
    ("forms", "hr", "/forms"),
    ("forms-build", "hr", "/forms?tab=build"),
    ("forms-src", "hr", "/forms?tab=src"),
    ("import", "hr", "/import"),
    ("learn", "hr", "/learn"),
    ("learn-tests", "hr", "/learn?tab=tests"),
    ("learn-guide", "hr", "/learn?tab=guide"),
    ("settings", "hr", "/settings"),
    ("lead-dashboard", "lead", "/dashboard"),
    ("me-intern", "intern", "/me"),
    ("learn-intern", "intern", "/learn"),
    ("me-mentor", "mentor", "/me"),
]

METRICS = r"""() => {
  const vw = document.documentElement.clientWidth, vh = innerHeight, out = {};
  out.hscroll = document.documentElement.scrollWidth > innerWidth + 1 ? document.documentElement.scrollWidth : 0;
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none"; };
  const inScroll = (el) => !!el.closest(".scroll-x, .seg, .tabs, .prog-track, svg, .orb, .st-orb, .sphere, .modal-back, [hidden]");
  out.offscreen = []; out.clipped = []; out.small_text = 0; out.small_inputs = []; out.small_taps = [];
  document.querySelectorAll("body *").forEach((el) => {
    if (!vis(el) || inScroll(el)) return;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 && r.width < vw * 3 && getComputedStyle(el).position !== "fixed") out.offscreen.push(el.tagName.toLowerCase() + "." + String(el.className).slice(0, 40) + " →" + Math.round(r.right));
    const own = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim().length > 2);
    if (own) {
      const cs = getComputedStyle(el), fs = parseFloat(cs.fontSize);
      if (fs < 12) out.small_text++;
      if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0 && cs.overflowX === "visible" && cs.textOverflow !== "ellipsis") out.clipped.push(el.textContent.trim().slice(0, 50));
    }
  });
  document.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]), textarea, select").forEach((el) => {
    if (vis(el) && parseFloat(getComputedStyle(el).fontSize) < 16) out.small_inputs.push((el.id || el.name || el.tagName) + ":" + getComputedStyle(el).fontSize);
  });
  document.querySelectorAll("a[href], button, [role=button], [role=tab], [role=switch], [role=checkbox], input[type=checkbox], input[type=radio], label[for]").forEach((el) => {
    if (!vis(el) || el.closest(".sr-only")) return;
    const r = el.getBoundingClientRect();
    if (r.width < 44 - 0.5 || r.height < 44 - 0.5) out.small_taps.push((el.textContent.trim() || el.getAttribute("aria-label") || el.tagName).slice(0, 24) + " " + Math.round(r.width) + "×" + Math.round(r.height));
  });
  out.offscreen = out.offscreen.slice(0, 8); out.clipped = out.clipped.slice(0, 8);
  out.small_taps_n = out.small_taps.length; out.small_taps = out.small_taps.slice(0, 12);
  return out;
}"""

MODAL = r"""() => { const m = document.querySelector(".modal, .popover:not([hidden])"); if (!m) return null; const r = m.getBoundingClientRect(); return {top: Math.round(r.top), bottom: Math.round(r.bottom), vh: innerHeight, right: Math.round(r.right), vw: innerWidth, scrollable: m.scrollHeight > m.clientHeight}; }"""


def settle(pg) -> None:
    pg.wait_for_load_state("networkidle")
    h = pg.evaluate("document.body.scrollHeight")
    for y in range(0, h, 700):
        pg.evaluate(f"window.scrollTo(0,{y})")
        time.sleep(0.05)
    pg.evaluate("window.scrollTo(0,0)")
    time.sleep(0.9)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        survey = None
        for w, h in SIZES:
            if ONLY and w not in ONLY:
                continue
            ctx = b.new_context(
                viewport={"width": w, "height": h},
                has_touch=w < 1024,
                is_mobile=w < 768 or (w == 844 and h == 390),
            )
            pg = ctx.new_page()
            role = None
            for name, need, url in PAGES:
                if need != role:
                    ctx.clear_cookies()
                    if need:
                        pg.goto(f"{BASE}/demo/{need}")
                    role = need
                if url == "SURVEY":
                    if survey is None:
                        pg.goto(f"{BASE}/demo/hr")
                        survey = pg.evaluate("fetch('/api/survey-links').then(r=>r.json())")[0]["link"]
                        ctx.clear_cookies()
                    url = survey
                pg.goto(BASE + url)
                settle(pg)
                m = pg.evaluate(METRICS)
                m.update(page=name, w=w, h=h)
                shot = OUT / f"{name}-{w}x{h}.png"
                if not shot.exists():
                    pg.screenshot(path=str(shot), full_page=True)
                results.append(m)
            # модалки и всплывающие окна на этом размере
            pg.goto(f"{BASE}/demo/hr")
            pg.goto(BASE + "/dashboard")
            settle(pg)
            popups = (
                ("report", "#rep-btn"),
                ("palette", "Control+k"),
                ("notif", "#notif-btn"),
                ("stream", "#stream-btn"),
                ("profile", "#menu-btn"),
            )
            for label, target in popups:
                try:
                    if target.startswith("#"):
                        pg.click(target)
                    else:
                        pg.keyboard.press(target)
                    time.sleep(0.5)
                    info = pg.evaluate(MODAL)
                    pg.screenshot(path=str(OUT / f"modal-{label}-{w}x{h}.png"))
                    results.append({"page": "modal-" + label, "w": w, "h": h, "modal": info})
                    pg.keyboard.press("Escape")
                    pg.mouse.click(2, h - 2)
                    time.sleep(0.2)
                except Exception as e:  # noqa: BLE001
                    results.append({"page": "modal-" + label, "w": w, "h": h, "error": str(e)[:120]})
            ctx.close()
        b.close()
    suffix = "-" + sys.argv[2].replace(",", "_") if ONLY else ""
    (OUT / f"metrics{suffix}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("снимков:", len(list(OUT.glob("*.png"))), "записей:", len(results))


if __name__ == "__main__":
    main()
