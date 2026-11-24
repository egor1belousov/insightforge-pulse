// Настройки (HR): интеграции, состояние LLM, правила оповещений с превью, пороги и веса, доступ.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page");
  let S = null;
  const KEYS = [["level_threshold", "Уровень: порог |Δ| по личной шкале", 0.05], ["growth_slope", "Растущий разрыв: наклон |Δ| в месяц", 0.01], ["lag_drop", "Запаздывание: снижение оценки", 0.05], ["words_score", "Слова ≠ цифры: оценка не ниже", 0.05], ["words_anxiety", "Слова ≠ цифры: тревожность не ниже", 0.05], ["program_share", "Сигнал программы: доля пар", 0.1], ["red_zone", "Красная зона |Δ|", 0.05], ["w_level", "Вес: уровень разрыва", 5], ["w_growth", "Вес: рост разрыва", 10], ["w_drop", "Вес: падение оценок", 5], ["w_low", "Вес: низкий общий уровень", 10], ["w_words", "Вес: слова ≠ цифры", 5], ["w_lag", "Вес: месяц запаздывания", 1], ["w_missing", "Вес: нет анкеты", 1]];
  const RULES = [["health", "Индекс здоровья пары ниже порога", 5, "Telegram + почта HR"], ["delta", "Расхождение |Δ| выше порога", 0.05, "Telegram + почта HR"], ["days", "Анкета не сдана дольше, дней", 1, "напоминание участнику, затем HR"], ["talk", "Запрос «Хочу поговорить с HR»", 0, "сразу: Telegram + почта HR"]];
  const fmt = (v) => (Number.isInteger(v) ? String(v) : Number(v).toFixed(2));
  const sw = (on, attrs) => '<button type="button" role="switch" aria-checked="' + on + '" ' + attrs + ' style="width:44px;height:26px;border-radius:999px;border:0;background:' + (on ? "var(--accent)" : "var(--line-3)") + ';position:relative;cursor:pointer;flex-shrink:0"><span style="position:absolute;top:3px;left:' + (on ? 21 : 3) + 'px;width:20px;height:20px;border-radius:50%;background:var(--card)"></span></button>';

  let I = null;
  async function load() { [S, I] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/integrations")]); render(); refreshLlm(); const t = location.hash.match(/^#int-(\w+)/); if (t && I[t[1]]) openInt(t[1]); }
  const ICONS = { yandex: "Я", google: "G", smtp: "@", telegram: "✈" };
  function intCard() {
    let h = '<p class="eyebrow">Интеграции</p>';
    h += Object.values(I).map((x) => '<div class="int-row" id="int-' + x.kind + '"><span class="int-ic">' + ICONS[x.kind] + '</span><span class="grow col" style="gap:3px"><b class="small">' + esc(x.title) + '</b><span class="xs muted">' + esc(x.connected && x.info ? x.info : x.desc) + '</span></span><span class="chip ' + (x.connected ? "ok" : "") + '">' + (x.connected ? "подключено" : "не подключено") + '</span><button type="button" class="btn small" data-int="' + x.kind + '">' + (x.connected ? "Настроить" : "Подключить") + "</button></div>").join("");
    return h + '<p class="xs muted">Токены хранятся на сервере компании и не показываются целиком. Каждое подключение проверяется настоящим запросом к сервису.</p>';
  }
  function openInt(kind) {
    const x = I[kind];
    const fields = x.fields.map((f) => '<div class="field"><label for="if-' + f.key + '">' + esc(f.label) + '</label>' + (f.key === "credentials" ? '<textarea class="input" id="if-' + f.key + '" rows="4" placeholder="' + esc(f.value || "{ \"client_id\": … }") + '"></textarea>' : '<input class="input" id="if-' + f.key + '" ' + (f.secret ? 'type="password" autocomplete="off" placeholder="' + esc(f.value || "") + '"' : 'value="' + esc(f.value || "") + '"') + ">") + '<span class="xs muted">' + esc(f.help) + "</span></div>").join("");
    let extra = "";
    if (kind === "yandex" && x.webhook) extra += '<div class="col" style="gap:6px;background:var(--soft-3);border-radius:12px;padding:12px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">ВЕБХУК ДЛЯ ФОРМЫ</span><code class="formula" style="word-break:break-all">' + esc(x.webhook) + '</code><span class="xs muted">В настройках формы: Интеграции → HTTP-запрос → POST на этот адрес, тело — JSON с ответами. Без вебхука ответы забираются по API каждые 15 секунд.</span><div class="row" style="gap:8px"><button type="button" class="btn small" data-copy-hook>Скопировать адрес</button><button type="button" class="btn small" data-sync="yandex">Загрузить ответы сейчас</button></div></div>';
    if (kind === "google" && x.connected) extra += '<button type="button" class="btn small" data-sync="google" style="align-self:flex-start">Загрузить ответы сейчас</button>';
    if (kind === "telegram" && x.connected) extra += '<div class="col" style="gap:6px;background:var(--soft-3);border-radius:12px;padding:12px"><span class="small"><b>Как подключаются участники.</b> У каждого стажёра и наставника в разделе «Моя стажировка» есть кнопка «Подключить Telegram» — личная ссылка на бота ' + esc(x.info || "") + '. После этого напоминания приходят в чат, а анкету можно заполнить кнопками прямо там.</span></div>';
    const logh = x.log.length ? '<div class="col" style="gap:4px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">ЖУРНАЛ</span>' + x.log.map((e) => '<span class="xs" style="color:' + (e.ok ? "var(--muted)" : "var(--both-fg)") + '">' + esc(e.at.replace("T", " ").slice(5, 16)) + " · " + esc(e.text) + "</span>").join("") + "</div>" : "";
    const m = Pulse.modal('<div class="modal" role="dialog" aria-modal="true" aria-labelledby="int-t"><div class="row between nowrap"><div class="row nowrap" style="gap:12px"><span class="int-ic">' + ICONS[kind] + '</span><div><h2 class="head" id="int-t" style="font-size:20px">' + esc(x.title) + '</h2><p class="xs muted">' + esc(x.desc) + '</p></div></div><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div>' + (x.connected ? '<div class="form-ok">Подключено' + (x.info ? ": " + esc(x.info) : "") + (x.source === "env" ? " (из .env сервера)" : "") + "</div>" : "") + fields + '<div id="int-err" class="form-error" hidden></div><div class="row" style="gap:8px"><button type="button" class="btn primary" id="int-save">' + (x.connected ? "Проверить и сохранить" : "Проверить и подключить") + "</button>" + (x.connected && x.source !== "env" ? '<button type="button" class="btn danger" id="int-off">Отключить</button>' : "") + "</div>" + extra + logh + "</div>");
    const q = (sel) => m.back.querySelector(sel);
    q("#int-save").addEventListener("click", async () => {
      const b = q("#int-save"), data = {};
      x.fields.forEach((f) => { data[f.key] = q("#if-" + f.key).value; });
      b.disabled = true; b.textContent = "Проверяем…"; q("#int-err").hidden = true;
      try { I[kind] = await api("POST", "/api/integrations/" + kind, data); toast(x.title + ": подключено — " + (I[kind].info || "")); m.close(); render(); }
      catch (e) { q("#int-err").textContent = e.message; q("#int-err").hidden = false; b.disabled = false; b.textContent = "Проверить и подключить"; }
    });
    const off = q("#int-off");
    if (off) off.addEventListener("click", async () => { I[kind] = await api("DELETE", "/api/integrations/" + kind); toast(x.title + " отключено"); m.close(); render(); });
    const hook = q("[data-copy-hook]");
    if (hook) hook.addEventListener("click", async () => { try { await navigator.clipboard.writeText(x.webhook); toast("Адрес вебхука скопирован"); } catch (e) { toast(x.webhook); } });
    m.back.querySelectorAll("[data-sync]").forEach((b) => b.addEventListener("click", async () => { b.disabled = true; try { const r = await api("POST", "/api/integrations/" + b.dataset.sync + "/sync"); toast(r.message); } catch (e) { toast(e.message); } b.disabled = false; }));
  }
  // Сведения о модели берём у Ollama при открытии экрана и раз в 30 секунд
  async function refreshLlm() {
    try { S.llm = await api("GET", "/api/llm/status?check=true"); } catch (e) { return; }
    const c = document.getElementById("llm-card");
    if (c) { c.innerHTML = llmCard(S.llm); bindLlm(); }
  }
  setInterval(() => { if (!document.hidden) refreshLlm(); }, 30000);
  function llmCard(L) {
    const I = L.info || {}, st = L.stats || {};
    const head = L.ok ? "Модель отвечает" + (L.latency != null ? " · " + L.latency + " с" : "") : L.ok === false ? "Модель недоступна — работают запасные правила" : "Проверяем модель…";
    const dot = L.ok ? "var(--ok)" : L.ok === false ? "var(--both)" : "var(--line-3)";
    const where = /ollama:|localhost|127\.0\.0\.1/.test(L.url || "") ? "локально, данные не покидают сервер" : L.url;
    const rows = [
      ["Модель", I.name || L.model],
      ["Размер", I.params ? I.params + (I.quant ? " · " + I.quant : "") + (I.size_gb ? " · " + I.size_gb + " ГБ" : "") : "—"],
      ["Видеопамять", I.loaded ? "загружена" + (I.vram_gb ? ", " + I.vram_gb + " ГБ" : "") : L.ok ? "выгружена, первый ответ дольше" : "—"],
      ["Где работает", "Ollama" + (I.version ? " " + I.version : "") + " · " + where],
      ["Запросов с запуска", st.calls != null ? st.calls + (st.cached ? " · из памяти " + st.cached : "") + (st.avg_seconds ? " · в среднем " + st.avg_seconds + " с" : "") : "—"],
      ["Если недоступна", "запасные правила — продукт продолжает работать"],
    ];
    let h = '<div class="row between"><p class="eyebrow">ИИ-модель</p><span class="xs muted" id="llm-upd">' + (L.ok != null ? "обновлено " + new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "") + "</span></div>";
    h += '<p class="small row nowrap" style="gap:8px"><span style="width:10px;height:10px;border-radius:50%;background:' + dot + ';flex-shrink:0"></span><b>' + head + "</b></p>";
    h += rows.map(([k, v]) => '<div class="row between small" style="border-bottom:1px solid var(--soft);padding:6px 0;gap:12px"><span class="muted">' + k + '</span><span style="text-align:right">' + esc(String(v)) + "</span></div>").join("");
    if (L.error) h += '<p class="xs" style="color:var(--both-fg)">' + esc(L.error) + "</p>";
    h += '<button type="button" class="btn small" id="llm-check" style="align-self:flex-start">Проверить сейчас</button>';
    return h;
  }
  function bindLlm() {
    const b = document.getElementById("llm-check");
    if (b) b.addEventListener("click", async () => { b.disabled = true; b.textContent = "Проверяем…"; await refreshLlm(); toast(S.llm.ok ? "Модель отвечает" : "Модель недоступна, работают запасные правила"); });
  }
  function render() {
    const L = S.llm;
    let h = '<section class="hero"><div class="sphere orb" data-orb="mesh" data-size="560" aria-hidden="true"></div><p class="tagline">Настройки</p><h1>Интеграции, оповещения, доступ</h1><p class="sub">Пороги и веса — стартовые: согласуем с HR и калибруем на исторических данных. Любое изменение сразу пересчитывает сигналы.</p></section>';
    h += '<div class="widgets"><section class="card col" style="flex:1 1 360px">' + intCard() + "</section>";
    h += '<section class="card col" style="flex:1 1 360px" id="llm-card">' + llmCard(L) + "</section></div>";
    h += '<section class="card col"><p class="eyebrow">Правила оповещений · превью «сработало бы сейчас»</p>';
    RULES.forEach(([k, n, step, ch]) => {
      const r = S.rules[k], hits = S.preview[k] || [];
      h += '<div class="row" style="border-bottom:1px solid var(--soft);padding:10px 0;gap:12px">' + sw(!!r.on, 'data-rule-on="' + k + '" aria-label="' + n + '"') + '<span class="grow"><b class="small">' + n + '</b><br><span class="xs muted">' + ch + " · " + (k === "talk" ? "срабатывает в момент запроса" : hits.length ? "сейчас сработало бы: " + esc(hits.join(", ")) : "сейчас не сработало бы ни разу") + "</span></span>";
      if (k !== "talk") h += '<span class="row nowrap" style="gap:6px"><button type="button" class="icon-btn" data-rule="' + k + '" data-d="-' + step + '" aria-label="Уменьшить">−</button><b class="head" style="min-width:52px;text-align:center">' + fmt(r.value) + '</b><button type="button" class="icon-btn" data-rule="' + k + '" data-d="' + step + '" aria-label="Увеличить">+</button></span>';
      h += "</div>";
    });
    h += "</section>";
    h += '<section class="card col"><div class="row between"><p class="eyebrow">Пороги сигналов и веса индекса</p><button type="button" class="btn small" id="reset">Вернуть стартовые</button></div><div class="grid-auto" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">';
    KEYS.forEach(([k, n, step]) => { const v = S.analytics[k], d = S.defaults[k]; h += '<div class="row nowrap" style="border:1px solid var(--line);border-radius:12px;padding:8px 10px;gap:8px"><span class="grow xs">' + n + (v !== d ? ' <span class="chip warn">изменено</span>' : "") + '</span><button type="button" class="icon-btn" style="width:36px;height:36px;min-width:36px" data-an="' + k + '" data-d="-' + step + '" aria-label="Уменьшить">−</button><b style="min-width:44px;text-align:center">' + fmt(v) + '</b><button type="button" class="icon-btn" style="width:36px;height:36px;min-width:36px" data-an="' + k + '" data-d="' + step + '" aria-label="Увеличить">+</button></div>'; });
    h += "</div></section>";
    h += '<section class="card col"><p class="eyebrow">Роли и доступ</p>' + S.users.map((u) => '<div class="list-row small"><span class="grow"><b>' + esc(u.email) + "</b> · " + esc(u.name) + '</span><span class="chip info">' + (u.role === "hr" ? "HR-партнёр" : "Руководитель") + "</span></div>").join("");
    h += '<div class="row"><label class="sr-only" for="nu">Почта</label><input class="input small" id="nu" type="email" placeholder="lead2@pulse.demo" style="flex:1 1 220px;width:auto"><select class="input small" id="nu-role" style="width:auto"><option value="lead">Руководитель</option><option value="hr">HR-партнёр</option></select><button type="button" class="btn primary small" id="nu-add">Выдать доступ</button></div><p class="xs muted">Стажёров и наставников приглашайте в разделе «Программа → Участники». Права проверяются на сервере для каждого действия.</p></section>';
    box.innerHTML = h; bind();
  }
  function bind() {
    const $ = (s) => box.querySelector(s);
    bindLlm();
    box.querySelectorAll("[data-int]").forEach((b) => b.addEventListener("click", () => openInt(b.dataset.int)));
    box.querySelectorAll("[data-rule-on]").forEach((b) => b.addEventListener("click", async () => { const k = b.dataset.ruleOn; S = await api("PUT", "/api/settings", { rules: { [k]: { ...S.rules[k], on: !S.rules[k].on } } }); render(); }));
    box.querySelectorAll("[data-rule]").forEach((b) => b.addEventListener("click", async () => { const k = b.dataset.rule, v = Math.max(0, Math.round((S.rules[k].value + Number(b.dataset.d)) * 100) / 100); S = await api("PUT", "/api/settings", { rules: { [k]: { ...S.rules[k], value: v } } }); render(); }));
    box.querySelectorAll("[data-an]").forEach((b) => b.addEventListener("click", async () => { const k = b.dataset.an, v = Math.max(0, Math.round((S.analytics[k] + Number(b.dataset.d)) * 100) / 100); S = await api("PUT", "/api/settings", { analytics: { [k]: v } }); toast("Сигналы пересчитаны с новым порогом"); render(); }));
    $("#reset").addEventListener("click", async () => { S = await api("POST", "/api/settings/reset"); toast("Стартовые пороги и веса восстановлены"); render(); });
    $("#nu-add").addEventListener("click", async () => { try { const r = await api("POST", "/api/auth/invites", { email: $("#nu").value, role: $("#nu-role").value }); toast("Доступ выдан: " + r.email + ". Ссылка: " + location.origin + r.link); } catch (e) { toast(e.message); } });
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
