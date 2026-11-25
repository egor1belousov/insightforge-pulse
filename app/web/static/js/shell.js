// Верхняя панель: меню профиля, уведомления, выход.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  function pop(btnId, popId) {
    const b = $(btnId), p = $(popId);
    if (!b || !p) return;
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = p.hidden;
      document.querySelectorAll(".popover").forEach((x) => (x.hidden = true));
      document.querySelectorAll("[aria-expanded]").forEach((x) => x.setAttribute("aria-expanded", "false"));
      p.hidden = !open; b.setAttribute("aria-expanded", String(open));
      if (open && popId === "notif-pop") window.dispatchEvent(new Event("pulse:notif-open"));
      if (open && popId === "stream-pop") window.dispatchEvent(new Event("pulse:streams-open"));
    });
  }
  pop("menu-btn", "menu-pop");
  pop("notif-btn", "notif-pop");
  pop("stream-btn", "stream-pop");
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".popover")) document.querySelectorAll(".popover").forEach((x) => (x.hidden = true));
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".popover").forEach((x) => (x.hidden = true)); });
  const lo = $("logout-btn");
  if (lo) lo.addEventListener("click", async () => { await Pulse.api("POST", "/api/auth/logout"); location.href = "/login"; });
})();

// Уведомления и живые события (SSE) для HR и руководителя.
(function () {
  "use strict";
  const main = document.getElementById("main");
  if (!main) return;
  const role = main.dataset.role, staff = role === "hr" || role === "lead";
  const list = document.getElementById("notif-list"), cnt = document.getElementById("notif-count");
  async function loadNotif() {
    try {
      const n = await Pulse.api("GET", "/api/notifications");
      cnt.hidden = !n.unread; cnt.textContent = n.unread;
      list.innerHTML = n.items.length ? n.items.map((it) => '<a class="item" href="' + Pulse.esc(it.link || "#") + '"><span class="dot" style="margin-top:6px;background:' + (it.level === "warn" ? "var(--over)" : it.read ? "var(--faint)" : "var(--accent)") + '"></span><span class="col" style="gap:2px"><b class="small">' + Pulse.esc(it.title) + '</b><span class="xs muted">' + Pulse.esc(it.sub) + "</span></span></a>").join("") : '<p class="small muted" style="padding:10px">Новых уведомлений нет.</p>';
    } catch (e) { /* без уведомлений страница работает */ }
  }
  loadNotif();
  window.addEventListener("pulse:notif-open", async () => { await Pulse.api("POST", "/api/notifications/read"); cnt.hidden = true; });
  window.PulseShell = { loadNotif };
  if (!staff || !window.EventSource) return;
  const es = new EventSource("/api/events");
  es.addEventListener("pair_updated", (e) => {
    const d = JSON.parse(e.data);
    Pulse.toast(d.message);
    loadNotif();
    window.dispatchEvent(new CustomEvent("pulse:pair-updated", { detail: d }));
  });
  es.addEventListener("data_imported", (e) => { window.dispatchEvent(new CustomEvent("pulse:data-imported", { detail: JSON.parse(e.data) })); });
  es.addEventListener("talk_request", (e) => { const d = JSON.parse(e.data); Pulse.toast(d.who + " просит разговор с HR · тема: " + d.topic); loadNotif(); });
  // Через шлюз, который копит поток целиком, события не доходят: тогда опрашиваем уведомления.
  let live = false;
  es.addEventListener("open", () => { live = true; });
  setTimeout(() => {
    if (live) return;
    es.close();
    let seen = null;
    const poll = async () => {
      try {
        const n = await Pulse.api("GET", "/api/notifications");
        const top = n.items[0];
        if (seen !== null && top && top.id > seen) {
          Pulse.toast(top.title);
          loadNotif();
          window.dispatchEvent(new CustomEvent("pulse:pair-updated", { detail: {} }));
        }
        if (top) seen = Math.max(seen || 0, top.id);
        else if (seen === null) seen = 0;
      } catch (e) { /* следующий опрос повторит */ }
    };
    poll();
    setInterval(() => { if (!document.hidden) poll(); }, 20000);
  }, 8000);
})();

