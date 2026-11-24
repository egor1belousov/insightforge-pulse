// Обучение: курсы, тесты (генерация ИИ с проверкой HR), справочник по методике.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page"), role = document.getElementById("main").dataset.role;
  const isHr = role === "hr", staff = isHr || role === "lead";
  const TABS = isHr ? [["courses", "Курсы"], ["tests", "Тесты"], ["guide", "Справочник"]] : staff ? [["guide", "Справочник"], ["courses", "Курсы"]] : [["courses", role === "mentor" ? "Памятки" : "Курсы"], ["tests", "Тесты"]];
  const TOP = { tasks: "Понимание задач", auto: "Самостоятельность", support: "Поддержка", load: "Нагрузка", feedback: "Обратная связь", growth: "Перспективы" };
  let tab = new URLSearchParams(location.search).get("tab") || TABS[0][0], L = null, guideI = 0, draft = null, pairs = [], picked = {};

  async function load() { L = await api("GET", "/api/learn"); if (isHr && !pairs.length) pairs = (await api("GET", "/api/dashboard")).pairs; render(); }
  function render() {
    const title = staff ? "Обучение" : role === "mentor" ? "Памятки и тесты" : "Мои курсы и тесты";
    const sub = isHr ? "Загружайте курсы, создавайте тесты с ИИ, держите методику под рукой." : staff ? "Справочник по методике и каталог курсов программы." : "Назначено по результатам ваших анкет.";
    let h = '<section class="hero"><div class="sphere" aria-hidden="true"></div><p class="tagline">Обучение</p><h1>' + title + '</h1><p class="sub">' + sub + '</p></section><div class="seg" role="tablist">' + TABS.map(([k, n]) => '<button type="button" role="tab" data-tab="' + k + '" aria-selected="' + (tab === k) + '">' + n + "</button>").join("") + "</div>";
    h += tab === "courses" ? courses() : tab === "tests" ? tests() : guide();
    box.innerHTML = h; bind();
  }
  function courseCard(c) {
    let h = '<section class="card col" style="gap:8px"><div class="row" style="gap:6px"><span class="chip info">' + esc(c.kind) + '</span><span class="chip">' + esc(c.duration || "") + '</span><span class="xs muted">' + esc(TOP[c.topic] || "") + '</span></div><b>' + esc(c.title) + '</b><p class="small muted" style="line-height:1.5">' + esc(c.description) + "</p>";
    if (c.progress != null) h += '<div class="bar"><span style="width:' + c.progress + '%;background:#0A7CD6"></span></div><div class="row between"><span class="xs muted">Пройдено ' + c.progress + "%" + (c.reason ? " · " + esc(c.reason) : "") + '</span>' + (c.progress < 100 ? '<button type="button" class="btn small" data-done="' + c.id + '">Отметить пройденным</button>' : '<span class="chip ok">пройдено</span>') + "</div>";
    if (staff) h += '<p class="xs muted" style="border-top:1px solid #EEF0F4;padding-top:8px">Назначено: ' + (c.assigned.length ? esc(c.assigned.join(", ")) : "никому") + "</p>";
    if (isHr) h += '<div class="row" style="gap:6px"><button type="button" class="btn small" data-assign="' + c.id + '">Назначить паре</button><button type="button" class="btn small" data-gen="' + c.id + '">Создать тест · ИИ</button></div>';
    return h + "</section>";
  }
  function courses() {
    let h = "";
    if (isHr) h += '<section class="card col"><p class="eyebrow">Загрузить курс или памятку</p><div class="row"><input class="input small" id="c-title" placeholder="Название, например «Техника безопасности на объекте»" style="flex:2 1 260px;width:auto" aria-label="Название курса"><select class="input small" id="c-kind" style="width:auto" aria-label="Тип"><option>Курс</option><option>Памятка</option><option>Материал</option></select><select class="input small" id="c-topic" style="width:auto" aria-label="Тема">' + Object.entries(TOP).map(([k, n]) => '<option value="' + k + '">' + n + "</option>").join("") + '</select><select class="input small" id="c-aud" style="width:auto" aria-label="Для кого"><option value="intern">Стажёрам</option><option value="mentor">Наставникам</option></select></div><textarea class="input" id="c-text" rows="3" placeholder="Текст материала — по нему ИИ составит тест. Или приложите файл .docx / .txt"></textarea><div class="row"><label class="btn small" for="c-file" style="cursor:pointer">Приложить файл</label><input type="file" id="c-file" accept=".docx,.txt,.md" class="sr-only"><span class="xs muted" id="c-fname"></span><span class="grow"></span><button type="button" class="btn primary" id="c-save">Сохранить курс</button></div></section>';
    const list = L.courses;
    h += list.length ? '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">' + list.map(courseCard).join("") + "</div>" : '<p class="muted">' + (staff ? "Курсов пока нет." : "Вам пока ничего не назначено.") + "</p>";
    return h;
  }
  function testsStaff() {
    let h = "";
    if (draft) {
      h += '<section class="card col" style="border:1px solid #0A7CD6"><div class="row between"><p class="eyebrow">Черновик · ' + esc(draft.title) + " · " + (draft.generated_by === "llm" ? "составил ИИ" : "составлен правилами") + '</p><span class="xs muted">Проверьте вопросы: снимите галочку с неудачных</span></div>';
      draft.questions.forEach((q) => { h += '<label class="row nowrap top" style="gap:10px;border-bottom:1px solid #EEF0F4;padding:8px 0;cursor:pointer"><input type="checkbox" data-q="' + q.id + '"' + (q.enabled ? " checked" : "") + ' style="width:20px;height:20px;accent-color:#0A7CD6;margin-top:2px"><span class="grow"><b class="small">' + esc(q.text) + '</b><br><span class="xs muted">' + q.options.map((o, i) => (i === q.correct ? "✓ " : "") + esc(o)).join(" · ") + "</span></span></label>"; });
      h += '<div class="row"><button type="button" class="btn primary" id="t-pub">Опубликовать и назначить тем, кому назначен курс</button><button type="button" class="btn" id="t-cancel">Свернуть</button></div></section>';
    }
    h += '<section class="card col"><p class="eyebrow">Тесты</p>' + (L.tests.length ? L.tests.map((t) => '<div class="list-row"><span class="grow small"><b>' + esc(t.title) + "</b> · " + t.questions.filter((q) => q.enabled).length + ' вопр.<br><span class="xs muted">' + (t.status === "published" ? "опубликован" : "черновик") + " · " + (t.generated_by === "llm" ? "создан ИИ, проверен HR" : "создан правилами") + (t.assigned.length ? " · назначен: " + esc(t.assigned.join(", ")) : "") + (t.results.length ? " · результаты: " + t.results.map((r) => esc(r.who) + " " + Math.round(r.score * 100) + "%").join(", ") : "") + "</span></span>" + (isHr && t.status !== "published" ? '<button type="button" class="btn small" data-open="' + t.id + '">Проверить</button>' : "") + "</div>").join("") : '<p class="small muted">Тестов пока нет. Откройте «Курсы» и нажмите «Создать тест · ИИ».</p>') + "</section>";
    return h;
  }
  function testsSide() {
    if (!L.tests.length) return '<p class="muted">Тестов пока нет.</p>';
    return L.tests.map((t) => {
      let h = '<section class="card col"><div class="row between"><p class="eyebrow">' + esc(t.title) + "</p>" + (t.score != null ? '<span class="chip ' + (t.score >= 0.7 ? "ok" : "warn") + '">результат ' + Math.round(t.score * 100) + "%</span>" : "") + "</div>";
      t.questions.forEach((q, i) => {
        const r = t.result ? t.result[q.id] : null;
        h += '<fieldset class="col" style="border:0;padding:0;margin:0;gap:6px"><legend class="small" style="font-weight:600;margin-bottom:6px">' + (i + 1) + ". " + esc(q.text) + "</legend>";
        q.options.forEach((o, k) => {
          const on = r ? r.chosen === k : picked[q.id] === k, good = r && k === r.correct, bad = r && on && !r.ok;
          h += '<button type="button" class="btn" data-tq="' + t.id + '" data-q="' + q.id + '" data-k="' + k + '" aria-pressed="' + on + '"' + (r ? " disabled" : "") + ' style="justify-content:flex-start;text-align:left;white-space:normal;border-radius:12px;' + (good ? "background:#E9F6EE;border-color:#1F8F4E" : bad ? "background:#FDECEC;border-color:#C93434" : on ? "border-color:#0A7CD6;background:#EAF2FF" : "") + '">' + esc(o) + "</button>";
        });
        if (r && !r.ok) h += '<p class="xs" style="color:#962020">' + esc(r.explanation) + "</p>";
        h += "</fieldset>";
      });
      if (t.score == null) h += '<button type="button" class="btn primary" data-submit="' + t.id + '" style="align-self:flex-start">Проверить ответы</button>';
      else h += '<p class="small muted">Результат попадёт в вашу карточку. Ошибки разберите с ' + (role === "intern" ? "наставником" : "HR") + " на реальной задаче.</p>";
      return h + "</section>";
    }).join("");
  }
  const tests = () => (staff ? testsStaff() : testsSide());
  function guide() {
    const G = L.guide, g = G[guideI] || { title: "", blocks: [] };
    let h = '<div class="widgets"><nav class="card col" style="flex:1 1 240px;padding:10px;gap:2px" aria-label="Статьи справочника">' + G.map((x, i) => '<button type="button" data-g="' + i + '" aria-current="' + (i === guideI) + '" style="text-align:left;border:0;border-radius:10px;padding:10px;min-height:44px;cursor:pointer;background:' + (i === guideI ? "#F3F5F9" : "transparent") + ';font-size:14px"><span class="head" style="font-size:12px;color:#0A7CD6;margin-right:8px">0' + (i + 1) + "</span>" + esc(x.title) + "</button>").join("") + "</nav>";
    h += '<article class="card col" style="flex:3 1 480px;gap:12px"><p class="eyebrow">0' + (guideI + 1) + '</p><h2 class="head" style="font-size:24px">' + esc(g.title) + "</h2>";
    let table = [];
    const flush = () => { if (table.length) { h += '<div class="scroll-x"><table class="tbl">' + table.filter((r) => !/^\|[-| ]+\|$/.test(r)).map((r, i) => "<tr>" + r.split(/(?<!\\)\|/).slice(1, -1).map((c) => (i ? "<td>" : "<th>") + md(c.trim().replace(/\\\|/g, "|")) + (i ? "</td>" : "</th>")).join("") + "</tr>").join("") + "</table></div>"; table = []; } };
    const md = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, '<code class="formula">$1</code>');
    g.blocks.forEach((b) => {
      if (b.startsWith("|")) { table.push(b); return; }
      flush();
      if (b.startsWith("> ")) h += '<p class="small" style="background:#EAF2FF;border-radius:12px;padding:12px;color:#1D4C9A">' + md(b.slice(2)) + "</p>";
      else if (b.startsWith("- ")) h += '<p class="small" style="line-height:1.6;padding-left:14px">• ' + md(b.slice(2)) + "</p>";
      else h += '<p style="line-height:1.65">' + md(b) + "</p>";
    });
    flush();
    if (/Качество/.test(g.title) && L.validation) {
      const rows = L.validation.results["1–10"] || Object.values(L.validation.results)[0];
      h += '<p class="eyebrow">Прогон детектора · ' + L.validation.n + ' пар на сценарий · шкала 1–10</p><div class="scroll-x"><table class="tbl"><tr><th>Сценарий</th><th>Нашли</th><th>Задержка, мес.</th></tr>' + rows.map((r) => "<tr><td>" + esc(r.title) + "</td><td>" + (r.kind === "healthy" ? "ложные тревоги: " + Math.round(r.false_alarm_pairs * 100) + "% пар" : Math.round(r.recall * 100) + "%") + "</td><td>" + (r.median_delay == null ? "—" : r.median_delay) + "</td></tr>").join("") + '</table></div><p class="xs muted">Цифры — из реального прогона ml/validate.py (docs/VALIDATION.md).</p>';
    }
    return h + "</article></div>";
  }
  function bind() {
    const $ = (s) => box.querySelector(s), all = (s) => box.querySelectorAll(s);
    all("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; history.replaceState(null, "", "/learn?tab=" + tab); render(); }));
    all("[data-g]").forEach((b) => b.addEventListener("click", () => { guideI = +b.dataset.g; render(); }));
    all("[data-done]").forEach((b) => b.addEventListener("click", async () => { await api("POST", "/api/courses/" + b.dataset.done + "/progress", { progress: 100 }); toast("Курс отмечен пройденным"); load(); }));
    const cf = $("#c-file"); if (cf) cf.addEventListener("change", () => { $("#c-fname").textContent = cf.files[0] ? cf.files[0].name : ""; });
    const cs = $("#c-save"); if (cs) cs.addEventListener("click", async () => {
      const fd = new FormData(); fd.append("title", $("#c-title").value); fd.append("kind", $("#c-kind").value); fd.append("topic", $("#c-topic").value); fd.append("audience", $("#c-aud").value); fd.append("text", $("#c-text").value);
      if (cf.files[0]) fd.append("file", cf.files[0]);
      try { await api("POST", "/api/courses", fd); toast("Курс сохранён. По нему можно составить тест"); load(); } catch (e) { toast(e.message); }
    });
    all("[data-assign]").forEach((b) => b.addEventListener("click", () => {
      const c = L.courses.find((x) => x.id === +b.dataset.assign);
      const back = document.createElement("div"); back.className = "modal-back";
      back.innerHTML = '<div class="modal" role="dialog" aria-modal="true" aria-label="Назначить курс"><div class="row between"><h2 class="head" style="font-size:18px">Назначить «' + esc(c.title) + '»</h2><button type="button" class="icon-btn" data-x aria-label="Закрыть">×</button></div><p class="small muted">' + (c.audience === "mentor" ? "Наставнику" : "Стажёру") + " выбранных пар:</p>" + pairs.map((p) => '<label class="row nowrap small" style="gap:10px;min-height:40px"><input type="checkbox" value="' + p.id + '" style="width:20px;height:20px;accent-color:#0A7CD6"><b>' + esc(p.code) + "</b> · " + esc(p.st.label) + "</label>").join("") + '<button type="button" class="btn primary" data-ok>Назначить</button></div>';
      document.body.appendChild(back);
      back.querySelector("[data-x]").onclick = () => back.remove();
      back.querySelector("[data-ok]").onclick = async () => { const ids = Array.from(back.querySelectorAll("input:checked")).map((i) => +i.value); const r = await api("POST", "/api/courses/" + c.id + "/assign", { pair_ids: ids, side: c.audience }); back.remove(); toast("Назначено: " + r.assigned); load(); };
    }));
    all("[data-gen]").forEach((b) => b.addEventListener("click", async () => { b.disabled = true; b.textContent = "ИИ составляет тест…"; try { draft = await api("POST", "/api/tests/generate", { course_id: +b.dataset.gen, n: 3 }); tab = "tests"; await load(); } catch (e) { toast(e.message); b.disabled = false; } }));
    all("[data-open]").forEach((b) => b.addEventListener("click", () => { draft = L.tests.find((t) => t.id === +b.dataset.open); render(); }));
    all("[data-q][type=checkbox]").forEach((c) => c.addEventListener("change", async () => { await api("PUT", "/api/tests/" + draft.id + "/questions/" + c.dataset.q, { enabled: c.checked }); draft.questions.find((q) => q.id === +c.dataset.q).enabled = c.checked; }));
    const tp = $("#t-pub"); if (tp) tp.addEventListener("click", async () => { try { const r = await api("POST", "/api/tests/" + draft.id + "/publish"); toast("Тест опубликован, назначен: " + r.assigned); draft = null; load(); } catch (e) { toast(e.message); } });
    const tc = $("#t-cancel"); if (tc) tc.addEventListener("click", () => { draft = null; render(); });
    all("[data-tq]").forEach((b) => b.addEventListener("click", () => { picked[+b.dataset.q] = +b.dataset.k; render(); }));
    all("[data-submit]").forEach((b) => b.addEventListener("click", async () => {
      const t = L.tests.find((x) => x.id === +b.dataset.submit), answers = {};
      t.questions.forEach((q) => { if (picked[q.id] != null) answers[q.id] = picked[q.id]; });
      if (Object.keys(answers).length < t.questions.length) { toast("Ответьте на все вопросы"); return; }
      const r = await api("POST", "/api/tests/" + t.id + "/answer", { answers }); toast("Результат: " + Math.round(r.score * 100) + "%"); load();
    }));
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
