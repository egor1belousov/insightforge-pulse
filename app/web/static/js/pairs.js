// Пары: список с поиском и фильтрами, карточка с вкладками «Диагноз», «Люди», «Действия».
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const params = new URLSearchParams(location.search);
  let LIST = [], cur = Number(params.get("id")) || null, tab = params.get("tab") || "diag", topic = "all", scale = "raw", filter = "all", q = "", C = null;
  const listBox = document.getElementById("pair-list"), cardBox = document.getElementById("pair-card");

  async function loadList() {
    const d = await api("GET", "/api/dashboard");
    LIST = d.pairs;
    if (!cur && LIST.length) cur = (LIST.find((p) => p.visible) || LIST[0]).id;
    renderList();
  }
  function renderList() {
    const s = q.trim().toLowerCase();
    const items = LIST.filter((p) => (filter === "all" || (filter === "risk" ? p.visible : !p.visible)) && (!s || (p.code + p.intern + p.mentor + p.dept).toLowerCase().includes(s)));
    listBox.innerHTML = items.length ? items.map((p) =>
      '<button type="button" data-id="' + p.id + '" aria-current="' + (p.id === cur) + '" style="text-align:left;border:1px solid ' + (p.id === cur ? "var(--ink)" : "var(--line)") + ";background:" + (p.id === cur ? "var(--soft)" : "var(--card)") + ';border-radius:14px;padding:12px;display:flex;gap:10px;align-items:center;cursor:pointer;min-height:60px">' +
      '<span style="width:10px;height:36px;border-radius:999px;background:' + p.st.dot + ';flex-shrink:0"></span><span class="grow col" style="gap:2px"><span class="small" style="font-weight:700">' + esc(p.code) + ' <span style="font-weight:500;color:var(--muted)">· ' + esc(p.dept) + '</span></span><span class="xs" style="color:' + p.st.fg + '">' + esc(p.st.label) + '</span></span><span class="head" style="font-size:15px">' + (p.health ?? "—") + "</span></button>").join("")
      : '<p class="small muted" style="margin:6px 4px">Ничего не найдено. Попробуйте ID стажёра или подразделение.</p>';
    listBox.querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => { cur = +b.dataset.id; topic = "all"; history.replaceState(null, "", "/pairs?id=" + cur + "&tab=" + tab); renderList(); loadCard(); }));
  }
  document.getElementById("pair-search").addEventListener("input", (e) => { q = e.target.value; renderList(); });
  document.querySelectorAll("#pair-filters [data-f]").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.f; document.querySelectorAll("#pair-filters [data-f]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderList();
  }));

  async function loadCard() {
    if (!cur) { cardBox.innerHTML = '<p class="muted">Пар пока нет. Загрузите данные в разделе «Анкеты».</p>'; return; }
    C = await api("GET", "/api/pairs/" + cur + "/diagnosis?topic=" + topic + "&scale=" + scale);
    renderCard();
  }

  function chartSvg() {
    const ch = C.chart, ms = C.months, X = (i) => 40 + i * 98, Y = (v) => 14 + (1 - v) * 180;
    const ix = (p) => ms.findIndex((m) => m.p === p);
    const ip = ch.intern.map(([p, v]) => [X(ix(p)), Y(v)]), mp = ch.mentor.map(([p, v]) => [X(ix(p)), Y(v)]);
    const warm = (C.sig.delta || 0) >= 0, fill = warm ? "rgba(226,139,0,0.18)" : "rgba(47,111,219,0.16)", ffill = warm ? "rgba(226,139,0,0.09)" : "rgba(47,111,219,0.08)";
    const fxp = Math.min(X(ms.length), 628);
    let h = '<div class="chart-wrap"><svg viewBox="0 0 640 230" role="img" aria-label="Оценки стажёра и наставника по месяцам с прогнозом" style="width:100%;height:auto;display:block">';
    h += '<rect x="' + X(ms.length - 1) + '" y="14" width="' + (fxp - X(ms.length - 1)) + '" height="180" fill="#F3F5F9" rx="6"></rect>';
    if (ch.swap) { const sx = X(ix(ch.swap)) - 49; h += '<line x1="' + sx + '" x2="' + sx + '" y1="14" y2="194" stroke="#C26F00" stroke-width="2" stroke-dasharray="3 3"></line><text x="' + (sx - 4) + '" y="26" font-size="10" fill="#C26F00" text-anchor="end">смена наставника</text>'; }
    const labels = scale === "cal" ? ["+0.50", "+0.25", "норма", "−0.25", "−0.50"] : ["1.00", "0.75", "0.50", "0.25", "0.00"];
    [1, 0.75, 0.5, 0.25, 0].forEach((v, k) => { h += '<line x1="40" x2="628" y1="' + Y(v) + '" y2="' + Y(v) + '" stroke="#E6E9EF"></line><text x="34" y="' + (Y(v) + 3) + '" font-size="10" fill="#5B6478" text-anchor="end">' + labels[k] + "</text>"; });
    if (ip.length && mp.length) h += '<polygon points="' + ip.concat(mp.slice().reverse()).map((p) => p.join(",")).join(" ") + '" fill="' + fill + '"></polygon>';
    if (ch.fi != null && ch.fm != null && ip.length && mp.length) {
      const li = ip[ip.length - 1], lm = mp[mp.length - 1];
      h += '<polygon points="' + [li, [fxp, Y(ch.fi)], [fxp, Y(ch.fm)], lm].map((p) => p.join(",")).join(" ") + '" fill="' + ffill + '"></polygon>';
      h += '<polyline points="' + li.join(",") + " " + fxp + "," + Y(ch.fi) + '" fill="none" stroke="#0A7CD6" stroke-width="2" stroke-dasharray="2 4"></polyline><polyline points="' + lm.join(",") + " " + fxp + "," + Y(ch.fm) + '" fill="none" stroke="#0E1424" stroke-width="2" stroke-dasharray="2 4"></polyline>';
    }
    h += '<polyline points="' + mp.map((p) => p.join(",")).join(" ") + '" fill="none" stroke="#0E1424" stroke-width="2.5" stroke-dasharray="6 5"></polyline>';
    h += '<polyline points="' + ip.map((p) => p.join(",")).join(" ") + '" fill="none" stroke="#0A7CD6" stroke-width="3"></polyline>';
    ip.forEach((p) => (h += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="4.5" fill="#0A7CD6" stroke="#fff" stroke-width="2"></circle>'));
    mp.forEach((p) => (h += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="4.5" fill="#0E1424" stroke="#fff" stroke-width="2"></circle>'));
    ms.forEach((m, i) => (h += '<text x="' + X(i) + '" y="216" font-size="11" fill="#5B6478" text-anchor="middle">' + esc(m.short) + "</text>"));
    h += '<text x="' + fxp + '" y="216" font-size="11" fill="#0A7CD6" text-anchor="end">' + esc(C.next_short) + " · прогноз</text></svg></div>";
    h += '<div class="row xs" style="gap:16px;margin-top:8px;color:var(--muted-2)"><span class="row nowrap" style="gap:6px"><span style="width:16px;height:3px;background:var(--accent)"></span>Стажёр ' + esc(C.intern) + '</span><span class="row nowrap" style="gap:6px"><span style="width:16px;border-top:3px dashed var(--ink)"></span>Наставник ' + esc(C.mentor) + '</span><span class="row nowrap" style="gap:6px"><span style="width:14px;height:10px;background:' + fill + ';border-radius:2px"></span>Расхождение</span><span class="row nowrap" style="gap:6px"><span style="width:14px;height:10px;background:var(--bg);border:1px solid var(--line-2);border-radius:2px"></span>Прогноз</span></div>';
    return h;
  }

  function tabDiag() {
    let h = '<section class="card"><p class="eyebrow" style="margin-bottom:12px">Из чего состоит расхождение</p><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px">';
    C.decomp.forEach((d) => { h += '<div class="col" style="border:1px solid ' + d.border + ';border-radius:14px;padding:14px;gap:8px"><div class="row between nowrap"><b class="small">' + esc(d.name) + '</b><span class="head" style="font-size:15px;color:' + d.color + '">' + esc(d.value) + '</span></div><div class="bar"><span style="width:' + d.pct + "%;background:" + d.color + '"></span></div><p class="small muted" style="line-height:1.45">' + esc(d.text) + "</p></div>"; });
    h += "</div></section>";
    h += '<div class="row" style="gap:8px">' + C.topics.map((t) => '<button type="button" class="pill" data-topic="' + t.k + '" aria-pressed="' + (topic === t.k) + '">' + esc(t.n) + "</button>").join("") + '<span class="grow"></span><div class="seg"><button type="button" data-scale="raw" aria-pressed="' + (scale === "raw") + '">Сырые баллы</button><button type="button" data-scale="cal" aria-pressed="' + (scale === "cal") + '">Личная шкала</button></div></div>';
    const tn = (C.topics.find((t) => t.k === topic) || { n: "" }).n.toUpperCase();
    h += '<div class="widgets"><section class="card" style="flex:2 1 480px"><p class="eyebrow">Два взгляда · ' + esc(tn) + '</p><p class="small muted" style="margin:6px 0 10px">' + (scale === "cal" ? "Личная шкала: норма каждого — медиана его первых двух месяцев. Убирает эффект «строгих» и «щедрых» оценщиков." : "Баллы анкеты, приведённые к шкале от 0 до 1.") + "</p>" + chartSvg() + "</section>";
    const d = C.sig.delta, dc = d > 0.1 ? "var(--over-fg)" : d < -0.1 ? "var(--under-fg)" : "var(--ok-fg)", f = C.sig.forecast;
    h += '<section class="card col" style="flex:1 1 260px;gap:12px"><div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px"><div style="background:var(--bg);border-radius:12px;padding:12px"><p class="xs muted">Δ сейчас</p><p class="head" style="font-size:20px;margin-top:6px;color:' + dc + '">' + (d == null ? "—" : (d > 0.004 ? "+" : d < -0.004 ? "−" : "") + Math.abs(d).toFixed(2)) + '</p></div><div style="background:var(--bg);border-radius:12px;padding:12px"><p class="xs muted">|Δ| в ' + esc(C.next_short.toLowerCase()) + '. · прогноз</p><p class="head" style="font-size:20px;margin-top:6px;color:' + (f == null ? "var(--muted)" : f >= 0.5 ? "var(--both)" : "var(--over-fg)") + '">' + (f == null ? "—" : f.toFixed(2)) + "</p></div></div>";
    h += '<p class="small"><b>До красной зоны:</b> ' + esc(C.sig.red) + '</p><div style="border-top:1px solid var(--soft);padding-top:12px"><p class="xs muted" style="margin-bottom:6px">Здоровье ' + C.health + " = 100 минус штрафы</p>";
    h += C.contrib.length ? C.contrib.map((c) => '<div class="row between small nowrap" style="padding:3px 0"><span>' + esc(c.name) + '</span><b style="color:var(--both)">−' + c.v + "</b></div>").join("") : '<p class="small" style="color:var(--ok-fg)">Штрафов нет: оценки близки и растут.</p>';
    h += "</div></section></div>";
    h += '<section class="card"><p class="eyebrow" style="margin-bottom:8px">Δ по темам и месяцам</p><div class="scroll-x"><div style="display:grid;grid-template-columns:130px repeat(' + C.months.length + ',minmax(36px,1fr));gap:3px;font-size:11px;min-width:420px"><span></span>' + C.months.map((m) => '<span style="text-align:center;color:var(--muted)">' + esc(m.short) + "</span>").join("");
    C.heat.forEach((r) => {
      h += '<span class="small" style="color:var(--muted-2);align-self:center">' + esc(r.name) + "</span>";
      r.cells.forEach((v) => { const bg = v == null ? "var(--soft)" : v >= 0 ? "rgba(226,139,0," + Math.min(0.85, 0.08 + Math.abs(v) * 1.4).toFixed(2) + ")" : "rgba(47,111,219," + Math.min(0.75, 0.08 + Math.abs(v) * 1.3).toFixed(2) + ")"; h += '<span style="height:26px;border-radius:6px;background:' + bg + ';display:flex;align-items:center;justify-content:center">' + (v == null ? "" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1).replace(/^0/, "")) + "</span>"; });
    });
    h += '</div></div><p class="xs muted" style="margin-top:8px">Оранжевый — стажёр оценивает выше наставника, синий — ниже.</p></section>';
    if (C.signals.length) {
      h += '<section class="card col"><p class="eyebrow">Сигналы этого месяца</p>';
      C.signals.forEach((s) => {
        h += '<div class="list-row"><span class="grow"><b class="small">' + esc(s.description) + '</b><br><span class="xs muted">' + esc(s.cause) + "</span></span>";
        if (C.can_act && s.id && s.type !== "missing") h += '<span class="row nowrap verdicts" style="gap:6px"><button type="button" class="pill" data-verdict="confirmed" data-sid="' + s.id + '" aria-pressed="' + (s.verdict === "confirmed") + '">Подтверждаю</button><button type="button" class="pill" data-verdict="false_alarm" data-sid="' + s.id + '" aria-pressed="' + (s.verdict === "false_alarm") + '">Ложная тревога</button></span>';
        h += "</div>";
      });
      h += "</section>";
    }
    return h;
  }

  function tabPeople() {
    let h = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">';
    C.people.forEach((p) => { h += '<section class="card col" style="gap:8px"><p class="xs muted" style="letter-spacing:.06em">' + esc(p.role) + '</p><p class="head" style="font-size:20px">' + esc(p.id) + '</p><div class="row" style="gap:6px">' + p.flags.map((f) => '<span class="chip" style="background:' + f.bg + ";color:" + f.fg + '">' + esc(f.text) + "</span>").join("") + '</div><p class="small" style="color:var(--muted-2);line-height:1.5">' + esc(p.note) + "</p></section>"; });
    h += '</div><section class="card col"><p class="eyebrow">Комментарии · разбор ИИ</p>';
    if (!C.comments.length) h += '<p class="small muted">Комментариев пока нет.</p>';
    C.comments.forEach((c) => {
      const cls = c.tone === "позитив" ? "ok" : c.tone === "негатив" ? "bad" : "";
      h += '<div style="border:1px solid var(--line);border-radius:14px;padding:12px 14px"><div class="row" style="gap:8px;margin-bottom:6px"><span class="tag">' + esc(c.who + " · " + c.month) + '</span><span class="chip ' + cls + '">' + esc(c.tone) + "</span>" + (c.anxiety >= 0.6 ? '<span class="chip warn">тревога ' + c.anxiety.toFixed(2) + "</span>" : "") + '<span class="xs muted">темы: ' + esc(c.topics) + " · разбор: " + esc(c.source) + '</span></div><p class="small" style="line-height:1.5">«' + esc(c.text) + "»</p></div>";
    });
    h += '</section><section class="card col"><div class="row"><p class="eyebrow grow">Заметки HR</p><span class="chip"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"></rect><path d="M8 11V7a4 4 0 018 0v4"></path></svg>видит только HR</span></div>';
    if (C.can_act) {
      h += '<label for="note-in" class="sr-only">Новая заметка о паре</label><textarea id="note-in" class="input" rows="3" placeholder="Например: Н-204 сказал по телефону, что с декабря объектов станет меньше"></textarea><button type="button" class="btn small" id="note-save" style="align-self:flex-start;border-color:var(--ink)">Сохранить заметку</button>';
      h += C.notes.length ? C.notes.map((n) => '<div style="background:var(--soft-3);border-radius:12px;padding:10px 12px" class="small"><span class="xs muted" style="font-weight:600">' + esc(n.date) + "</span><br>" + esc(n.text) + "</div>").join("") : '<p class="small muted">Заметок пока нет. Сюда удобно записывать то, что не попадает в анкеты: телефонные разговоры, договорённости, контекст.</p>';
    } else h += '<p class="small muted">Заметки HR о паре видны только HR-партнёру.</p>';
    return h + "</section>";
  }

  function tabAct() {
    const steps = ["assigned", "done", "effect_checked"], names = ["Назначено", "Выполнено", "Эффект проверен"];
    let h = '<div class="widgets"><section class="card col" style="flex:1 1 360px"><p class="eyebrow">Действия</p>';
    let n = 0;
    C.actions.forEach((a) => {
      n++;
      const lv = steps.indexOf(a.status) + 1, isMeet = /meeting|talk|expect/.test(a.kind);
      let btn = "";
      if (C.can_act) {
        if (lv === 1) btn = isMeet ? '<button type="button" class="btn small" data-meet="' + a.id + '">Внести итоги встречи</button>' : '<button type="button" class="btn small" data-status="done" data-aid="' + a.id + '">Отметить выполненным</button>';
        else if (lv === 2) btn = '<button type="button" class="btn small" data-status="effect_checked" data-aid="' + a.id + '">Проверить эффект</button>';
      }
      h += '<div class="col" style="border:1px solid var(--line);border-radius:14px;padding:12px 14px;gap:10px"><div class="row nowrap" style="gap:12px"><span class="head" style="font-size:14px;color:var(--accent)">0' + n + '</span><div class="grow"><p class="small" style="font-weight:600">' + esc(a.title) + "</p></div>" + btn + "</div>";
      h += '<div class="row" style="gap:4px">' + names.map((nm, j) => '<span class="chip ' + (j < lv ? "ok" : "") + '">' + (j < lv ? "✓ " : "") + nm + "</span>").join("") + "</div>";
      if (a.agreements && a.agreements.length) h += '<div class="col" style="gap:6px;border-top:1px solid var(--soft);padding-top:8px"><p class="eyebrow">Договорённости</p>' + a.agreements.map((x) => '<div class="row nowrap small" style="gap:10px"><b style="min-width:120px">' + esc(x.who) + '</b><span class="grow">' + esc(x.what) + '</span><span class="muted" style="white-space:nowrap">' + esc(x.when) + "</span></div>").join("") + "</div>";
      if (a.effect) h += '<p class="small" style="border-radius:10px;padding:8px 10px;background:' + (a.effect.good === false ? "var(--over-bg)" : a.effect.good ? "var(--ok-bg)" : "var(--soft)") + ";color:" + (a.effect.good === false ? "var(--over-fg)" : a.effect.good ? "var(--ok-fg)" : "var(--muted-2)") + '">' + esc(a.effect.text) + "</p>";
      h += "</div>";
    });
    if (C.recommended.length) {
      h += '<p class="eyebrow" style="margin-top:6px">Рекомендовано по сигналам</p>';
      C.recommended.forEach((r) => {
        n++;
        h += '<div class="row nowrap" style="border:1px dashed var(--line-3);border-radius:14px;padding:12px 14px;gap:12px"><span class="head" style="font-size:14px;color:var(--faint)">0' + n + '</span><div class="grow"><p class="small" style="font-weight:600">' + esc(r.title) + '</p><p class="xs muted">' + esc(r.note) + "</p></div>" + (C.can_act ? '<button type="button" class="btn primary small" data-assign="' + esc(r.kind) + '" data-title="' + esc(r.title) + '">Назначить</button>' : "") + "</div>";
      });
    }
    if (!C.actions.length && !C.recommended.length) h += '<p class="small muted">Действий нет: сигналов в паре нет.</p>';
    h += "</section>";
    const meet = C.actions.find((a) => /meeting|talk|expect/.test(a.kind));
    h += '<section class="col" style="flex:1 1 360px;background:#070A14;color:#fff;border-radius:18px;padding:20px;gap:12px"><p class="xs" style="color:#9AA6C6;font-weight:700;letter-spacing:.06em">ПОВЕСТКА ВСТРЕЧИ ВТРОЁМ · ИИ</p>';
    if (meet && meet.agenda && meet.agenda.length) {
      h += '<ol style="margin:0;padding-left:20px;font-size:14px;line-height:1.6;color:#E6EAF5">' + meet.agenda.map((x) => '<li style="margin-bottom:6px">' + esc(x) + "</li>").join("") + "</ol>";
      if (C.can_act) h += '<div class="row"><button type="button" class="btn small" style="border:0" id="agenda-send">Отправить приглашение на встречу</button><button type="button" class="btn small on-dark" data-agenda="' + meet.id + '">Сформировать заново</button></div>';
    } else {
      h += '<p class="small" style="color:#C9D1E6;line-height:1.5">ИИ соберёт план разговора из сигналов пары. Сырые ответы сторон в повестку не попадают.</p>';
      if (C.can_act) h += meet ? '<button type="button" class="btn" style="align-self:flex-start;border:0" data-agenda="' + meet.id + '">Сформировать повестку →</button>' : '<button type="button" class="btn" style="align-self:flex-start;border:0" data-assign="meeting" data-title="Встреча втроём: стажёр, наставник, HR" data-then-agenda="1">Назначить встречу и сформировать повестку →</button>';
    }
    return h + "</section></div>";
  }

  function renderCard() {
    if (C.empty) {
      cardBox.innerHTML = '<section class="card col" style="padding:clamp(20px,3vw,32px);gap:14px"><p class="xs muted" style="letter-spacing:.1em">' + esc(C.dept.toUpperCase() + " · СТАЖЁР " + C.intern + " · НАСТАВНИК " + C.mentor) + '</p><h1 class="head" style="font-size:clamp(22px,2.6vw,30px)">Пара ' + esc(C.code) + ' — данных пока нет</h1><p style="color:var(--muted-2);line-height:1.6;max-width:640px">Расхождение по уровню будет видно после первой анкеты обеих сторон, тренд — после второй: по одной точке направление не посчитать.</p><a class="btn primary" style="align-self:flex-start" href="/program">Открыть в разделе «Программа» →</a></section>';
      return;
    }
    let h = "";
    if (C.talk) h += '<div role="status" class="row" style="background:var(--over-bg);border:1px solid #F5C77A;border-radius:14px;padding:12px 14px"><span class="grow small" style="color:#5A3300"><b>' + esc(C.talk.who) + " просит разговор с HR</b> · тема: " + esc(C.talk.topic) + ". " + esc(C.talk.text) + "</span>" + (C.can_act ? '<button type="button" class="btn primary small" id="talk-answer">Назначить встречу</button>' : "") + "</div>";
    h += '<section class="hero" style="border-radius:22px"><div class="sphere orb" data-orb="mesh" data-size="560" aria-hidden="true"></div><div class="row between" style="align-items:flex-end;gap:18px"><div style="min-width:0;max-width:640px"><p class="tagline">' + esc(C.dept + " · СТАЖЁР " + C.intern + " · НАСТАВНИК " + C.mentor) + "</p><h1>Пара " + esc(C.code) + '</h1><p class="sub" id="summary">' + esc(C.summary) + "</p>";
    if (C.swap) h += '<p class="small" style="margin-top:10px;display:inline-block;background:rgba(255,180,80,.18);color:#FFD9A0;border-radius:8px;padding:6px 10px">С месяца «' + esc(C.swap.month) + "» наставник — " + esc(C.mentor) + " (был " + esc(C.swap.was) + "). История сохранена, на графике отмечена смена.</p>";
    h += '<div class="row" style="margin-top:12px"><button type="button" class="btn small on-dark" id="explain-btn">Объяснить простыми словами · ИИ</button></div></div><div class="row nowrap" style="gap:16px"><div style="text-align:right"><p class="xs" style="color:#9AA6C6;letter-spacing:.08em">ЗДОРОВЬЕ</p><p class="head" style="font-size:34px;margin-top:2px">' + C.health + '</p></div><span class="chip" style="font-size:13px;padding:8px 14px;background:' + C.st.bg + ";color:" + C.st.fg + '">' + esc(C.st.label) + "</span></div></div></section>";
    h += '<div class="tabs" role="tablist" aria-label="Разделы карточки пары">' + [["diag", "Диагноз"], ["people", "Люди, комментарии, заметки"], ["act", "Действия"]].map(([k, n]) => '<button type="button" role="tab" data-tab="' + k + '" aria-selected="' + (tab === k) + '">' + n + "</button>").join("") + "</div>";
    h += tab === "diag" ? tabDiag() : tab === "people" ? tabPeople() : tabAct();
    cardBox.innerHTML = h;
    bindCard();
  }

  function bindCard() {
    const $ = (s) => cardBox.querySelector(s), all = (s) => cardBox.querySelectorAll(s);
    all("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; history.replaceState(null, "", "/pairs?id=" + cur + "&tab=" + tab); renderCard(); }));
    all("[data-topic]").forEach((b) => b.addEventListener("click", () => { topic = b.dataset.topic; loadCard(); }));
    all("[data-scale]").forEach((b) => b.addEventListener("click", () => { scale = b.dataset.scale; loadCard(); }));
    all("[data-verdict]").forEach((b) => b.addEventListener("click", async () => {
      const on = b.getAttribute("aria-pressed") === "true";
      await api("POST", "/api/signals/" + b.dataset.sid + "/verdict", { verdict: on ? null : b.dataset.verdict });
      toast(on ? "Отметка снята" : b.dataset.verdict === "confirmed" ? "Сигнал подтверждён — учтём в оценке эффекта" : "Отмечено как ложная тревога"); loadCard();
    }));
    const ex = $("#explain-btn");
    if (ex) ex.addEventListener("click", async () => { ex.disabled = true; ex.textContent = "ИИ формулирует…"; try { const r = await api("POST", "/api/pairs/" + cur + "/explain"); $("#summary").textContent = r.text; ex.textContent = r.fallback ? "Объяснение по правилам" : "Объяснено ИИ по фактам из базы"; } catch (e) { toast(e.message); ex.disabled = false; } });
    const ns = $("#note-save");
    if (ns) ns.addEventListener("click", async () => { const t = $("#note-in").value.trim(); if (!t) { toast("Заметка пустая"); return; } await api("POST", "/api/pairs/" + cur + "/notes", { text: t }); toast("Заметка сохранена. Её видите только вы"); loadCard(); });
    all("[data-assign]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      const r = await api("POST", "/api/pairs/" + cur + "/actions", { kind: b.dataset.assign, title: b.dataset.title });
      if (b.dataset.thenAgenda) { b.textContent = "ИИ готовит повестку…"; await api("POST", "/api/actions/" + r.id + "/agenda"); }
      toast("Назначено: " + b.dataset.title + " (" + C.code + ")", async () => { await api("DELETE", "/api/actions/" + r.id); loadCard(); });
      loadCard();
    }));
    all("[data-status]").forEach((b) => b.addEventListener("click", async () => { await api("POST", "/api/actions/" + b.dataset.aid + "/status", { status: b.dataset.status }); toast(b.dataset.status === "done" ? "Отмечено как выполненное. Эффект покажет следующая анкета" : "Эффект проверен"); loadCard(); }));
    all("[data-agenda]").forEach((b) => b.addEventListener("click", async () => { b.disabled = true; b.textContent = "ИИ готовит повестку…"; try { await api("POST", "/api/actions/" + b.dataset.agenda + "/agenda"); } catch (e) { toast(e.message); } loadCard(); }));
    const as = $("#agenda-send");
    if (as) as.addEventListener("click", () => toast("Приглашение на встречу с повесткой отправлено " + C.intern + " и " + C.mentor));
    const ta = $("#talk-answer");
    if (ta) ta.addEventListener("click", async () => { await api("POST", "/api/talk/" + C.talk.id + "/answer", { text: "HR назначил встречу на ближайшие два рабочих дня" }); toast("Встреча назначена, приглашение отправлено " + C.talk.who); loadCard(); });
    all("[data-meet]").forEach((b) => b.addEventListener("click", () => openMeet(+b.dataset.meet)));
  }

  function openMeet(aid) {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="meet-t"><div class="row between"><h2 class="head" id="meet-t" style="font-size:20px">Итоги встречи · ' + esc(C.code) + '</h2><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div><label class="label" for="meet-text">Что обсудили и о чём договорились — свободным текстом</label><textarea class="input" id="meet-text" rows="6" placeholder="Например: стажёр согласен сдавать работу после самопроверки с 16 ноября, наставник раз в неделю даёт развёрнутую обратную связь по пятницам, HR проводит контрольную встречу 27 ноября."></textarea><button type="button" class="btn" id="meet-ai">Выделить договорённости · ИИ</button><div id="meet-res"></div><div class="row"><button type="button" class="btn primary" id="meet-save" disabled>Сохранить и отправить участникам</button><button type="button" class="btn" data-close>Отмена</button></div></div>';
    document.body.appendChild(back);
    let agreements = [];
    const close = () => back.remove();
    back.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
    back.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    back.querySelector("#meet-text").focus();
    back.querySelector("#meet-ai").addEventListener("click", async (e) => {
      const btn = e.target, text = back.querySelector("#meet-text").value;
      if (!text.trim()) { toast("Опишите итоги встречи"); return; }
      btn.disabled = true; btn.textContent = "ИИ разбирает текст…";
      try {
        const r = await api("POST", "/api/actions/" + aid + "/outcomes", { text });
        agreements = r.agreements;
        back.querySelector("#meet-res").innerHTML = agreements.length ? '<div class="col" style="gap:6px;background:var(--soft-3);border-radius:12px;padding:12px"><p class="eyebrow">Договорённости · ' + (r.fallback ? "правила" : "ИИ") + "</p>" + agreements.map((x) => '<div class="row nowrap small" style="gap:10px"><b style="min-width:120px">' + esc(x.who) + '</b><span class="grow">' + esc(x.what) + '</span><span class="muted">' + esc(x.when) + "</span></div>").join("") + "</div>" : '<p class="small muted">Договорённостей не найдено — уточните, кто что делает и когда.</p>';
        back.querySelector("#meet-save").disabled = false;
      } catch (x) { toast(x.message); }
      btn.disabled = false; btn.textContent = "Выделить договорённости · ИИ";
    });
    back.querySelector("#meet-save").addEventListener("click", async () => {
      await api("PUT", "/api/actions/" + aid + "/outcomes", { text: back.querySelector("#meet-text").value, agreements });
      close(); toast("Итоги сохранены, договорённости отправлены участникам"); loadCard();
    });
  }

  window.addEventListener("pulse:pair-updated", (e) => { loadList(); if (e.detail.pair_id === cur) loadCard(); });
  loadList().then(loadCard).catch((e) => { cardBox.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