// Отчёт для руководства и палитра команд (Ctrl+K).
(function () {
  "use strict";
  const main = document.getElementById("main");
  if (!main) return;
  const role = main.dataset.role, staff = role === "hr" || role === "lead", esc = Pulse.esc;

  function modal(html) {
    const back = document.createElement("div");
    back.className = "modal-back"; back.innerHTML = html;
    document.body.appendChild(back);
    const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    back.addEventListener("click", (e) => { if (e.target === back) close(); });
    back.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
    return { back, close };
  }

  Pulse.modal = modal;

  window.PulseReport = {
    open(dept) {
      const st = { fmt: "pdf", period: "all", parts: { sum: true, pairs: true, signals: true, actions: true } };
      const names = { sum: "Сводка и ключевые показатели", pairs: "Карточки пар", signals: "Сигналы и прогноз", actions: "Действия и эффект" };
      const m = modal('<div class="modal" role="dialog" aria-modal="true" aria-labelledby="rep-t"><div class="row between"><h2 class="head" id="rep-t" style="font-size:20px">Отчёт для руководства</h2><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div><div id="rep-body"></div></div>');
      const draw = () => {
        const n = Object.values(st.parts).filter(Boolean).length;
        m.back.querySelector("#rep-body").innerHTML = '<div class="col"><span class="label">Формат</span><div class="seg">' + [["pdf", "PDF"], ["xlsx", "Excel"]].map(([k, t]) => '<button type="button" data-fmt="' + k + '" aria-pressed="' + (st.fmt === k) + '">' + t + "</button>").join("") + '</div><span class="label">Период</span><div class="seg">' + [["all", "Вся программа"], ["last", "Последний месяц"]].map(([k, t]) => '<button type="button" data-per="' + k + '" aria-pressed="' + (st.period === k) + '">' + t + "</button>").join("") + '</div><span class="label">Разделы</span>' + Object.keys(names).map((k) => '<label class="row nowrap small" style="gap:10px;min-height:40px;cursor:pointer"><input type="checkbox" data-part="' + k + '"' + (st.parts[k] ? " checked" : "") + ' style="width:20px;height:20px;accent-color:var(--accent)">' + names[k] + "</label>").join("") + '<p class="xs muted">' + n + " разд. · " + (dept && dept !== "all" ? esc(dept) : "все подразделения") + '</p><a class="btn primary" id="rep-go" href="#">Сформировать</a></div>';
        const q = new URLSearchParams({ fmt: st.fmt, period: st.period, parts: Object.keys(st.parts).filter((k) => st.parts[k]).join(","), dept: dept || "all" });
        const go = m.back.querySelector("#rep-go");
        go.href = "/api/reports?" + q; go.setAttribute("download", "");
        go.addEventListener("click", (e) => { if (!n) { e.preventDefault(); Pulse.toast("Выберите хотя бы один раздел"); return; } Pulse.toast("Отчёт формируется и скачается автоматически"); setTimeout(m.close, 300); });
        m.back.querySelectorAll("[data-fmt]").forEach((b) => b.addEventListener("click", () => { st.fmt = b.dataset.fmt; draw(); }));
        m.back.querySelectorAll("[data-per]").forEach((b) => b.addEventListener("click", () => { st.period = b.dataset.per; draw(); }));
        m.back.querySelectorAll("[data-part]").forEach((b) => b.addEventListener("change", () => { st.parts[b.dataset.part] = b.checked; draw(); }));
      };
      draw();
    },
  };

  const CMDS = {
    hr: [["Раздел", "Дашборд", "/dashboard"], ["Раздел", "Пары", "/pairs"], ["Действие", "Загрузить данные из Excel и Word", "/import"], ["Действие", "Пригласить стажёра или наставника", "/program?tab=people"], ["Действие", "Подобрать наставника / сменить наставника", "/program"], ["Действие", "Завершить поток и отметить итоги", "/program?tab=flow"], ["Действие", "Напомнить не заполнившим анкету", "/forms"], ["Действие", "Создать вопрос анкеты", "/forms?tab=build"], ["Действие", "Подключить Яндекс Форму", "/forms?tab=src"], ["Действие", "Отчёт для руководства", "#report"], ["Раздел", "Обучение и справочник", "/learn"], ["Раздел", "Настройки: интеграции, правила оповещений, доступ", "/settings"]],
    lead: [["Раздел", "Дашборд", "/dashboard"], ["Раздел", "Пары", "/pairs"], ["Действие", "Отчёт для руководства", "#report"], ["Раздел", "Справочник по методике", "/learn"]],
    mentor: [["Раздел", "Заполнить анкету", "/me"], ["Действие", "Хочу поговорить с HR", "/me#talk"], ["Раздел", "Памятки и тесты", "/learn"]],
    intern: [["Раздел", "Заполнить анкету", "/me"], ["Действие", "Хочу поговорить с HR", "/me#talk"], ["Раздел", "Мои курсы и тесты", "/learn"]],
  };
  let pairsCache = null;
  async function openPalette() {
    const items = CMDS[role].map(([g, l, u]) => ({ group: g, label: l, url: u }));
    if (staff) { if (!pairsCache) { try { pairsCache = await Pulse.api("GET", "/api/search"); } catch (e) { pairsCache = []; } } items.unshift(...pairsCache); }
    if (window.PulseChat) items.push({ group: "ИИ", label: "Спросить ИИ-ассистента", url: "#chat" });
    const m = modal('<div class="modal" role="dialog" aria-modal="true" aria-label="Поиск и команды" style="align-self:flex-start;margin-top:10vh;padding:14px;gap:8px"><label class="sr-only" for="pal-q">Поиск</label><input class="input" id="pal-q" placeholder="Пара, человек или действие…" autocomplete="off"><div id="pal-list" class="col" style="gap:2px;max-height:55vh;overflow:auto"></div></div>');
    const q = m.back.querySelector("#pal-q"), list = m.back.querySelector("#pal-list");
    let sel = 0, shown = [];
    const go = (it) => { m.close(); if (it.url === "#report") window.PulseReport.open(); else if (it.url === "#chat") window.PulseChat.open(); else location.href = it.url; };
    const draw = () => {
      const s = q.value.trim().toLowerCase();
      shown = items.filter((it) => !s || (it.label + it.group).toLowerCase().includes(s));
      sel = Math.min(sel, Math.max(0, shown.length - 1));
      list.innerHTML = shown.length ? shown.map((it, i) => '<button type="button" class="popover-item" data-i="' + i + '" style="text-align:left;border:0;border-radius:10px;padding:10px;min-height:44px;cursor:pointer;display:flex;gap:10px;background:' + (i === sel ? "var(--soft)" : "transparent") + '"><span class="xs muted" style="min-width:70px">' + esc(it.group) + '</span><span class="small">' + esc(it.label) + "</span></button>").join("") : '<p class="small muted" style="padding:10px">Ничего не найдено.</p>';
      list.querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => go(shown[+b.dataset.i])));
    };
    q.addEventListener("input", () => { sel = 0; draw(); });
    q.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { sel = Math.min(shown.length - 1, sel + 1); draw(); e.preventDefault(); }
      if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
      if (e.key === "Enter" && shown[sel]) go(shown[sel]);
    });
    draw(); q.focus();
  }
  const pb = document.getElementById("palette-open");
  if (pb) pb.addEventListener("click", openPalette);
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!document.querySelector(".modal-back")) openPalette(); } });
})();

