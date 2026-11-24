// Анкеты (HR): рассылки, конструктор, источники и загрузка.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page");
  let tab = new URLSearchParams(location.search).get("tab") || "send", M = null, Q = null, S = null, side = "intern", sug = null;
  const TOPICS = { tasks: "Понимание задач", auto: "Самостоятельность", support: "Поддержка", load: "Нагрузка", feedback: "Обратная связь", growth: "Перспективы" };
  const CH = [["email", "Письмо на рабочую почту", "Ссылка на анкету, вход без пароля", "smtp"], ["tg", "Telegram-бот", "Анкета прямо в чате, оценки кнопками", "telegram"], ["site", "Уведомление на сайте", "Колокольчик и карточка «Заполнить анкету»", null]];
  const CH_SHORT = { email: "почта", tg: "Telegram", site: "сайт" };

  async function load() {
    if (tab === "send") M = await api("GET", "/api/forms/mailing");
    if (tab === "build") Q = await api("GET", "/api/questionnaires");
    if (tab === "src") S = await api("GET", "/api/forms/status");
    render();
  }
  const sw = (on, attrs) => '<button type="button" role="switch" aria-checked="' + on + '" ' + attrs + ' style="width:44px;height:26px;border-radius:999px;border:0;background:' + (on ? "var(--accent)" : "var(--line-3)") + ';position:relative;cursor:pointer;flex-shrink:0"><span style="position:absolute;top:3px;left:' + (on ? 21 : 3) + 'px;width:20px;height:20px;border-radius:50%;background:var(--card)"></span></button>';

  function render() {
    let h = '<section class="hero"><div class="sphere orb" data-orb="mesh" data-size="560" aria-hidden="true"></div><p class="tagline">Анкеты</p><h1>Рассылки, конструктор и источники</h1><p class="sub">Анкета раз в месяц: каждому вопросу — тема и «зеркальный» вопрос другой стороне, иначе расхождение не посчитать.</p></section>';
    h += '<div class="seg" role="tablist">' + [["send", "Рассылки"], ["build", "Конструктор"], ["src", "Источники и загрузка"]].map(([k, n]) => '<button type="button" role="tab" data-tab="' + k + '" aria-selected="' + (tab === k) + '">' + n + "</button>").join("") + "</div>";
    h += tab === "send" ? sendTab() : tab === "build" ? buildTab() : srcTab();
    box.innerHTML = h; bind();
  }
  function sendTab() {
    if (!M.rows.length) return '<div class="widgets"><section class="card col" style="flex:2 1 520px;align-items:flex-start"><p class="eyebrow">Рассылка за ' + esc(M.month) + '</p><p class="head" style="font-size:22px">В потоке пока нет пар</p><p class="small muted" style="line-height:1.5">Анкета уходит стажёру и наставнику каждой пары. Добавьте участников и соберите пары — рассылка начнётся в начале месяца, каналы и напоминания уже можно настроить справа.</p><a class="btn primary small" href="/program">К участникам и парам →</a></section><div class="col" style="flex:1 1 340px;gap:16px">' + channelsCard() + remindersCard() + "</div></div>";
    const pend = M.rows.filter((r) => r.status !== "заполнено").map((r) => r.external_id);
    let h = '<div class="widgets"><section class="card col" style="flex:2 1 520px"><div class="row between"><p class="eyebrow">Рассылка за ' + esc(M.month) + " · " + M.got + " из " + M.total + "</p>" + (pend.length ? '<button type="button" class="btn primary small" data-remind="' + esc(pend.join(",")) + '">Напомнить всем, кто не заполнил</button>' : "") + "</div>";
    const rem = M.rows.filter((r) => r.status === "напомнили").length;
    h += Pulse.progress([{ n: M.got, cls: "ok", label: "заполнено" }, { n: rem, cls: "warn", label: "напомнили" }, { n: M.total - M.got - rem, cls: "bad", label: "не заполнено" }], { big: true });
    h += '<div class="scroll-x" style="margin-top:6px"><table class="tbl cards"><thead><tr><th>Участник</th><th>Пара</th><th>Анкета</th><th>Статус</th><th></th></tr></thead><tbody>';
    M.rows.forEach((r) => {
      const cls = r.status === "заполнено" ? "ok" : r.status === "напомнили" ? "warn" : "bad";
      h += "<tr><td><b>" + esc(r.external_id) + "</b></td><td>" + esc(r.pair) + "</td><td>" + (r.side === "intern" ? "Стажёр" : "Наставник") + " · " + r.questions + ' вопр.</td><td><span class="chip ' + cls + '">' + esc(r.status) + '</span></td><td class="row nowrap" style="gap:6px">' + (r.status !== "заполнено" ? '<button type="button" class="btn small" data-remind="' + esc(r.external_id) + '">Напомнить</button>' : "") + (r.response_id ? '<button type="button" class="btn ghost small" data-answers="' + r.response_id + '">Ответы</button>' : '<button type="button" class="btn ghost small" data-copy="' + esc(location.origin + r.link) + '" title="Личная ссылка участника — можно отправить вручную">Ссылка</button>') + "</td></tr>";
    });
    h += '</tbody></table></div><p class="xs muted">Следующая рассылка — в начале месяца «' + esc(M.next) + "». Ссылка на анкету личная, открывается с телефона без пароля.</p></section>";
    h += '<div class="col" style="flex:1 1 340px;gap:16px">' + channelsCard() + remindersCard() + "</div></div>";
    return h;
  }
  // Каналы: куда вообще доставляем анкету и напоминания
  function channelsCard() {
    let h = '<section class="card col"><p class="eyebrow">Каналы доставки</p><p class="xs muted">Куда уходят приглашения и напоминания HR. Неподключённый канал пропускается — в итоге рассылки видно, что не ушло.</p>';
    CH.forEach(([k, n, d, integ]) => {
      const con = M.connected[k], on = !!M.channels[k];
      const st = con ? '<span class="chip ok">подключено' + (k === "tg" ? " · чатов " + M.tg_linked : "") + "</span>" : '<a class="chip warn" href="/settings#int-' + integ + '" style="text-decoration:none">не подключено — настроить</a>';
      h += '<div class="row nowrap" style="gap:12px;padding:10px 0;border-top:1px solid var(--soft)"><span class="grow col" style="gap:4px"><b class="small">' + n + '</b><span class="xs muted">' + d + "</span>" + (k === "site" ? "" : "<span>" + st + "</span>") + "</span>" + sw(on, 'data-ch="' + k + '" aria-label="' + n + '"') + "</div>";
    });
    return h + "</section>";
  }
  // Автонапоминания: расписание, тихие часы, эскалация HR
  function remindersCard() {
    const R = M.reminders, step = (k, v, unit, min, max) => '<span class="row nowrap stepper" style="gap:6px"><button type="button" class="icon-btn" data-rs="' + k + '" data-d="-1" aria-label="Меньше"' + (v <= min ? " disabled" : "") + '>−</button><b style="min-width:58px;text-align:center" class="small">' + v + (unit[0] === ":" ? "" : " ") + unit + '</b><button type="button" class="icon-btn" data-rs="' + k + '" data-d="1" aria-label="Больше"' + (v >= max ? " disabled" : "") + ">+</button></span>";
    let h = '<section class="card col"><div class="row between nowrap"><p class="eyebrow">Автонапоминания</p>' + sw(R.on, 'data-r-on aria-label="Автонапоминания"') + "</div>";
    if (!R.on) return h + '<p class="small muted">Выключены: напоминает только HR вручную.</p></section>';
    const row = (label, ctl, hint) => '<div class="row between" style="gap:10px;padding:8px 0;border-top:1px solid var(--soft)"><span class="col" style="gap:2px"><span class="small">' + label + "</span>" + (hint ? '<span class="xs muted">' + hint + "</span>" : "") + "</span>" + ctl + "</div>";
    h += row("Первое напоминание", step("first_days", R.first_days, "дн.", 1, 27), "после начала месяца");
    h += row("Второе напоминание", step("second_days", R.second_days, "дн.", R.first_days + 1, 28), "если анкеты всё ещё нет");
    h += row("Сколько напоминать", step("max", R.max, "раз", 0, 2), "");
    h += row("Сообщить HR", step("escalate_days", R.escalate_days, "дн.", R.second_days, 28), "если не ответили и после напоминаний");
    h += row("Тихие часы", '<span class="row nowrap" style="gap:6px">' + step("quiet_from", R.quiet_from, ":00", 0, 23) + '<span class="xs muted">до</span>' + step("quiet_to", R.quiet_to, ":00", 0, 23) + "</span>", "ночью не беспокоим");
    h += '<div class="col" style="gap:8px;padding:10px 0;border-top:1px solid var(--soft)"><span class="small">Каналы напоминаний</span><div class="row" style="gap:6px">' + CH.map(([k, n]) => '<button type="button" class="pill accent" data-rch="' + k + '" aria-pressed="' + !!R.channels[k] + '">' + esc(CH_SHORT[k]) + "</button>").join("") + "</div></div>";
    if (M.plan.length) h += '<div class="col" style="gap:6px;background:var(--soft-3);border-radius:12px;padding:12px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">ПЛАН</span>' + M.plan.map((x) => '<span class="small">' + esc(x) + "</span>").join("") + "</div>";
    h += '<button type="button" class="btn small" id="r-run" style="align-self:flex-start">Проверить и отправить сейчас</button>';
    return h + "</section>";
  }
  async function saveReminders(patch) { M.reminders = await api("PUT", "/api/forms/reminders", { ...M.reminders, ...patch }); M = await api("GET", "/api/forms/mailing"); render(); }

  function buildTab() {
    let h = '<section class="card col"><div class="row between"><p class="eyebrow">Новый вопрос · тема и зеркальный вопрос от ИИ</p><div class="seg">' + [["intern", "Стажёру"], ["mentor", "Наставнику"]].map(([k, n]) => '<button type="button" data-side="' + k + '" aria-pressed="' + (side === k) + '">' + n + "</button>").join("") + "</div></div>";
    h += '<div class="row"><label class="sr-only" for="nq">Текст вопроса</label><input class="input" id="nq" placeholder="Например: Получаете ли вы обратную связь по своей работе?" style="flex:1 1 320px;width:auto"><button type="button" class="btn primary" id="nq-go">Предложить тему</button></div>';
    if (sug) {
      h += '<div class="col" style="background:var(--soft-3);border-radius:14px;padding:14px;gap:10px"><div class="row"><span class="small"><b>Тема:</b></span><select class="input small" id="sug-topic" style="width:auto">' + Object.entries(TOPICS).map(([k, n]) => '<option value="' + k + '"' + (k === sug.topic ? " selected" : "") + ">" + n + "</option>").join("") + "</select>" + Pulse.conf(sug.confidence) + '<span class="xs muted">' + (sug.fallback ? "правила" : "ИИ") + "</span></div>";
      h += '<label class="label" for="sug-mirror">Зеркальный вопрос ' + (side === "intern" ? "наставнику" : "стажёру") + (sug.mirror_exists ? " (уже есть в анкете)" : "") + '</label><input class="input" id="sug-mirror" value="' + esc(sug.mirror_text) + '"' + (sug.mirror_exists ? " disabled" : "") + ">";
      h += '<div class="row"><button type="button" class="btn primary" id="add-both">' + (sug.mirror_exists ? "Добавить вопрос" : "Добавить оба вопроса") + '</button>' + (sug.mirror_exists ? "" : '<button type="button" class="btn" id="add-one">Только этот вопрос</button>') + '</div><p class="xs muted">Изменение создаёт новую версию анкеты. Ответы до и после считаются отдельно, на графиках появится отметка версии.</p></div>';
    }
    h += "</section>";
    const ok = Q.coverage.filter((c) => c.intern && c.mentor).length;
    h += '<section class="card col"><p class="eyebrow">Покрытие тем · ' + ok + " из " + Q.coverage.length + '</p><div class="grid-auto" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">' + Q.coverage.map((c) => { const g = c.intern && c.mentor; return '<div style="border-radius:12px;padding:10px 12px;background:' + (g ? "var(--ok-bg)" : "var(--both-bg)") + ";border:1px solid " + (g ? "var(--ok)" : "var(--both)") + '"><b class="small">' + esc(c.name) + '</b><br><span class="xs muted">стажёр ' + c.intern + " · наставник " + c.mentor + "</span></div>"; }).join("") + "</div></section>";
    h += '<div class="widgets">' + ["intern", "mentor"].map((s) => { const q = Q[s]; return '<section class="card col" style="flex:1 1 380px"><div class="row between"><p class="eyebrow">Анкета ' + (s === "intern" ? "стажёра" : "наставника") + " · v" + q.version + '</p><span class="xs muted">' + q.versions.map((v) => "v" + v.version + " · " + esc(v.source) + " · " + esc(v.created)).join(" → ") + "</span></div>" + q.questions.map((x, i) => '<div class="list-row small"><span class="tag">' + (i + 1) + '</span><span class="grow">' + esc(x.text) + "</span>" + (x.qtype === "text" ? '<span class="chip">текст</span>' : '<span class="chip info">' + esc(x.topic_name) + "</span>" + (x.mirror ? "" : '<span class="chip warn" title="Без зеркального вопроса расхождение по теме не посчитать">без пары</span>')) + "</div>").join("") + "</section>"; }).join("") + "</div>";
    return h;
  }
  function srcTab() {
    let h = '<div class="widgets"><section class="card col" style="flex:1 1 360px"><p class="eyebrow">Загрузка Excel и Word</p><p class="small muted">Перетащите выгрузки ответов и структуру анкет — система поймёт формат сама и покажет экран «Мы поняли так».</p><a class="btn primary" style="align-self:flex-start" href="/import">Загрузить файлы →</a></section>';
    h += '<section class="card col" style="flex:1 1 360px"><p class="eyebrow">Внешние формы</p>';
    h += '<div class="list-row"><span class="grow small"><b>Яндекс Формы</b><br><span class="xs muted">вебхук ' + esc(location.origin + S.yandex.webhook) + "?token=… и опрос API каждые " + S.poll_seconds + ' с</span></span><span class="chip ' + (S.yandex.enabled ? "ok" : "") + '">' + (S.yandex.enabled ? "подключено" : "не подключено") + "</span></div>";
    h += '<div class="list-row"><span class="grow small"><b>Google Forms</b><br><span class="xs muted">forms.responses.list каждые ' + S.poll_seconds + ' с</span></span><span class="chip ' + (S.google.enabled ? "ok" : "") + '">' + (S.google.enabled ? "подключено" : "не подключено") + "</span></div>";
    h += '<p class="xs muted">Подключение — токены в .env, инструкция в docs/FORMS.md. Поля формы сопоставляются с вопросами так же, как при загрузке файлов.</p>';
    if (window.PULSE_DEMO) h += '<button type="button" class="btn" id="demo-resp" style="align-self:flex-start">Отправить тестовый ответ</button>';
    return h + "</section></div>";
  }
  async function showAnswers(id) {
    const R = await api("GET", "/api/forms/responses/" + id);
    const who = (R.side === "intern" ? "Стажёр " : "Наставник ") + R.external_id;
    const rows = R.answers.map((a) => {
      const scale = a.qtype !== "text" && a.value != null && a.max != null;
      const pct = scale ? Math.round(((Number(a.value) - (a.min ?? 0)) / Math.max(1, a.max - (a.min ?? 0))) * 100) : 0;
      return '<div class="col" style="gap:6px;padding:12px 0;border-bottom:1px solid var(--line, var(--soft))"><span class="small"><b>' + esc(a.question) + "</b>" + (a.topic ? ' <span class="chip">' + esc(a.topic) + "</span>" : "") + "</span>" +
        (scale ? '<div class="row nowrap" style="gap:10px"><span class="bar" style="flex:1"><span style="width:' + pct + '%;background:var(--accent)"></span></span><b class="small" style="min-width:56px;text-align:right">' + esc(a.value) + " из " + a.max + "</b></div>" : "") +
        (a.text ? '<p class="small" style="background:var(--bg);border-radius:12px;padding:10px 12px;line-height:1.5">«' + esc(a.text) + "»</p>" : a.qtype === "text" ? '<p class="xs muted">без комментария</p>' : "") + "</div>";
    }).join("");
    Pulse.modal('<div class="modal" role="dialog" aria-modal="true" aria-labelledby="ans-t"><div class="row between"><div><p class="eyebrow">Анкета за ' + esc(R.month) + '</p><h2 class="head" id="ans-t" style="font-size:20px">' + esc(who) + '</h2></div><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div><div class="col" style="gap:0">' + (rows || '<p class="small muted">Ответов нет.</p>') + '</div><p class="xs muted">Только для чтения. Ответы видит HR; другая сторона пары их не видит.</p></div>');
  }

  function bind() {
    box.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; history.replaceState(null, "", "/forms?tab=" + tab); load(); }));
    box.querySelectorAll("[data-remind]").forEach((b) => b.addEventListener("click", async () => { const r = await api("POST", "/api/forms/remind", { ids: b.dataset.remind.split(",") }); toast(r.message); load(); }));
    box.querySelectorAll("[data-ch]").forEach((b) => b.addEventListener("click", async () => { M.channels = await api("PUT", "/api/forms/channels", { ...M.channels, [b.dataset.ch]: !M.channels[b.dataset.ch] }); render(); }));
    box.querySelectorAll("[data-answers]").forEach((b) => b.addEventListener("click", () => showAnswers(b.dataset.answers)));
    box.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => { try { await navigator.clipboard.writeText(b.dataset.copy); toast("Ссылка скопирована — её можно отправить участнику"); } catch (e) { toast(b.dataset.copy); } }));
    box.querySelectorAll("[data-rs]").forEach((b) => b.addEventListener("click", () => saveReminders({ [b.dataset.rs]: M.reminders[b.dataset.rs] + Number(b.dataset.d) })));
    box.querySelectorAll("[data-rch]").forEach((b) => b.addEventListener("click", () => saveReminders({ channels: { ...M.reminders.channels, [b.dataset.rch]: !M.reminders.channels[b.dataset.rch] } })));
    const ron = box.querySelector("[data-r-on]");
    if (ron) ron.addEventListener("click", () => saveReminders({ on: !M.reminders.on }));
    const rrun = box.querySelector("#r-run");
    if (rrun) rrun.addEventListener("click", async () => { rrun.disabled = true; const r = await api("POST", "/api/forms/reminders/run"); toast(r.message); load(); });
    box.querySelectorAll("[data-side]").forEach((b) => b.addEventListener("click", () => { side = b.dataset.side; sug = null; render(); }));
    const go = box.querySelector("#nq-go");
    if (go) go.addEventListener("click", async () => {
      const text = box.querySelector("#nq").value.trim() || "Получаете ли вы обратную связь по своей работе?";
      go.disabled = true; go.textContent = "ИИ думает…";
      try { sug = await api("POST", "/api/questions/suggest", { text, side }); sug.text = text; render(); box.querySelector("#nq").value = text; } catch (e) { toast(e.message); go.disabled = false; }
    });
    const add = async (both) => {
      try {
        await api("POST", "/api/questions", { side, text: sug.text, topic: box.querySelector("#sug-topic").value, mirror_text: both && !sug.mirror_exists ? box.querySelector("#sug-mirror").value : null, scale_min: 1, scale_max: 10 });
        toast(both && !sug.mirror_exists ? "Добавлены два зеркальных вопроса — тему можно сравнивать" : "Вопрос добавлен"); sug = null; load();
      } catch (e) { toast(e.message); }
    };
    const ab = box.querySelector("#add-both"); if (ab) ab.addEventListener("click", () => add(true));
    const ao = box.querySelector("#add-one"); if (ao) ao.addEventListener("click", () => add(false));
    const dr = box.querySelector("#demo-resp"); if (dr) dr.addEventListener("click", async () => { try { await api("POST", "/api/demo/test-response"); } catch (e) { toast(e.message); } });
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
