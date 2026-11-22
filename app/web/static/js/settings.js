// Настройки (HR): интеграции, состояние LLM, правила оповещений с превью, пороги и веса, доступ.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page");
  let S = null;
  const KEYS = [["level_threshold", "Уровень: порог |Δ| по личной шкале", 0.05], ["growth_slope", "Растущий разрыв: наклон |Δ| в месяц", 0.01], ["lag_drop", "Запаздывание: снижение оценки", 0.05], ["words_score", "Слова ≠ цифры: оценка не ниже", 0.05], ["words_anxiety", "Слова ≠ цифры: тревожность не ниже", 0.05], ["program_share", "Сигнал программы: доля пар", 0.1], ["red_zone", "Красная зона |Δ|", 0.05], ["w_level", "Вес: уровень разрыва", 5], ["w_growth", "Вес: рост разрыва", 10], ["w_drop", "Вес: падение оценок", 5], ["w_low", "Вес: низкий общий уровень", 10], ["w_words", "Вес: слова ≠ цифры", 5], ["w_lag", "Вес: месяц запаздывания", 1], ["w_missing", "Вес: нет анкеты", 1]];
  const RULES = [["health", "Индекс здоровья пары ниже порога", 5, "Telegram + почта HR"], ["delta", "Расхождение |Δ| выше порога", 0.05, "Telegram + почта HR"], ["days", "Анкета не сдана дольше, дней", 1, "напоминание участнику, затем HR"], ["talk", "Запрос «Хочу поговорить с HR»", 0, "сразу: Telegram + почта HR"]];
  const fmt = (v) => (Number.isInteger(v) ? String(v) : Number(v).toFixed(2));
  const sw = (on, attrs) => '<button type="button" role="switch" aria-checked="' + on + '" ' + attrs + ' style="width:44px;height:26px;border-radius:999px;border:0;background:' + (on ? "#0A7CD6" : "#C9CFDB") + ';position:relative;cursor:pointer;flex-shrink:0"><span style="position:absolute;top:3px;left:' + (on ? 21 : 3) + 'px;width:20px;height:20px;border-radius:50%;background:#fff"></span></button>';

  async function load() { S = await api("GET", "/api/settings"); render(); }
  function render() {
    const L = S.llm;
    let h = '<section class="hero"><div class="sphere" aria-hidden="true"></div><p class="tagline">Настройки</p><h1>Интеграции, оповещения, доступ</h1><p class="sub">Пороги и веса — стартовые: согласуем с HR и калибруем на исторических данных. Любое изменение сразу пересчитывает сигналы.</p></section>';
    h += '<div class="widgets"><section class="card col" style="flex:1 1 360px"><p class="eyebrow">Интеграции</p>';
    h += [["Яндекс Формы", "Ответы анкеты по API и вебхуку", S.forms.yandex.enabled], ["Google Forms", "Альтернатива Яндекс Формам", S.forms.google.enabled], ["Рабочая почта", "Приглашения, напоминания, сводки", false], ["Telegram-бот", "Напоминания и ответы в чате", false]].map(([n, d, on]) => '<div class="list-row"><span class="grow small"><b>' + n + '</b><br><span class="xs muted">' + d + '</span></span><span class="chip ' + (on ? "ok" : "") + '">' + (on ? "подключено" : "не подключено") + "</span></div>").join("");
    h += '<p class="xs muted">Подключение — токены в .env (docs/FORMS.md). Без SMTP ссылки приглашений показываются HR на экране.</p></section>';
    h += '<section class="card col" style="flex:1 1 360px"><p class="eyebrow">ИИ-модель</p><p class="small"><b>' + (L.ok ? "Модель отвечает" + (L.latency ? " · " + L.latency + " с" : "") : L.ok === false ? "Модель недоступна — работают запасные правила" : "Работает локально, данные не покидают сервер") + "</b></p>";
    h += [["Где работает", "на сервере компании (Ollama)"], ["Модель", L.model], ["Что делает", "разбор комментариев, темы вопросов, объяснение сигналов, повестка, договорённости"], ["Если недоступна", "запасные правила — продукт продолжает работать"]].map(([k, v]) => '<div class="row between small" style="border-bottom:1px solid #EEF0F4;padding:6px 0"><span class="muted">' + k + "</span><span>" + esc(v) + "</span></div>").join("");
    if (L.error) h += '<p class="xs" style="color:#962020">' + esc(L.error) + "</p>";
    h += '<button type="button" class="btn small" id="llm-check" style="align-self:flex-start">Проверить модель</button></section></div>';
    h += '<section class="card col"><p class="eyebrow">Правила оповещений · превью «сработало бы сейчас»</p>';
    RULES.forEach(([k, n, step, ch]) => {
      const r = S.rules[k], hits = S.preview[k] || [];
      h += '<div class="row" style="border-bottom:1px solid #EEF0F4;padding:10px 0;gap:12px">' + sw(!!r.on, 'data-rule-on="' + k + '" aria-label="' + n + '"') + '<span class="grow"><b class="small">' + n + '</b><br><span class="xs muted">' + ch + " · " + (k === "talk" ? "срабатывает в момент запроса" : hits.length ? "сейчас сработало бы: " + esc(hits.join(", ")) : "сейчас не сработало бы ни разу") + "</span></span>";
      if (k !== "talk") h += '<span class="row nowrap" style="gap:6px"><button type="button" class="icon-btn" data-rule="' + k + '" data-d="-' + step + '" aria-label="Уменьшить">−</button><b class="head" style="min-width:52px;text-align:center">' + fmt(r.value) + '</b><button type="button" class="icon-btn" data-rule="' + k + '" data-d="' + step + '" aria-label="Увеличить">+</button></span>';
      h += "</div>";
    });
    h += "</section>";
    h += '<section class="card col"><div class="row between"><p class="eyebrow">Пороги сигналов и веса индекса</p><button type="button" class="btn small" id="reset">Вернуть стартовые</button></div><div class="grid-auto" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">';
    KEYS.forEach(([k, n, step]) => { const v = S.analytics[k], d = S.defaults[k]; h += '<div class="row nowrap" style="border:1px solid #E3E6EC;border-radius:12px;padding:8px 10px;gap:8px"><span class="grow xs">' + n + (v !== d ? ' <span class="chip warn">изменено</span>' : "") + '</span><button type="button" class="icon-btn" style="width:36px;height:36px;min-width:36px" data-an="' + k + '" data-d="-' + step + '" aria-label="Уменьшить">−</button><b style="min-width:44px;text-align:center">' + fmt(v) + '</b><button type="button" class="icon-btn" style="width:36px;height:36px;min-width:36px" data-an="' + k + '" data-d="' + step + '" aria-label="Увеличить">+</button></div>'; });
    h += "</div></section>";
    h += '<section class="card col"><p class="eyebrow">Роли и доступ</p>' + S.users.map((u) => '<div class="list-row small"><span class="grow"><b>' + esc(u.email) + "</b> · " + esc(u.name) + '</span><span class="chip info">' + (u.role === "hr" ? "HR-партнёр" : "Руководитель") + "</span></div>").join("");
    h += '<div class="row"><label class="sr-only" for="nu">Почта</label><input class="input small" id="nu" type="email" placeholder="lead2@pulse.demo" style="flex:1 1 220px;width:auto"><select class="input small" id="nu-role" style="width:auto"><option value="lead">Руководитель</option><option value="hr">HR-партнёр</option></select><button type="button" class="btn primary small" id="nu-add">Выдать доступ</button></div><p class="xs muted">Стажёров и наставников приглашайте в разделе «Программа → Участники». Права проверяются на сервере для каждого действия.</p></section>';
    box.innerHTML = h; bind();
  }
  function bind() {
    const $ = (s) => box.querySelector(s);
    $("#llm-check").addEventListener("click", async (e) => { e.target.disabled = true; e.target.textContent = "Проверяем…"; const r = await api("GET", "/api/llm/status?check=true"); S.llm = r; toast(r.ok ? "Проверка пройдена: модель отвечает" : "Модель недоступна, работают запасные правила"); render(); });
    box.querySelectorAll("[data-rule-on]").forEach((b) => b.addEventListener("click", async () => { const k = b.dataset.ruleOn; S = await api("PUT", "/api/settings", { rules: { [k]: { ...S.rules[k], on: !S.rules[k].on } } }); render(); }));
    box.querySelectorAll("[data-rule]").forEach((b) => b.addEventListener("click", async () => { const k = b.dataset.rule, v = Math.max(0, Math.round((S.rules[k].value + Number(b.dataset.d)) * 100) / 100); S = await api("PUT", "/api/settings", { rules: { [k]: { ...S.rules[k], value: v } } }); render(); }));
    box.querySelectorAll("[data-an]").forEach((b) => b.addEventListener("click", async () => { const k = b.dataset.an, v = Math.max(0, Math.round((S.analytics[k] + Number(b.dataset.d)) * 100) / 100); S = await api("PUT", "/api/settings", { analytics: { [k]: v } }); toast("Сигналы пересчитаны с новым порогом"); render(); }));
    $("#reset").addEventListener("click", async () => { S = await api("POST", "/api/settings/reset"); toast("Стартовые пороги и веса восстановлены"); render(); });
    $("#nu-add").addEventListener("click", async () => { try { const r = await api("POST", "/api/auth/invites", { email: $("#nu").value, role: $("#nu-role").value }); toast("Доступ выдан: " + r.email + ". Ссылка: " + location.origin + r.link); } catch (e) { toast(e.message); } });
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
