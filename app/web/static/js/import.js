// Экран «Мы поняли так»: загрузка файлов, правка решений, подтверждение.
(function () {
  "use strict";
  const { api, esc, toast, conf } = window.Pulse;
  const $ = (id) => document.getElementById(id);
  const ROLE_NAMES = { id: "ID участника", link: "ID другой стороны", pair: "ID пары", period: "Месяц анкеты", score: "Оценка", comment: "Комментарий", department: "Подразделение", email: "Почта", timestamp: "Отметка времени", skip: "Не учитывать" };
  const SIDE = { intern: "Стажёры", mentor: "Наставники" };
  const TOPICS = { tasks: "Понимание задач", auto: "Самостоятельность", support: "Поддержка", load: "Нагрузка", feedback: "Обратная связь", growth: "Перспективы" };
  let files = [], job = null, saving = null;

  function setStep(n) { document.querySelectorAll("#steps .step").forEach((s) => s.classList.toggle("on", Number(s.dataset.step) <= n)); }

  function pick(list) {
    files = Array.from(list);
    $("picked").innerHTML = files.map((f) => "• " + esc(f.name) + " · " + Math.ceil(f.size / 1024) + " КБ").join("<br>");
    $("analyze-btn").disabled = files.length === 0;
  }
  const drop = $("drop");
  $("file-input").addEventListener("change", (e) => pick(e.target.files));
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => pick(e.dataTransfer.files));

  $("analyze-btn").addEventListener("click", async () => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    $("err").hidden = true; $("busy").hidden = false; $("analyze-btn").disabled = true;
    try {
      job = await api("POST", "/api/import/upload", fd);
      render();
      setStep(1);
    } catch (x) { $("err").textContent = x.message; $("err").hidden = false; }
    $("busy").hidden = true; $("analyze-btn").disabled = false;
  });

  function opt(value, label, cur) { return '<option value="' + esc(value) + '"' + (String(value) === String(cur) ? " selected" : "") + ">" + esc(label) + "</option>"; }

  function render() {
    const s = job.schema, box = $("stage-review");
    box.hidden = false;
    const asks = s.asks || [];
    const sm = s.summary || {};
    let h = "";
    h += '<div class="card col">';
    h += '<div class="row between"><p class="eyebrow">Мы поняли так</p>' + (s.profile_applied ? '<span class="chip ok">Формат знаком — применён сохранённый профиль</span>' : "") + "</div>";
    h += '<p class="head" style="font-size:22px">' + (sm.pairs || 0) + " пар, " + ((sm.responses || {}).intern || 0) + " анкет стажёров и " + ((sm.responses || {}).mentor || 0) + " анкет наставников, месяцы " + esc((sm.periods || []).join(", ")) + "</p>";
    h += asks.length
      ? '<div class="issue open"><b>Нужен ваш ответ: ' + asks.length + "</b><span>" + asks.map((a) => esc(a.where) + " — " + esc(a.what)).join("; ") + "</span></div>"
      : '<div class="issue done"><b>Вопросов нет.</b><span>Все решения приняты уверенно. Проверьте и подтвердите.</span></div>';
    h += '<p class="small muted">Цвет уверенности: <span class="conf hi">≥ 0.85</span> <span class="conf mid">0.60–0.85 — проверить</span> <span class="conf lo">&lt; 0.60 — нужен ответ</span></p>';
    h += "</div>";

    h += '<div class="card col"><p class="eyebrow">Файлы</p>';
    s.files.forEach((f) => {
      const what = f.kind === "structure" ? "структура анкет: " + esc((f.found || []).join(", ") || "вопросы не найдены") : f.kind === "responses" ? "ответы · таблиц: " + (f.tables || 0) : "не распознан";
      h += '<div class="list-row"><span class="tag">' + (f.kind === "structure" ? "Word" : f.kind === "responses" ? "Таблица" : "?") + '</span><span class="grow"><b class="small">' + esc(f.name) + '</b><br><span class="xs muted">' + what + "</span></span></div>";
    });
    h += "</div>";

    s.tables.forEach((t, ti) => {
      const qs = s.questionnaires[t.side].questions;
      h += '<div class="card col"><div class="row between"><div><p class="eyebrow">Таблица · ' + esc(t.file) + (t.sheet && t.sheet !== "csv" ? " · лист «" + esc(t.sheet) + "»" : "") + '</p><p class="xs muted">' + t.rows + " строк · формат: " + (t.format === "long" ? "длинный (строка = ответ), развернули в анкеты" : "широкий (строка = анкета)") + "</p></div>";
      h += '<div class="row"><label class="small" for="side-' + ti + '"><b>Сторона</b></label><select class="input small" style="width:auto" id="side-' + ti + '" data-t="' + ti + '" data-k="side">' + opt("intern", "Стажёры", t.side) + opt("mentor", "Наставники", t.side) + "</select>" + conf(t.side_conf) + "</div></div>";
      h += '<p class="xs muted">Почему: ' + esc((t.side_why || []).join(", ")) + "</p>";
      h += '<div class="scroll-x"><table class="tbl"><thead><tr><th>Колонка</th><th>Что это</th><th>Вопрос анкеты</th><th>Уверенность</th></tr></thead><tbody>';
      t.columns.forEach((c, ci) => {
        let roleSel = '<select class="input small" data-t="' + ti + '" data-c="' + ci + '" data-k="role" aria-label="Назначение колонки ' + esc(c.name) + '">';
        Object.keys(ROLE_NAMES).forEach((r) => (roleSel += opt(r, ROLE_NAMES[r], c.role)));
        roleSel += "</select>";
        let qSel = "—";
        if (c.role === "score" || c.role === "comment") {
          qSel = '<select class="input small" data-t="' + ti + '" data-c="' + ci + '" data-k="question" aria-label="Вопрос для колонки ' + esc(c.name) + '">';
          qs.filter((q) => (c.role === "comment") === (q.qtype === "text")).forEach((q) => (qSel += opt(q.key, q.key + ". " + q.text.slice(0, 70), c.question)));
          qSel += opt("", "— новый вопрос —", c.question || "x") + "</select>";
        }
        const cc = c.role === "score" ? Math.min(c.conf, c.match_conf || c.conf) : c.conf;
        h += "<tr><td><b class='small'>" + esc(c.name) + "</b></td><td>" + roleSel + "</td><td style='min-width:240px'>" + qSel + "</td><td>" + (c.role === "skip" ? "" : conf(cc)) + "</td></tr>";
      });
      h += "</tbody></table></div></div>";
    });

    ["intern", "mentor"].forEach((side) => {
      const q = s.questionnaires[side];
      const other = s.questionnaires[side === "intern" ? "mentor" : "intern"].questions.filter((x) => x.qtype !== "text");
      h += '<div class="card col"><p class="eyebrow">Анкета: ' + SIDE[side].toLowerCase() + " · " + (q.source === "word" ? "из Word" : "по заголовкам таблицы") + '</p><div class="scroll-x"><table class="tbl"><thead><tr><th>Вопрос</th><th>Шкала</th><th>Тема</th><th>Зеркальный вопрос</th><th>Уверенность</th></tr></thead><tbody>';
      q.questions.forEach((x, qi) => {
        const scale = x.qtype === "text" ? "текст" : x.labels && x.labels.length > 2 ? "словесная" : x.min != null ? x.min + "–" + x.max : "?";
        let tSel = "—", mSel = "—";
        if (x.qtype !== "text") {
          tSel = '<select class="input small" data-side="' + side + '" data-q="' + qi + '" data-k="topic" aria-label="Тема вопроса">';
          Object.keys(TOPICS).forEach((k) => (tSel += opt(k, TOPICS[k], x.topic)));
          tSel += "</select>";
          mSel = '<select class="input small" data-side="' + side + '" data-q="' + qi + '" data-k="mirror" aria-label="Зеркальный вопрос">' + opt("", "— нет —", x.mirror || "");
          other.forEach((o) => (mSel += opt(o.key, o.key + ". " + o.text.slice(0, 50), x.mirror)));
          mSel += "</select>";
        }
        const inv = x.inverse ? ' <span class="chip warn" title="Высокий балл — плохо, значение переворачивается">инверсный</span>' : "";
        h += "<tr><td class='small'><b>" + esc(x.key) + "</b>. " + esc(x.text) + inv + "</td><td class='small'>" + scale + "</td><td>" + tSel + "</td><td style='min-width:220px'>" + mSel + "</td><td>" + (x.qtype === "text" ? "" : conf(Math.min(x.topic_conf, x.mirror ? x.mirror_conf || 1 : 1))) + "</td></tr>";
      });
      h += "</tbody></table></div></div>";
    });

    h += '<div class="card col"><p class="eyebrow">Пары</p>';
    s.pairs.forEach((p, pi) => {
      h += '<div class="list-row"><span class="grow small"><b>' + esc(p.intern) + " ↔ " + esc(p.mentor) + '</b> <span class="muted">· ' + esc(p.how) + "</span></span>" + conf(p.conf) + ' <button type="button" class="btn small danger" data-unpair="' + pi + '">Разъединить</button></div>';
    });
    const lonely = (s.issues.find((i) => i.type === "unpaired") || { data: { items: [] } }).data.items;
    if (lonely.length) {
      const ints = lonely.filter((x) => !s.pairs.some((p) => p.intern === x)), all = lonely;
      h += '<div class="row"><span class="small"><b>Связать вручную:</b></span><select class="input small" style="width:auto" id="mi">' + all.map((x) => opt(x, x, "")).join("") + '</select><span>↔</span><select class="input small" style="width:auto" id="mm">' + all.map((x) => opt(x, x, "")).join("") + '</select><button type="button" class="btn small" id="add-pair">Добавить пару</button></div>';
      void ints;
    }
    h += "</div>";

    h += '<div class="card col"><p class="eyebrow">Проверка качества</p>';
    if (!s.issues.length) h += '<div class="issue done"><b>Проблем не найдено.</b></div>';
    s.issues.forEach((i, ii) => {
      h += '<div class="issue ' + (i.apply ? "done" : "open") + '"><span class="grow"><b>' + esc(i.title) + "</b><br><span class='small'>" + esc(i.text) + "</span></span>" +
        '<button type="button" class="btn small" data-issue="' + ii + '" aria-pressed="' + (i.apply ? "true" : "false") + '">' + (i.apply ? "✓ " + esc(i.fix_label) : esc(i.fix_label)) + "</button></div>";
    });
    h += "</div>";

    h += '<div class="card row between"><span class="small muted">После подтверждения данные запишутся в базу, сигналы и индекс пересчитаются, дашборд обновится. Сопоставление сохранится: следующая загрузка того же формата пройдёт без вопросов.</span><button type="button" class="btn primary" id="confirm-btn">Подтвердить и пересчитать</button></div>';
    box.innerHTML = h;
    bind();
  }

  function bind() {
    const box = $("stage-review"), s = job.schema;
    box.querySelectorAll("select[data-k]").forEach((el) => el.addEventListener("change", () => {
      const k = el.dataset.k;
      if (el.dataset.t !== undefined && k === "side") s.tables[+el.dataset.t].side = el.value, (s.tables[+el.dataset.t].side_conf = 1);
      else if (el.dataset.c !== undefined) {
        const c = s.tables[+el.dataset.t].columns[+el.dataset.c];
        c[k] = el.value || null; c.conf = 1; if (k === "question") c.match_conf = 1;
        if (k === "role" && !["score", "comment"].includes(el.value)) c.question = null;
      } else if (el.dataset.side) {
        const qs = s.questionnaires[el.dataset.side].questions, q = qs[+el.dataset.q];
        if (k === "topic") { q.topic = el.value; q.topic_conf = 1; }
        if (k === "mirror") {
          const otherSide = el.dataset.side === "intern" ? "mentor" : "intern", oq = s.questionnaires[otherSide].questions;
          oq.forEach((o) => { if (o.mirror === q.key) o.mirror = null; });
          q.mirror = el.value || null; q.mirror_conf = 1;
          const t = oq.find((o) => o.key === el.value); if (t) { t.mirror = q.key; t.mirror_conf = 1; }
        }
      }
      save();
    }));
    box.querySelectorAll("[data-issue]").forEach((b) => b.addEventListener("click", () => { const i = s.issues[+b.dataset.issue]; i.apply = !i.apply; save(); }));
    box.querySelectorAll("[data-unpair]").forEach((b) => b.addEventListener("click", () => { s.pairs.splice(+b.dataset.unpair, 1); save(); }));
    const ap = $("add-pair");
    if (ap) ap.addEventListener("click", () => {
      const a = $("mi").value, b = $("mm").value;
      if (a === b) { toast("Выберите двух разных участников"); return; }
      s.pairs.push({ intern: a, mentor: b, conf: 1, how: "связано вручную", manual: true }); save();
    });
    $("confirm-btn").addEventListener("click", confirm);
  }

  async function save() {
    clearTimeout(saving);
    saving = setTimeout(async () => {
      try { job = await api("PUT", "/api/import/" + job.id + "/schema", job.schema); render(); setStep(2); }
      catch (x) { toast(x.message); }
    }, 150);
  }

  async function confirm() {
    const btn = $("confirm-btn"); btn.disabled = true; btn.textContent = "Записываем…";
    try {
      const r = await api("POST", "/api/import/" + job.id + "/confirm");
      setStep(3);
      $("stage-review").innerHTML = '<div class="card col"><p class="eyebrow">Готово</p><p class="head" style="font-size:22px">Записано анкет: ' + r.responses + ", новых пар: " + r.pairs_new + '</p><p class="small muted">Сигналы и индекс здоровья пересчитаны. Профиль сопоставления сохранён.</p><div class="row"><a class="btn primary" href="/dashboard">Открыть дашборд →</a><a class="btn" href="/import">Загрузить ещё</a></div></div>';
      toast("Данные загружены, сигналы пересчитаны");
    } catch (x) { toast(x.message); btn.disabled = false; btn.textContent = "Подтвердить и пересчитать"; }
  }
})();
