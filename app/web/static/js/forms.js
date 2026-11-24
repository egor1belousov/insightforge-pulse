// Анкеты (HR): рассылки, конструктор, источники и загрузка.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page");
  let tab = new URLSearchParams(location.search).get("tab") || "send", M = null, Q = null, S = null, side = "intern", sug = null, pv = "mail";
  const TOPICS = { tasks: "Понимание задач", auto: "Самостоятельность", support: "Поддержка", load: "Нагрузка", feedback: "Обратная связь", growth: "Перспективы" };
  const CH = [["email", "Письмо на рабочую почту", "Ссылка на анкету, вход без пароля"], ["tg", "Telegram-бот", "Можно ответить прямо в чате"], ["site", "Уведомление на сайте", "Колокольчик и карточка «Заполнить анкету»"], ["auto", "Автонапоминания", "Через 2 и 4 дня, если анкета не заполнена"]];

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
    const pend = M.rows.filter((r) => r.status !== "заполнено").map((r) => r.external_id);
    let h = '<div class="widgets"><section class="card col" style="flex:2 1 520px"><div class="row between"><p class="eyebrow">Рассылка за ' + esc(M.month) + " · " + M.got + " из " + M.total + "</p>" + (pend.length ? '<button type="button" class="btn primary small" data-remind="' + esc(pend.join(",")) + '">Напомнить всем, кто не заполнил</button>' : "") + "</div>";
    const rem = M.rows.filter((r) => r.status === "напомнили").length;
    h += Pulse.progress([{ n: M.got, cls: "ok", label: "заполнено" }, { n: rem, cls: "warn", label: "напомнили" }, { n: M.total - M.got - rem, cls: "bad", label: "не заполнено" }], { big: true });
    h += '<div class="scroll-x" style="margin-top:6px"><table class="tbl"><thead><tr><th>Участник</th><th>Пара</th><th>Анкета</th><th>Статус</th><th></th></tr></thead><tbody>';
    M.rows.forEach((r) => {
      const cls = r.status === "заполнено" ? "ok" : r.status === "напомнили" ? "warn" : "bad";
      h += "<tr><td><b>" + esc(r.external_id) + "</b></td><td>" + esc(r.pair) + "</td><td>" + (r.side === "intern" ? "Стажёр" : "Наставник") + " · " + r.questions + ' вопр.</td><td><span class="chip ' + cls + '">' + esc(r.status) + '</span></td><td class="row nowrap" style="gap:6px">' + (r.status !== "заполнено" ? '<button type="button" class="btn small" data-remind="' + esc(r.external_id) + '">Напомнить</button>' : "") + (r.response_id ? '<button type="button" class="btn ghost small" data-answers="' + r.response_id + '">Ответы</button>' : '<button type="button" class="btn ghost small" data-copy="' + esc(location.origin + r.link) + '" title="Личная ссылка участника — можно отправить вручную">Ссылка</button>') + "</td></tr>";
    });
    h += '</tbody></table></div><p class="xs muted">Следующая рассылка — в начале месяца «' + esc(M.next) + "». Ссылка на анкету личная, открывается с телефона без пароля.</p></section>";
    h += '<section class="card col" style="flex:1 1 300px"><p class="eyebrow">Каналы</p>' + CH.map(([k, n, d]) => '<div class="row nowrap" style="gap:12px;padding:6px 0"><span class="grow"><b class="small">' + n + '</b><br><span class="xs muted">' + d + "</span></span>" + sw(!!M.channels[k], 'data-ch="' + k + '" aria-label="' + n + '"') + "</div>").join("");
    h += '<p class="eyebrow" style="margin-top:8px">Предпросмотр</p><div class="seg">' + [["mail", "Письмо"], ["tg", "Telegram"], ["phone", "Телефон"]].map(([k, n]) => '<button type="button" data-pv="' + k + '" aria-pressed="' + (pv === k) + '">' + n + "</button>").join("") + "</div>";
    const msg = pv === "mail" ? "<b>Тема:</b> Анкета за " + esc(M.month) + " — 2 минуты<br><br>Здравствуйте! Раз в месяц мы спрашиваем, как идёт стажировка. Ваши ответы видит только HR.<br><br><u>Заполнить анкету →</u>" : pv === "tg" ? "🤖 Пульс адаптации: пора заполнить анкету за " + esc(M.month) + ". Ответьте прямо здесь — 6 вопросов, 2 минуты." : "Пульс адаптации · анкета за " + esc(M.month) + ". Откройте ссылку: оценки кнопками 1–10 и комментарий по желанию.";
    h += '<div style="background:var(--soft-3);border:1px solid var(--line);border-radius:14px;padding:14px" class="small">' + msg + "</div></section></div>";
    return h;
  }
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
    box.querySelectorAll("[data-pv]").forEach((b) => b.addEventListener("click", () => { pv = b.dataset.pv; render(); }));
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