// Потоки стажировки: переключение и создание нового потока.
(function () {
  "use strict";
  const box = document.getElementById("stream-pop"), main = document.getElementById("main");
  if (!box || !main) return;
  const { api, esc, toast } = Pulse, isHr = main.dataset.role === "hr";
  const ST = { "идёт": "ok", "набор": "info", "скоро": "info", "завершается": "warn", "завершён": "" };
  window.addEventListener("pulse:streams-open", async () => {
    box.innerHTML = '<p class="small muted" style="padding:10px">Загружаем потоки…</p>';
    const list = await api("GET", "/api/programs");
    box.innerHTML = '<p class="eyebrow grey" style="margin:6px 10px 8px">Потоки компании</p>' + list.map((p) => '<button type="button" class="item stream-item" data-stream="' + p.id + '" aria-current="' + p.current + '"><span class="grow col" style="gap:3px"><span class="row nowrap" style="gap:8px"><b class="small">' + esc(p.name) + "</b>" + (p.current ? '<span class="chip info">открыт</span>' : "") + '</span><span class="xs muted">' + (p.start ? new Date(p.start).toLocaleDateString("ru-RU", { month: "long", year: "numeric" }) + " · " : "") + p.months + " мес. · пар " + p.pairs + " · людей " + p.people + (p.period ? " · " + p.period + "-й месяц" : "") + '</span></span><span class="chip ' + (ST[p.status] || "") + '">' + esc(p.status) + "</span></button>").join("") + (isHr ? '<button type="button" class="btn small" id="stream-new" style="margin:8px 10px 6px;align-self:flex-start">+ Новый поток</button>' : "");
    box.querySelectorAll("[data-stream]").forEach((b) => b.addEventListener("click", async () => {
      if (b.getAttribute("aria-current") === "true") { box.hidden = true; return; }
      await api("POST", "/api/programs/" + b.dataset.stream + "/switch"); location.reload();
    }));
    const nb = document.getElementById("stream-new");
    if (nb) nb.addEventListener("click", (e) => { e.stopPropagation(); box.hidden = true; createModal(); });
  });
  function createModal() {
    const now = new Date(), ym = now.getFullYear() + "-" + String(now.getMonth() + 2 > 12 ? 1 : now.getMonth() + 2).padStart(2, "0");
    const m = Pulse.modal('<div class="modal" role="dialog" aria-modal="true" aria-labelledby="sn-t"><div class="row between"><h2 class="head" id="sn-t" style="font-size:20px">Новый поток стажировки</h2><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div><p class="small muted">Поток принадлежит компании: его увидят все HR и руководители. Участников и пары добавите в разделе «Программа».</p><div class="field"><label for="sn-name">Название</label><input class="input" id="sn-name" placeholder="Например: Стажировка весна 2027"></div><div class="row" style="gap:12px"><div class="field" style="flex:1 1 180px"><label for="sn-start">Старт</label><input class="input" id="sn-start" type="month" value="' + ym + '"></div><div class="field" style="flex:1 1 140px"><label for="sn-months">Длительность, мес.</label><input class="input" id="sn-months" type="number" min="1" max="24" value="6"></div></div><label class="row nowrap small" style="gap:10px;cursor:pointer"><input type="checkbox" id="sn-copy" checked style="width:20px;height:20px;accent-color:var(--accent)"> Скопировать анкеты текущего потока (темы и зеркальные вопросы)</label><div id="sn-err" class="form-error" hidden></div><button type="button" class="btn primary" id="sn-go" style="align-self:flex-start">Создать и открыть</button></div>');
    const q = (s) => m.back.querySelector(s);
    q("#sn-name").focus();
    q("#sn-go").addEventListener("click", async () => {
      const st = q("#sn-start").value;
      try {
        await api("POST", "/api/programs", { name: q("#sn-name").value, start: st ? st + "-01" : null, months: Number(q("#sn-months").value) || 6, copy_questionnaires: q("#sn-copy").checked });
        location.href = "/program";
      } catch (e) { q("#sn-err").textContent = e.message; q("#sn-err").hidden = false; }
    });
  }
})();
