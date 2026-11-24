"""Браузерные тесты адаптивности (Playwright, Chromium) против запущенного стенда.

Запуск:
    uv run --with playwright playwright install chromium      # один раз
    E2E_BASE=http://localhost:8000 uv run --with playwright pytest e2e -q

В обычный `pytest` не входят (testpaths = tests): CI не ставит браузеры.
"""

import os
import time

import pytest
from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:8000")
PHONE, DESKTOP = (375, 812), (1440, 900)
WIDTHS = [(320, 568), (375, 812), (390, 844), (768, 1024), (1024, 768), (1440, 900), (1920, 1080)]
PAGES = [
    (None, "/"),
    (None, "/login"),
    ("hr", "/dashboard"),
    ("hr", "/pairs"),
    ("hr", "/program"),
    ("hr", "/forms"),
    ("hr", "/learn"),
    ("hr", "/settings"),
    ("intern", "/me"),
    ("intern", "/learn"),
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_page(browser, size, role=None) -> Page:
    w, h = size
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=w < 1024, is_mobile=w < 768)
    pg = ctx.new_page()
    if role:
        pg.goto(f"{BASE}/demo/{role}")
    return pg


def ready(pg: Page) -> None:
    pg.wait_for_load_state("networkidle")
    time.sleep(0.6)


@pytest.mark.parametrize("size", WIDTHS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_no_horizontal_scroll(browser, size) -> None:
    pg = open_page(browser, size)
    role = None
    for need, url in PAGES:
        if need != role:
            pg.context.clear_cookies()
            if need:
                pg.goto(f"{BASE}/demo/{need}")
            role = need
        pg.goto(BASE + url)
        ready(pg)
        extra = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
        assert extra <= 0, f"{url} на {size[0]}px шире экрана на {extra}px"
    pg.context.close()


def test_tabbar_navigates_on_phone(browser) -> None:
    pg = open_page(browser, PHONE, "hr")
    pg.goto(BASE + "/dashboard")
    ready(pg)
    assert pg.locator(".tabbar").is_visible() and not pg.locator(".topbar nav.seg").is_visible()
    pg.locator(".tabbar a", has_text="Пары").click()
    ready(pg)
    assert pg.url.endswith("/pairs")
    assert pg.locator('.tabbar a[aria-current="page"]').inner_text().strip() == "Пары"
    pg.context.close()


def test_tabbar_hidden_on_desktop(browser) -> None:
    pg = open_page(browser, DESKTOP, "hr")
    pg.goto(BASE + "/dashboard")
    ready(pg)
    assert not pg.locator(".tabbar").is_visible() and pg.locator(".topbar nav.seg").is_visible()
    pg.context.close()


@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["375", "1440"])
def test_hr_scenario(browser, size) -> None:
    """HR: дашборд → пара → анкеты → ответы участника → закрыть окно; ассистент открывается и закрывается."""
    pg = open_page(browser, size, "hr")
    pg.goto(BASE + "/dashboard")
    ready(pg)
    assert pg.locator(".hero h1").is_visible()
    pg.goto(BASE + "/pairs")
    ready(pg)
    assert pg.locator("#explain-btn").is_visible()
    pg.goto(BASE + "/forms")
    ready(pg)
    pg.locator("[data-answers]").first.click()
    modal = pg.locator(".modal")
    modal.wait_for()
    box = modal.bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= size[1] + 1, "окно ответов не помещается по высоте"
    pg.keyboard.press("Escape")
    assert pg.locator(".modal").count() == 0
    pg.click("#chat-fab")
    assert pg.locator(".ai-panel").is_visible()
    pg.keyboard.press("Escape")
    assert not pg.locator(".ai-panel").is_visible()
    pg.context.close()


@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["375", "1440"])
def test_intern_scenario(browser, size) -> None:
    """Стажёр: моя стажировка → обучение → открыть материал."""
    pg = open_page(browser, size, "intern")
    pg.goto(BASE + "/me")
    ready(pg)
    assert pg.locator(".hero h1").is_visible()
    pg.goto(BASE + "/learn")
    ready(pg)
    pg.locator("[data-read]").first.click()
    ready(pg)
    assert pg.locator(".reader").is_visible()
    pg.context.close()


def test_theme_switch_in_profile_menu_on_phone(browser) -> None:
    pg = open_page(browser, PHONE, "hr")
    pg.goto(BASE + "/dashboard")
    ready(pg)
    before = pg.evaluate("document.documentElement.dataset.theme")
    pg.click("#menu-btn")
    pg.click(".menu-theme")
    assert pg.evaluate("document.documentElement.dataset.theme") != before
    pg.context.close()


def test_tap_targets_on_phone(browser) -> None:
    pg = open_page(browser, PHONE, "hr")
    pg.goto(BASE + "/dashboard")
    ready(pg)
    for sel in (
        ".tabbar a",
        "#menu-btn",
        "#notif-btn",
        "#palette-open",
        "#chat-fab",
        ".hero .btn",
        "[data-dept]",
    ):
        for el in pg.locator(sel).all():
            if el.is_visible():
                b = el.bounding_box()
                assert b["width"] >= 44 and b["height"] >= 44, f"{sel}: {b['width']:.0f}×{b['height']:.0f}"
    pg.context.close()


def test_inputs_do_not_zoom_on_ios(browser) -> None:
    pg = open_page(browser, PHONE)
    for url in ("/login", "/register"):
        pg.goto(BASE + url)
        ready(pg)
        sizes = pg.eval_on_selector_all(
            "input:not([type=checkbox]), textarea, select",
            "els => els.map(e => parseFloat(getComputedStyle(e).fontSize))",
        )
        assert sizes and min(sizes) >= 16, f"{url}: {sizes}"
    pg.context.close()
