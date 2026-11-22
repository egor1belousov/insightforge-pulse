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

  window.Pulse = { api, esc, toast, conf, cookie, plural };
})();
