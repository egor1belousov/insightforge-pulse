// Дашборд HR и руководителя: виджеты, фильтры, режим «Настроить», живое обновление.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const role = document.getElementById("main").dataset.role, isHr = role === "hr";
  const META = { kpi: "Ключевые показатели", tasks: "Мои задачи на неделю", signals: "Сигналы", map: "Карта пар", trend: "Динамика и прогноз", system: "Проблема пары или программы", forms: "Анкеты за месяц", feed: "Комментарии", health: "Индекс здоровья" };
  const FLEX = { kpi: "1 1 100%", tasks: "1 1 380px", signals: "1 1 460px", map: "1 1 380px", trend: "2 1 560px", system: "1 1 340px", forms: "1 1 300px", feed: "1 1 460px", health: "1 1 300px" };
  const PRESETS = [["hr", "HR: всё", {}], ["lead", "Руководителю: кратко", { forms: true, feed: true, health: true, tasks: true }], ["coach", "Работа с наставниками", { kpi: true, map: true, trend: true }]];
  let D = null, L = null, edit = false, period = null, dept = "all", flash = null;
  const box = document.getElementById("dash");
  const allowed = (k) => k !== "tasks" || isHr;

  async function load() {
    const q = new URLSearchParams();
    if (period != null) q.set("period", period);
    if (dept !== "all") q.set("dept", dept);
    [D, L] = await Promise.all([api("GET", "/api/dashboard?" + q), L ? Promise.resolve(L) : api("GET", "/api/dashboard/layout")]);
    if (period == null) period = D.period;
    render();
  }

  const saveLayout = (patch) => { Object.assign(L, patch); api("PUT", "/api/dashboard/layout", patch).catch((e) => toast(e.message)); };

  function ctrl(k) {
    if (!edit) return "";
    return '<span class="row nowrap" style="gap:4px"><button type="button" class="icon-btn" style="width:32px;height:32px;min-width:32px;border-radius:8px" data-up="' + k + '" aria-label="Выше">↑</button><button type="button" class="icon-btn" style="width:32px;height:32px;min-width:32px;border-radius:8px" data-down="' + k + '" aria-label="Ниже">↓</button><button type="button" class="icon-btn" style="width:32px;height:32px;min-width:32px;border-radius:8px;border-color:#F0A3A3;color:var(--both)" data-hide="' + k + '" aria-label="Убрать с дашборда">×</button></span>';
  }
  const head = (k, title) => '<div class="row nowrap" style="gap:6px;margin-bottom:10px"><p class="eyebrow grow">' + esc(title) + "</p>" + ctrl(k) + "</div>";
  const card = (k, inner, extra) => '<section class="card col" data-w="' + k + '" style="order:' + L.order.indexOf(k) + ";flex:" + FLEX[k] + ";" + (edit ? "outline:2px dashed var(--accent);outline-offset:4px;" : "") + "gap:0;" + (extra || "") + '">' + inner + "</section>";
  const pairLink = (id) => "/pairs?id=" + id;

  function W_kpi() {
    let h = (edit ? head("kpi", META.kpi) : "") + '<div class="grid-auto">';
    D.kpis.forEach((k) => {
      h += '<div class="card kpi"><div class="row between nowrap"><p class="small muted">' + esc(k.label) + '</p><span class="help" title="' + esc(k.help) + '" aria-label="Пояснение: ' + esc(k.help) + '" tabindex="0">?</span></div><p class="value" style="color:' + k.color + '">' + esc(k.value) + '</p><p class="xs muted" style="margin-top:6px">' + esc(k.note) + "</p></div>";
    });
    return '<section data-w="kpi" style="order:' + L.order.indexOf("kpi") + ";flex:" + FLEX.kpi + ";min-width:0;" + (edit ? "outline:2px dashed #9DBDF2;outline-offset:4px;border-radius:18px" : "") + '">' + h + "</div></section>";
  }
  function W_tasks() {
    const done = D.tasks.filter((t) => t.done).length;
    let h = head("tasks", "Мои задачи на неделю · " + done + " из " + D.tasks.length);
    if (!D.tasks.length) h += '<p class="small muted">Задач нет — все пары под контролем.</p>';
    D.tasks.forEach((t) => {
      h += '<div class="row nowrap" style="border-bottom:1px solid var(--soft);padding:6px 0;gap:10px"><button type="button" role="checkbox" aria-checked="' + t.done + '" aria-label="Отметить: ' + esc(t.title) + '" data-task="' + esc(t.k) + '" style="flex-shrink:0;width:36px;height:36px;border:0;background:none;cursor:pointer;display:inline-flex;align-items:center;justify-content:center"><span aria-hidden="true" style="width:20px;height:20px;border-radius:6px;border:2px solid ' + (t.done ? "var(--accent)" : "var(--line-3)") + ";background:" + (t.done ? "var(--accent)" : "var(--card)") + ";color:" + (t.done ? "#fff" : "transparent") + ';transition:background .2s,border-color .2s;font-size:12px;display:inline-flex;align-items:center;justify-content:center">✓</span></button><span class="grow col" style="gap:2px"><span class="small" style="font-weight:600;' + (t.done ? "text-decoration:line-through;color:var(--faint)" : "") + '">' + esc(t.title) + '</span><span class="xs muted">' + esc(t.sub) + '</span></span><a class="btn ghost small" href="' + esc(t.link) + '">Открыть →</a></div>';
    });
    if (D.tasks.length) {
      const urgent = D.tasks.filter((t) => !t.done && /срочно/.test(t.sub)).length;
      h += '<div class="w-foot">' + Pulse.progress([{ n: done, cls: "ok", label: "сделано" }, { n: urgent, cls: "bad", label: "срочно" }, { n: D.tasks.length - done - urgent, cls: "idle", label: "в работе" }], { title: done === D.tasks.length ? "Все задачи недели закрыты" : "Неделя: " + done + " из " + D.tasks.length }) + '<a class="btn ghost small" style="align-self:flex-start;padding-left:0" href="/pairs">Все пары и действия →</a></div>';
    }
    return card("tasks", h);
  }
  function W_signals() {
    let h = head("signals", "Сигналы · что требует внимания");
    if (!D.alerts.length) h += '<div class="issue done"><span><b>Сигналов нет.</b> В этот период и в этом подразделении пары двигались согласованно. Сдвиньте ползунок вперёд, чтобы увидеть, когда появились первые сигналы.</span></div>';
    h += '<div class="col" style="gap:10px">';
    D.alerts.forEach((a) => {
      h += '<a class="signal-btn" style="text-decoration:none;color:inherit" href="' + (a.pair_id ? pairLink(a.pair_id) : "/pairs") + '"><span class="pair-badge" style="background:' + a.dot + '">' + esc(a.pair) + '</span><span class="grow col" style="gap:3px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">' + esc(a.type) + '</span><span class="small" style="font-weight:600">' + esc(a.title) + '</span><span class="small muted" style="line-height:1.45">' + esc(a.why) + '</span></span><span aria-hidden="true" style="color:var(--accent);font-size:18px">→</span></a>';
    });
    return card("signals", h + "</div>");
  }
  function W_map() {
    let h = head("map", "Карта пар");
    h += '<div class="row nowrap" style="gap:8px;align-items:stretch;flex:1"><p class="xs muted" style="writing-mode:vertical-rl;transform:rotate(180deg);text-align:center">оценка стажёра →</p><div class="grow col" style="gap:6px"><div style="position:relative;flex:1;min-height:260px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr));gap:4px">';
    h += '<div style="background:var(--over-bg);border-radius:12px;padding:8px 10px;font-size:11px;font-weight:600;color:var(--over-fg)">Переоценивает себя</div><div style="background:var(--ok-bg);border-radius:12px;padding:8px 10px;font-size:11px;font-weight:600;color:var(--ok-fg);text-align:right">Согласны, растут</div><div style="background:var(--both-bg);border-radius:12px;padding:8px 10px;font-size:11px;font-weight:600;color:var(--both-fg);display:flex;align-items:flex-end">Оба тревожатся</div><div style="background:var(--accent-soft);border-radius:12px;padding:8px 10px;font-size:11px;font-weight:600;color:var(--under-fg);display:flex;align-items:flex-end;justify-content:flex-end">Недооценивает себя</div>';
    const placed = [];
    D.pairs.filter((p) => p.i != null && p.m != null).forEach((p) => {
      let x = 8 + p.m * 84, y = 92 - p.i * 84;
      placed.forEach((q) => { if (Math.abs(q[0] - x) < 9 && Math.abs(q[1] - y) < 9) y += 10; });
      placed.push([x, y]);
      h += '<a href="' + pairLink(p.id) + '" aria-label="Открыть пару ' + esc(p.code) + '" title="' + esc(p.code + " · " + p.st.label) + '" style="position:absolute;left:' + x.toFixed(1) + "%;top:" + y.toFixed(1) + "%;transform:translate(-50%,-50%);min-width:48px;height:32px;border-radius:999px;border:2px solid var(--card);background:" + p.st.dot + ';color:#fff;font-size:11px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(5,7,14,.25);padding:0 8px;text-decoration:none' + (flash === p.id ? ";outline:3px solid #22C55E" : "") + '">' + esc(p.code) + "</a>";
    });
    h += '</div><p class="xs muted" style="text-align:center">оценка наставника →</p></div></div>';
    return card("map", h);
  }
  function W_trend() {
    const X = (i) => 40 + i * 98, Y = (v) => 14 + (1 - Math.min(Math.max(0, v) / 0.6, 1)) * 216;
    const ms = D.months, idx = ms.findIndex((x) => x.p === D.period);
    let h = head("trend", "Динамика расхождения и прогноз");
    h += '<div class="chart-wrap"><svg viewBox="0 0 640 252" role="img" aria-label="Линии расхождения по парам по месяцам и прогноз" style="width:100%;height:auto;display:block;margin-top:4px">';
    const fx = Math.min(X(ms.length), 628);
    if (D.period === D.last) h += '<rect x="' + X(ms.length - 1) + '" y="14" width="' + (fx - X(ms.length - 1)) + '" height="216" fill="#F3F5F9" rx="6"></rect>';
    [1, 0.75, 0.5, 0.25, 0].forEach((v) => { const y = 14 + (1 - v) * 216; h += '<line x1="40" x2="628" y1="' + y + '" y2="' + y + '" stroke="#E6E9EF"></line><text x="32" y="' + (y + 3) + '" font-size="10" fill="#5B6478" text-anchor="end">' + (v * 0.6).toFixed(2) + "</text>"; });
    const ry = Y(D.red_zone);
    h += '<line x1="40" x2="628" y1="' + ry + '" y2="' + ry + '" stroke="#C93434" stroke-dasharray="3 4"></line><text x="44" y="' + (ry - 4) + '" font-size="10" fill="#C93434">красная зона</text>';
    D.pairs.forEach((p) => {
      const pts = p.abs.map(([per, v]) => X(ms.findIndex((x) => x.p === per)) + "," + Y(v).toFixed(1));
      h += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + p.st.dot + '" stroke-width="' + (flash === p.id ? 4 : 2.4) + '" stroke-linejoin="round"></polyline>';
      if (p.forecast != null && p.abs.length) { const last = p.abs[p.abs.length - 1]; h += '<polyline points="' + X(ms.findIndex((x) => x.p === last[0])) + "," + Y(last[1]).toFixed(1) + " " + fx + "," + Y(p.forecast).toFixed(1) + '" fill="none" stroke="' + p.st.dot + '" stroke-width="2" stroke-dasharray="4 4"></polyline>'; }
    });
    ms.forEach((m, i) => { h += '<text x="' + X(i) + '" y="246" font-size="11" fill="' + (i <= idx ? "#5B6478" : "#B0B7C6") + '" text-anchor="middle">' + esc(m.short) + "</text>"; });
    if (D.period === D.last) h += '<text x="' + fx + '" y="246" font-size="11" fill="#0A7CD6" text-anchor="end">' + esc(D.next_short) + " · прогноз</text>";
    h += "</svg></div>";
    if (idx === 0) h += '<p class="small" style="background:var(--bg);border-radius:12px;padding:12px;margin-top:8px">Пока только одна анкета — тренд появится после второй.</p>';
    h += '<div class="row" style="gap:14px;margin-top:8px">' + D.pairs.map((p) => '<span class="row nowrap xs" style="gap:6px;color:var(--muted-2)"><span style="width:14px;height:3px;border-radius:2px;background:' + p.st.dot + '"></span>' + esc(p.code + " · " + p.st.label) + "</span>").join("") + "</div>";
    return card("trend", h);
  }
  function W_system() {
    const P = D.program;
    let h = head("system", "Проблема пары или программы");
    h += '<div style="display:grid;grid-template-columns:112px repeat(' + P.months.length + ',minmax(0,1fr));gap:3px;font-size:11px"><span></span>' + P.months.map((m) => '<span style="text-align:center;color:var(--muted)">' + esc(m) + "</span>").join("");
    P.rows.forEach((r) => {
      h += '<span class="small" style="align-self:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(r.name) + '">' + esc(r.name) + "</span>";
      r.cells.forEach((c) => { const bg = c.v == null ? "#F3F5F9" : "rgba(10,124,214," + Math.max(0.06, Math.min(0.9, 0.08 + (c.v - 0.35) * 2)).toFixed(2) + ")"; h += '<span title="' + (c.v == null ? "" : c.v.toFixed(2)) + '" style="height:26px;border-radius:6px;background:' + bg + ";border:2px solid " + (c.ring ? "#C93434" : "transparent") + '"></span>'; });
    });
    h += "</div>";
    h += P.box ? '<div style="background:var(--both-bg);border-radius:12px;padding:12px 14px;margin-top:12px"><p class="small" style="font-weight:700;color:var(--both-fg)">' + esc(P.box.title) + '</p><p class="xs" style="margin-top:6px;color:var(--both-fg);opacity:.85;line-height:1.5">' + esc(P.box.text) + "</p></div>" : '<div class="issue done" style="margin-top:12px"><span class="small">Системных просадок нет: проблемы, если есть, — на уровне отдельных пар.</span></div>';
    return card("system", h);
  }
  function W_forms() {
    const F = D.forms;
    let h = head("forms", "Анкеты за " + F.month);
    h += Pulse.progress([{ n: F.got, cls: "ok", label: "заполнено" }, { n: F.pending.length, cls: "bad", label: "ждём" }], { big: true });
    if (F.pending.length) h += '<div class="col" style="gap:6px;margin-top:14px"><p class="xs muted" style="font-weight:700;letter-spacing:.06em">ЖДЁМ ОТВЕТ</p><div class="row" style="gap:6px">' + F.pending.map((x) => '<span class="tag">' + esc(x) + "</span>").join("") + "</div></div>";
    else h += '<p class="small muted" style="margin-top:12px">Все анкеты месяца получены — можно смотреть сигналы.</p>';
    h += '<div class="w-foot">';
    if (isHr && F.pending.length) h += '<a class="btn primary small" href="/forms">Напомнить не заполнившим</a>';
    if (isHr && window.PULSE_DEMO) h += '<button type="button" class="btn small" id="demo-resp">Отправить тестовый ответ</button>';
    if (!isHr) h += '<p class="xs muted">Рассылкой управляет HR.</p>';
    return card("forms", h + "</div>");
  }
  function W_feed() {
    let h = head("feed", "Комментарии · разбор ИИ");
    if (!D.feed.length) h += '<p class="small muted">Комментариев за этот месяц нет.</p>';
    D.feed.forEach((c) => {
      const cls = c.tone === "позитив" ? "ok" : c.tone === "негатив" ? "bad" : "";
      h += '<div class="list-row"><span class="tag">' + esc(c.who) + '</span><a class="grow small" style="color:inherit;text-decoration:none;line-height:1.5" href="' + pairLink(c.pair_id) + '">«' + esc(c.text) + '»</a>' + (c.anxiety >= 0.6 ? '<span class="chip warn">тревога</span>' : "") + '<span class="chip ' + cls + '">' + esc(c.tone) + "</span></div>";
    });
    return card("feed", h);
  }
  function W_health() {
    let h = head("health", "Индекс здоровья пар");
    D.pairs.slice().sort((a, b) => (a.health ?? 101) - (b.health ?? 101)).forEach((p) => {
      h += '<a href="' + pairLink(p.id) + '" style="display:block;text-decoration:none;color:inherit;padding:6px 0;min-height:36px"><span class="row between small"><span>' + esc(p.code + " · " + p.st.label) + "</span><b>" + (p.health ?? "—") + '</b></span><span class="bar" style="display:block;margin-top:6px"><span style="width:' + (p.health || 0) + "%;background:" + p.st.dot + '"></span></span></a>';
    });
    const hs = D.pairs.map((p) => p.health).filter((v) => v != null);
    if (hs.length) {
      const good = hs.filter((v) => v > 75).length, low = hs.filter((v) => v < 50).length;
      h += '<div class="w-foot">' + Pulse.progress([{ n: good, cls: "ok", label: "выше 75" }, { n: hs.length - good - low, cls: "warn", label: "50–75" }, { n: low, cls: "bad", label: "ниже 50 — нужна встреча" }], { title: "Здоровы " + good + " из " + hs.length }) + "</div>";
    }
    return card("health", h);
  }
  const WIDGETS = { kpi: W_kpi, tasks: W_tasks, signals: W_signals, map: W_map, trend: W_trend, system: W_system, forms: W_forms, feed: W_feed, health: W_health };

  // Новый поток без пар: шаги запуска с реальными счётчиками
  async function renderEmpty() {
    let O = { people: [], unpaired: [], free_mentors: [] }, M = { rows: [], got: 0 };
    try { [O, M] = await Promise.all([api("GET", "/api/program/overview"), isHr ? api("GET", "/api/forms/mailing") : Promise.resolve(M)]); } catch (e) { /* пустой поток */ }
    const people = O.people || [], joined = people.filter((p) => p.joined).length, interns = people.filter((p) => p.side === "intern").length;
    const steps = [
      ["01 / Люди", people.length ? "Участников: " + people.length : "Пригласите стажёров и наставников", people.length ? "Вошли в систему: " + joined + " из " + people.length + ". Стажёров " + interns + ", наставников " + (people.length - interns) + "." : "Ссылки-приглашения на почту или загрузка списка из Excel.", "/program?tab=people", "К участникам", people.length > 0],
      ["02 / Пары", (O.unpaired || []).length ? "Без пары: " + O.unpaired.length : "Соберите пары", "ИИ подскажет наставника по подразделению и нагрузке." + ((O.free_mentors || []).length ? " Свободных наставников: " + O.free_mentors.length + "." : ""), "/program", "К парам", false],
      ["03 / Анкета", M.got ? "Получено анкет: " + M.got : "Проверьте анкету", M.got ? "Ответы уже видны в «Анкеты → Рассылки». Сигналы появятся, когда люди будут в парах." : "Анкеты скопированы из прошлого потока — их можно поправить в конструкторе.", M.got ? "/forms" : "/forms?tab=build", M.got ? "К ответам" : "К конструктору", M.got > 0],
      ["04 / Каналы", "Настройте рассылку", "Почта, Telegram и автонапоминания — один раз на весь поток.", "/forms", "К рассылкам", false],
    ];
    box.innerHTML = '<section class="hero"><div class="sphere orb" data-orb="dots" data-size="560" aria-hidden="true"></div><p class="tagline">Новый поток</p><h1>' + (people.length ? "Поток набирается" : "Поток готов к запуску") + '</h1><p class="sub">' + (people.length ? "Людей: " + people.length + ", пар пока нет — сигналы появятся, когда стажёр и наставник окажутся в паре и заполнят анкету." : "Пар пока нет — сигналы появятся после первой анкеты. Четыре шага, чтобы начать.") + '</p></section><div class="grid-auto" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">' + steps.map(([k, t, d, u, b, done]) => '<a class="card col start-step' + (done ? " done" : "") + '" href="' + u + '" style="text-decoration:none;color:inherit"><p class="eyebrow">' + esc(k) + (done ? " ✓" : "") + '</p><b style="font-size:17px">' + esc(t) + '</b><p class="small muted" style="line-height:1.5">' + esc(d) + '</p><span class="btn ghost small" style="margin-top:auto;align-self:flex-start;padding-left:0">' + esc(b) + " →</span></a>").join("") + "</div>";
  }

  function render() {
    if (!D.pairs.length && dept === "all") { renderEmpty(); return; }
    const ms = D.months, idx = Math.max(0, ms.findIndex((x) => x.p === D.period));
    let h = '<section class="hero"><div class="sphere orb" data-orb="lattice" data-size="560" aria-hidden="true"></div><div class="row between" style="align-items:flex-end;gap:18px"><div style="max-width:680px"><p class="tagline">' + esc(D.tag) + "</p><h1>" + esc(D.headline) + '</h1><p class="sub">' + esc(D.sub) + '</p></div><div class="row">';
    h += '<button type="button" class="btn on-dark" id="rep-btn"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12"></path><path d="M7 10l5 5 5-5"></path><path d="M5 21h14"></path></svg>Отчёт</button>';
    h += '<button type="button" class="btn on-dark" id="edit-btn" aria-pressed="' + edit + '"' + (edit ? ' style="background:var(--card);color:#05070E"' : "") + '><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="3" width="7" height="7" rx="1.5"></rect><rect x="3" y="14" width="7" height="7" rx="1.5"></rect><rect x="14" y="14" width="7" height="7" rx="1.5"></rect></svg>' + (edit ? "Готово" : "Настроить") + "</button></div></div></section>";
    h += '<section class="card row" aria-label="Фильтры дашборда" style="gap:14px 28px;align-items:flex-end;padding:14px 18px"><div class="col" style="flex:1 1 320px;gap:6px"><label for="f-month" class="xs muted" style="font-weight:700;letter-spacing:.06em">ПЕРИОД · ДАННЫЕ НА ' + esc(ms[idx].full.toUpperCase()) + '</label><input id="f-month" type="range" min="0" max="' + (ms.length - 1) + '" step="1" value="' + idx + '" style="width:100%;accent-color:var(--accent);min-height:28px;cursor:pointer" aria-valuetext="' + esc(ms[idx].full) + '"><div class="row between nowrap" style="font-size:11px">' + ms.map((m, i) => '<span style="color:' + (i === idx ? "#0A7CD6" : "#5B6478") + ";font-weight:" + (i === idx ? 700 : 400) + '">' + esc(m.short) + "</span>").join("") + "</div></div>";
    h += '<div class="col" style="flex:2 1 440px;gap:6px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">ПОДРАЗДЕЛЕНИЕ</span><div class="row" style="gap:6px">' + [["all", "Все подразделения"]].concat(D.depts.map((d) => [d, d])).map(([k, n]) => '<button type="button" class="pill" data-dept="' + esc(k) + '" aria-pressed="' + (dept === k) + '">' + esc(n) + "</button>").join("") + "</div></div>";
    h += "</section>";
    if (edit) {
      const shelf = Object.keys(META).filter((k) => L.hidden[k] && allowed(k));
      h += '<section class="card col" style="border:1px dashed var(--accent)"><div class="row between"><p class="small"><b>Режим настройки.</b> Двигайте виджеты стрелками, скрывайте лишнее, добавляйте с полки. Раскладка сохранится только для вас.</p><div class="row" style="gap:6px">' + PRESETS.map(([k, n]) => '<button type="button" class="pill" data-preset="' + k + '" aria-pressed="' + (L.preset === k) + '">' + esc(n) + "</button>").join("") + "</div></div>";
      h += '<div class="row" style="gap:8px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">ПОЛКА ВИДЖЕТОВ:</span>' + (shelf.length ? shelf.map((k) => '<button type="button" class="pill" style="border-style:dashed;border-color:var(--accent);background:var(--accent-soft);color:var(--accent-ink)" data-show="' + k + '">+ ' + esc(META[k]) + "</button>").join("") : '<span class="small muted">все виджеты на дашборде</span>') + "</div></section>";
    }
    h += '<div class="widgets">';
    L.order.forEach((k) => { if (!L.hidden[k] && allowed(k) && WIDGETS[k]) h += WIDGETS[k](); });
    h += "</div>";
    box.innerHTML = h;
    bind();
  }

  function visibleOrder() { return L.order.filter((k) => !L.hidden[k] && allowed(k)); }
  function move(k, dir) {
    const vis = visibleOrder(), i = vis.indexOf(k), j = i + dir;
    if (j < 0 || j >= vis.length) return;
    const full = L.order.slice(), a = full.indexOf(vis[i]), b = full.indexOf(vis[j]);
    full[a] = vis[j]; full[b] = vis[i];
    saveLayout({ order: full, preset: "custom" }); render();
  }

  function bind() {
    const $ = (s) => box.querySelector(s);
    $("#f-month").addEventListener("input", (e) => { const v = D.months[+e.target.value].p; if (v !== period) { period = v; load(); } });
    box.querySelectorAll("[data-dept]").forEach((b) => b.addEventListener("click", () => { dept = b.dataset.dept; load(); }));
    $("#edit-btn").addEventListener("click", () => { if (edit) toast("Раскладка сохранена для вас"); edit = !edit; render(); });
    $("#rep-btn").addEventListener("click", () => (window.PulseReport ? window.PulseReport.open(dept) : toast("Отчёт будет доступен в разделе «Отчёт»")));
    box.querySelectorAll("[data-up]").forEach((b) => b.addEventListener("click", () => move(b.dataset.up, -1)));
    box.querySelectorAll("[data-down]").forEach((b) => b.addEventListener("click", () => move(b.dataset.down, 1)));
    box.querySelectorAll("[data-hide]").forEach((b) => b.addEventListener("click", () => {
      const prev = { hidden: { ...L.hidden }, preset: L.preset }, k = b.dataset.hide;
      saveLayout({ hidden: { ...L.hidden, [k]: true }, preset: "custom" }); render();
      toast("Виджет «" + META[k] + "» убран на полку", () => { saveLayout(prev); render(); });
    }));
    box.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => { saveLayout({ hidden: { ...L.hidden, [b.dataset.show]: false }, preset: "custom" }); render(); }));
    box.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => { const p = PRESETS.find((x) => x[0] === b.dataset.preset); saveLayout({ preset: p[0], hidden: p[2] }); render(); }));
    box.querySelectorAll("[data-task]").forEach((b) => b.addEventListener("click", async () => { await api("POST", "/api/dashboard/tasks/" + encodeURIComponent(b.dataset.task)); load(); }));
    const dr = $("#demo-resp");
    if (dr) dr.addEventListener("click", async () => { dr.disabled = true; try { await api("POST", "/api/demo/test-response"); } catch (e) { toast(e.message); } dr.disabled = false; });
  }

  window.addEventListener("pulse:pair-updated", (e) => { flash = e.detail.pair_id; period = null; load().then(() => setTimeout(() => { flash = null; render(); }, 2500)); });
  window.addEventListener("pulse:data-imported", () => { period = null; load(); });
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
