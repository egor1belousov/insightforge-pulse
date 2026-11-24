// Общие функции интерфейса: запросы к API, всплывающие сообщения, экранирование.
(function () {
  "use strict";

  function cookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function api(method, url, body, opts) {
    const headers = { "x-csrf-token": cookie("pulse_csrf") };
    let payload = body;
    if (body && !(body instanceof FormData)) {
      headers["content-type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin", ...(opts || {}) });
    if (res.status === 401 && !url.startsWith("/api/auth/")) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname);
      throw new Error("Нужно войти в систему.");
    }
    const type = res.headers.get("content-type") || "";
    const data = type.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : "Проверьте введённые данные.") : "Что-то пошло не так. Повторите попытку.";
      throw new Error(detail);
    }
    return data;
  }

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let toastTimer = null;
  function toast(text, undo) {
    let el = document.getElementById("toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.innerHTML = '<span class="dot" style="background:#22C55E"></span><span class="grow">' + esc(text) + "</span>" +
      (undo ? '<button type="button" class="undo">Отменить</button>' : "") +
      '<button type="button" class="x" aria-label="Закрыть уведомление">×</button>';
    el.hidden = false;
    el.querySelector(".x").onclick = () => { el.hidden = true; };
    if (undo) el.querySelector(".undo").onclick = () => { el.hidden = true; undo(); };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }

  function conf(c) {
    const v = Number(c || 0);
    const cls = v >= 0.85 ? "hi" : v >= 0.6 ? "mid" : "lo";
    const txt = v >= 0.85 ? v.toFixed(2) : v >= 0.6 ? v.toFixed(2) + " — проверить" : v.toFixed(2) + " — нужен ответ";
    return '<span class="conf ' + cls + '">' + txt + "</span>";
  }

  const plural = (n, a, b, c) => (n % 10 === 1 && n % 100 !== 11 ? a : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? b : c);

  // Сегментный прогресс: части по статусам, крупная цифра и легенда.
  // parts: [{ n, cls: "ok" | "warn" | "bad" | "idle", label }]
  function progress(parts, opt) {
    const o = opt || {}, total = parts.reduce((a, p) => a + p.n, 0), ok = parts[0].n, pct = total ? Math.round((ok / total) * 100) : 0;
    let h = '<div class="prog' + (o.big ? " big" : "") + '">';
    h += '<div class="prog-top"><span class="prog-num">' + (o.title ? '<span class="prog-title">' + esc(o.title) + "</span>" : ok + '<span class="prog-of"> / ' + total + "</span>") + '</span><span class="prog-pct">' + pct + "%</span></div>";
    h += '<div class="prog-track" role="progressbar" aria-valuemin="0" aria-valuemax="' + total + '" aria-valuenow="' + ok + '">';
    parts.forEach((p) => { for (let i = 0; i < p.n; i++) h += '<span class="seg-' + p.cls + '" style="animation-delay:' + Math.min(i * 40, 600) + 'ms"></span>'; });
    h += '</div><div class="prog-legend">' + parts.filter((p) => p.n).map((p) => '<span><i class="seg-' + p.cls + '"></i>' + esc(p.label) + " · " + p.n + "</span>").join("") + "</div></div>";
    return h;
  }

  window.Pulse = { api, esc, toast, conf, cookie, plural, progress };

  // ---------- тема ----------
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("pulse-theme", t); } catch (e) { /* приватный режим */ }
    syncToggles();
    document.dispatchEvent(new CustomEvent("pulse:theme", { detail: t }));
  }
  function syncToggles() {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach((b) => { b.setAttribute("aria-checked", String(dark)); });
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme-toggle]");
    if (b) setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
  syncToggles();
  Pulse.theme = () => document.documentElement.getAttribute("data-theme") || "light";

  // ---------- движение ----------
  // Блоки появляются при первом показе, графики прорисовываются линией, полосы растут.
  // При перерисовке анимируется только то, что действительно изменилось.
  const calm = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const REVEAL = ".card, .tile, .hero, .signal-btn, .landing .step, .kpi";
  const io = "IntersectionObserver" in window ? new IntersectionObserver((ents) => {
    ents.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("rv-in"); io.unobserve(en.target); } });
  }, { rootMargin: "0px 0px -6% 0px" }) : null;

  // страховка: всё, что так и не попало в экран, показываем через 5 секунд
  setTimeout(() => document.querySelectorAll(".rv:not(.rv-in)").forEach((el) => el.classList.add("rv-in")), 5000);
  function reveal(nodes) {
    if (!io) return;
    let i = 0;
    nodes.forEach((el) => {
      if (el.closest(".modal, .popover, .toast") || el.classList.contains("rv")) return;
      if (el.parentElement && el.parentElement.closest(".rv")) return; // вложенные появляются вместе с родителем
      el.classList.add("rv");
      el.style.transitionDelay = Math.min(i++ * 45, 360) + "ms";
      io.observe(el);
      el.addEventListener("transitionend", () => { el.style.transitionDelay = ""; }, { once: true });
    });
  }
  const lineSig = (el) => (el.getAttribute("points") || el.getAttribute("d") || "") + "|" + (el.getAttribute("stroke") || "");
  function drawLine(el, delay) {
    if (!el.getTotalLength) return;
    let len = 0;
    try { len = el.getTotalLength(); } catch (e) { return; }
    if (!len || !isFinite(len)) return;
    const dashed = el.getAttribute("stroke-dasharray");
    if (dashed) { el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: delay + 900, fill: "backwards" }); return; }
    el.style.strokeDasharray = len + " " + len;
    const a = el.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: 1300, delay, easing: "cubic-bezier(.3,.6,.2,1)", fill: "backwards" });
    a.onfinish = () => { el.style.strokeDasharray = ""; };
  }
  function countUp(el) {
    const raw = el.textContent.trim(), m = raw.match(/^(\d+(?:[.,]\d+)?)(.*)$/);
    if (!m) return;
    const target = parseFloat(m[1].replace(",", ".")), dec = (m[1].split(/[.,]/)[1] || "").length, tail = m[2], t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 900), v = target * (1 - Math.pow(1 - k, 3));
      el.textContent = v.toFixed(dec) + tail;
      if (k < 1) requestAnimationFrame(step); else el.textContent = raw;
    };
    requestAnimationFrame(step);
  }
  function animate(added, removed) {
    const old = new Set(), oldBars = new Set();
    let rerender = false;
    removed.forEach((n) => {
      if (n.nodeType !== 1) return;
      if (n.matches(".card, .widgets, section") || n.querySelector(".card")) rerender = true;
      n.querySelectorAll("polyline, path, line").forEach((l) => old.add(lineSig(l)));
      n.querySelectorAll(".bar > span").forEach((b) => oldBars.add(b.getAttribute("style")));
    });
    const els = [];
    added.forEach((n) => { if (n.nodeType === 1) els.push(n); });
    if (!els.length) return;
    if (!rerender) { els.forEach((n) => n.querySelectorAll && n.querySelectorAll(".hero h1").forEach((h) => h.setAttribute("data-split", ""))); splitWords(); }
    if (!rerender) reveal(els.flatMap((n) => [n].filter((x) => x.matches(REVEAL)).concat(Array.from(n.querySelectorAll(REVEAL)))));
    let d = 0;
    els.forEach((n) => n.querySelectorAll("svg polyline, svg path, svg line").forEach((l) => {
      const fill = l.getAttribute("fill");
      if (old.has(lineSig(l)) || l.closest(".theme-toggle, button, .icon-btn, .btn, a.cta, .no-anim")) return;
      if (!l.getAttribute("stroke") || (fill && fill !== "none")) {
        if (fill && fill !== "none" && l.tagName !== "line") l.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 900, delay: 500, fill: "backwards" });
        return;
      }
      drawLine(l, d); d = Math.min(d + 60, 500);
    }));
    els.forEach((n) => n.querySelectorAll(".bar > span").forEach((b) => { if (!oldBars.has(b.getAttribute("style"))) b.classList.add("grow-in"); }));
    if (!rerender) els.forEach((n) => n.querySelectorAll(".kpi .value, [data-count]").forEach(countUp));
  }
  // Таблицы-карточки: на телефоне у каждой ячейки подпись из заголовка столбца
  function labelTables(root) {
    (root.querySelectorAll ? root : document).querySelectorAll("table.cards").forEach((t) => {
      const heads = Array.from(t.querySelectorAll("thead th")).map((th) => th.textContent.trim());
      t.querySelectorAll("tbody tr").forEach((tr) => Array.from(tr.children).forEach((td, i) => { if (!td.hasAttribute("data-label") && heads[i]) td.setAttribute("data-label", heads[i]); }));
    });
  }
  // Ряды вкладок, которые не помещаются: класс overflow включает затухание у края
  function markOverflow() {
    document.querySelectorAll(".seg, .tabs").forEach((el) => el.classList.toggle("overflow", el.scrollWidth > el.clientWidth + 2));
  }
  let ovTimer = null;
  const scheduleOverflow = () => { clearTimeout(ovTimer); ovTimer = setTimeout(markOverflow, 60); };
  window.addEventListener("resize", scheduleOverflow);
  new MutationObserver((ms) => { ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) labelTables(n); })); scheduleOverflow(); }).observe(document.documentElement, { childList: true, subtree: true });

  // Заголовки с data-split появляются по словам
  function splitWords() {
    document.querySelectorAll("[data-split]:not([data-split-done])").forEach((h) => {
      h.setAttribute("data-split-done", "1");
      if (calm) return;
      const words = h.textContent.trim().split(/\s+/);
      h.setAttribute("aria-label", h.textContent.trim());
      h.innerHTML = words.map((w, i) => '<span class="split-w" aria-hidden="true" style="animation-delay:' + (120 + i * 90) + 'ms">' + esc(w) + "</span>").join(" ");
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", splitWords); else splitWords();

  if (!calm && "MutationObserver" in window) {
    const mo = new MutationObserver((muts) => {
      const added = [], removed = [];
      muts.forEach((m) => { added.push(...m.addedNodes); removed.push(...m.removedNodes); });
      animate(added, removed);
    });
    const start = () => {
      mo.observe(document.body, { childList: true, subtree: true });
      animate(Array.from(document.body.children), []);
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  }
})();
