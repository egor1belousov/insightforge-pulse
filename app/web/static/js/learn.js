// Обучение: конструктор материалов, тесты с ИИ и проверкой HR, читалка и прохождение тестов, справочник.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page"), role = document.getElementById("main").dataset.role;
  const isHr = role === "hr", staff = isHr || role === "lead";
  const TABS = isHr ? [["courses", "Материалы"], ["tests", "Тесты"], ["guide", "Справочник"]] : staff ? [["guide", "Справочник"], ["courses", "Материалы"]] : [["courses", role === "mentor" ? "Памятки и материалы" : "Мои материалы"], ["tests", "Тесты"]];
  const TOP = { tasks: "Понимание задач", auto: "Самостоятельность", support: "Поддержка", load: "Нагрузка", feedback: "Обратная связь", growth: "Перспективы" };
  const KINDS = ["Курс", "Памятка", "Чек-лист", "Материал"];
  const AUD = { intern: "Стажёрам", mentor: "Наставникам", all: "Всем" };
  const SEC = { text: "Текст", list: "Список", tip: "Совет", check: "Чек-лист" };
  const QT = { single: "Один ответ", multi: "Несколько ответов", truefalse: "Верно / неверно" };
  const QHINT = { single: "Выберите один ответ", multi: "Выберите все верные ответы", truefalse: "Верно или неверно?" };
  const DIFF = { easy: "Базовый", medium: "Средний", hard: "Сложный" };
  const BY = { llm: "составил ИИ", "llm+rules": "ИИ + правила", rules: "составлен правилами" };
  const TAG_HINTS = ["Оборудование", "Охрана труда", "Коммуникация", "Планирование", "Наставничество", "Карьера", "Документы", "Клиенты", "Безопасность данных"];
  let tab = new URLSearchParams(location.search).get("tab") || TABS[0][0], L = null, guideI = 0, pairs = [];
  let view = "list", ed = null, T = null, R = null, play = null, fKind = "all", fTag = null, fText = "";

  async function load() { L = await api("GET", "/api/learn"); if (isHr && !pairs.length) pairs = (await api("GET", "/api/dashboard")).pairs; render(); }
  const mins = (secs) => Math.max(2, Math.round(secs.map((s) => (s.title || "") + " " + (s.body || "")).join(" ").split(/\s+/).filter(Boolean).length / 150 + secs.length * 0.5));
  const lines = (b) => String(b || "").split("\n").map((x) => x.trim()).filter(Boolean);

  function render() {
    if (view === "edit") { box.innerHTML = editor(); bindEditor(); return; }
    if (view === "test") { box.innerHTML = testEditor(); bindTest(); return; }
    if (view === "read") { box.innerHTML = reader(); bindReader(); return; }
    if (view === "take") { box.innerHTML = player(); bindPlayer(); return; }
    const title = staff ? "Обучение" : role === "mentor" ? "Памятки и тесты" : "Мои материалы и тесты";
    const sub = isHr ? "Собирайте материалы из разделов, создавайте тесты с ИИ и проверяйте их, держите методику под рукой." : staff ? "Справочник по методике и каталог материалов программы." : "Назначено по результатам ваших анкет. Отмечайте прочитанные разделы — прогресс увидит HR.";
    let h = '<section class="hero"><div class="sphere orb" data-orb="dots" data-size="560" aria-hidden="true"></div><p class="tagline">Обучение</p><h1>' + title + '</h1><p class="sub">' + sub + '</p></section><div class="seg" role="tablist">' + TABS.map(([k, n]) => '<button type="button" role="tab" data-tab="' + k + '" aria-selected="' + (tab === k) + '">' + n + "</button>").join("") + "</div>";
    h += tab === "courses" ? courses() : tab === "tests" ? (staff ? testsStaff() : testsSide()) : guide();
    box.innerHTML = h; bind();
  }

  // ---------- материалы: каталог ----------
  function card(c) {
    let h = '<section class="card col mat-card" style="gap:10px"><div class="row" style="gap:6px"><span class="chip info">' + esc(c.kind) + '</span><span class="chip">' + esc(c.duration || "") + "</span>" + (c.status === "draft" ? '<span class="chip warn">черновик</span>' : "") + (staff ? '<span class="xs muted">' + esc(AUD[c.audience] || "") + "</span>" : "") + '</div><b style="font-size:16px">' + esc(c.title) + '</b><p class="small muted" style="line-height:1.5">' + esc(c.description) + "</p>";
    if ((c.tags || []).length || c.topic) h += '<div class="row" style="gap:6px">' + (c.tags || []).map((t) => '<span class="tag">' + esc(t) + "</span>").join("") + (c.topic ? '<span class="tag" title="Связано с темой анкеты" style="background:var(--accent-soft);color:var(--accent-ink)">↔ ' + esc(TOP[c.topic]) + "</span>" : "") + "</div>";
    if (c.progress != null) h += '<div class="bar"><span style="width:' + c.progress + '%;background:var(--accent)"></span></div><span class="xs muted">' + (c.progress >= 100 ? "Пройдено" : "Пройдено " + c.progress + "%") + (c.reason ? " · " + esc(c.reason) : "") + "</span>";
    if (staff) h += '<p class="xs muted" style="border-top:1px solid var(--soft);padding-top:8px">' + c.sections_count + " " + Pulse.plural(c.sections_count, "раздел", "раздела", "разделов") + " · назначено: " + (c.assigned.length ? esc(c.assigned.join(", ")) : "никому") + "</p>";
    h += '<div class="row" style="gap:6px;margin-top:auto">';
    if (isHr) h += '<button type="button" class="btn small primary" data-edit="' + c.id + '">Открыть</button><button type="button" class="btn small" data-assign="' + c.id + '">Назначить</button><button type="button" class="btn small" data-gen="' + c.id + '">Тест · ИИ</button>';
    else h += '<button type="button" class="btn small ' + (c.progress != null && c.progress < 100 ? "primary" : "") + '" data-read="' + c.id + '">' + (c.progress == null ? "Открыть" : c.progress >= 100 ? "Повторить" : c.progress ? "Продолжить" : "Начать") + "</button>";
    return h + "</div></section>";
  }
  function courses() {
    const all = L.courses, tags = [...new Set(all.flatMap((c) => c.tags || []))];
    let h = "";
    if (staff) {
      h += '<section class="card row" style="gap:10px 14px;padding:14px 18px"><label class="sr-only" for="m-q">Поиск</label><input class="input small" id="m-q" placeholder="Найти материал" value="' + esc(fText) + '" style="flex:1 1 220px;width:auto"><div class="row" style="gap:6px">' + [["all", "Все"]].concat(KINDS.map((k) => [k, k])).map(([k, n]) => '<button type="button" class="pill" data-fk="' + esc(k) + '" aria-pressed="' + (fKind === k) + '">' + esc(n) + "</button>").join("") + "</div>" + (isHr ? '<button type="button" class="btn primary small" id="m-new" style="margin-left:auto">+ Новый материал</button>' : "") + "</section>";
      if (tags.length) h += '<div class="row" style="gap:6px"><span class="xs muted" style="font-weight:700;letter-spacing:.06em">ТЕМЫ:</span>' + tags.map((t) => '<button type="button" class="pill accent" data-ft="' + esc(t) + '" aria-pressed="' + (fTag === t) + '">' + esc(t) + "</button>").join("") + "</div>";
    }
    const list = all.filter((c) => (fKind === "all" || c.kind === fKind) && (!fTag || (c.tags || []).includes(fTag)) && (!fText || (c.title + " " + c.description + " " + (c.tags || []).join(" ")).toLowerCase().includes(fText.toLowerCase())));
    h += list.length ? '<div class="mat-grid">' + list.map(card).join("") + "</div>" : '<section class="card col" style="align-items:flex-start"><b>' + (staff ? (all.length ? "Ничего не нашлось" : "Материалов пока нет") : "Вам пока ничего не назначено") + '</b><p class="small muted">' + (isHr ? "Соберите материал из разделов или загрузите .docx — Пульс разобьёт его на разделы сам." : staff ? "Попробуйте другой фильтр." : "Материалы появятся, когда HR назначит их по итогам анкеты.") + "</p>" + (isHr && !all.length ? '<button type="button" class="btn primary small" id="m-new2">+ Новый материал</button>' : "") + "</section>";
    return h;
  }

  // ---------- конструктор материала ----------
  function blank() { return { id: null, title: "", kind: "Курс", audience: "intern", topic: null, tags: [], duration: "", status: "published", sections: [{ kind: "text", title: "", body: "" }] }; }
  async function openEditor(id) {
    ed = id ? await api("GET", "/api/courses/" + id) : blank();
    ed.duration = ed.duration && !/^\d+ мин$/.test(ed.duration) ? ed.duration : "";
    view = "edit"; render(); window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function secPreview(s, i, done) {
    const head = s.title ? '<h3 class="rd-h">' + esc(s.title) + "</h3>" : "";
    let body = "";
    if (s.kind === "list") body = "<ul>" + lines(s.body).map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>";
    else if (s.kind === "check") body = '<div class="col" style="gap:6px">' + lines(s.body).map((x, k) => '<label class="row nowrap small" style="gap:10px;cursor:pointer"><input type="checkbox" data-chk="' + i + "-" + k + '" style="width:18px;height:18px;accent-color:var(--accent)">' + esc(x) + "</label>").join("") + "</div>";
    else if (s.kind === "tip") body = '<div class="rd-tip"><b>Совет.</b> ' + esc(s.body) + "</div>";
    else body = String(s.body || "").split(/\n{2,}/).map((p) => '<p class="rd-p">' + esc(p) + "</p>").join("");
    return '<div class="rd-sec' + (done ? " done" : "") + '">' + head + body + "</div>";
  }
  function preview() {
    const secs = ed.sections.filter((s) => s.title || s.body);
    return '<div class="col" style="gap:12px"><div class="row" style="gap:6px"><span class="chip info">' + esc(ed.kind) + '</span><span class="chip">≈ ' + (ed.duration || mins(secs) + " мин") + '</span><span class="xs muted">' + esc(AUD[ed.audience]) + '</span></div><h2 class="head" style="font-size:22px">' + esc(ed.title || "Без названия") + "</h2>" + (ed.tags.length ? '<div class="row" style="gap:6px">' + ed.tags.map((t) => '<span class="tag">' + esc(t) + "</span>").join("") + "</div>" : "") + (secs.length ? secs.map((s, i) => secPreview(s, i)).join("") : '<p class="small muted">Добавьте разделы — здесь будет видно, как материал увидит стажёр.</p>') + "</div>";
  }
  function editor() {
    let h = '<div class="row between"><button type="button" class="btn ghost small" id="ed-back" style="padding-left:0">← К материалам</button><span class="xs muted">' + (ed.id ? "Редактирование" : "Новый материал") + "</span></div>";
    h += '<div class="ed-grid"><section class="card col" style="gap:16px">';
    h += '<div class="field"><span class="label">Тип</span><div class="seg">' + KINDS.map((k) => '<button type="button" data-kind="' + k + '" aria-pressed="' + (ed.kind === k) + '">' + k + "</button>").join("") + "</div></div>";
    h += '<div class="field"><label for="ed-title">Название</label><input class="input" id="ed-title" value="' + esc(ed.title) + '" placeholder="Например: Оборудование на выезде" maxlength="300"></div>';
    h += '<div class="row" style="gap:16px;align-items:flex-start"><div class="field" style="flex:1 1 240px"><span class="label">Для кого</span><div class="seg">' + Object.entries(AUD).map(([k, n]) => '<button type="button" data-aud="' + k + '" aria-pressed="' + (ed.audience === k) + '">' + n + "</button>").join("") + '</div></div><div class="field" style="flex:1 1 160px"><label for="ed-dur">Длительность</label><input class="input small" id="ed-dur" value="' + esc(ed.duration) + '" placeholder="≈ ' + mins(ed.sections) + ' мин — посчитаем сами"></div></div>';
    h += '<div class="field"><label for="ed-tag">Темы материала</label><div class="tag-box">' + ed.tags.map((t, i) => '<span class="tag-chip">' + esc(t) + '<button type="button" data-untag="' + i + '" aria-label="Убрать тему ' + esc(t) + '">×</button></span>').join("") + '<input id="ed-tag" list="tag-hints" placeholder="' + (ed.tags.length ? "Ещё тема" : "Любая тема: Оборудование, Охрана труда…") + '"><datalist id="tag-hints">' + [...new Set(TAG_HINTS.concat(L.courses.flatMap((c) => c.tags || [])))].filter((t) => !ed.tags.includes(t)).map((t) => '<option value="' + esc(t) + '">').join("") + '</datalist></div><span class="xs muted">Свои темы — для каталога и поиска. Enter или запятая добавляет тему.</span></div>';
    h += '<div class="field"><label for="ed-topic">Связать с темой анкеты</label><select class="input small" id="ed-topic"><option value="">Не связывать</option>' + Object.entries(TOP).map(([k, n]) => '<option value="' + k + '"' + (ed.topic === k ? " selected" : "") + ">" + n + "</option>").join("") + '</select><span class="xs muted">Если тема проседает у пары, Пульс предложит этот материал в действиях.</span></div>';
    h += '<div class="col" style="gap:10px"><div class="row between"><span class="label">Разделы · ' + ed.sections.length + '</span><label class="btn small" style="cursor:pointer">Импорт из файла<input type="file" id="ed-file" accept=".docx,.txt,.md" hidden></label></div>';
    ed.sections.forEach((s, i) => {
      h += '<div class="sec-ed" data-sec="' + i + '"><div class="row nowrap" style="gap:6px"><span class="sec-n">' + (i + 1) + '</span><select class="input small" data-sk="' + i + '" style="width:auto" aria-label="Вид раздела">' + Object.entries(SEC).map(([k, n]) => '<option value="' + k + '"' + (s.kind === k ? " selected" : "") + ">" + n + "</option>").join("") + '</select><input class="input small" data-st="' + i + '" value="' + esc(s.title) + '" placeholder="Заголовок раздела (необязательно)" style="flex:1"><button type="button" class="icon-btn" data-sup="' + i + '" aria-label="Выше"' + (i ? "" : " disabled") + '>↑</button><button type="button" class="icon-btn" data-sdown="' + i + '" aria-label="Ниже"' + (i < ed.sections.length - 1 ? "" : " disabled") + '>↓</button><button type="button" class="icon-btn" data-sdel="' + i + '" aria-label="Удалить раздел">×</button></div><textarea class="input" data-sb="' + i + '" rows="' + (s.kind === "text" ? 4 : 3) + '" placeholder="' + (s.kind === "list" || s.kind === "check" ? "Каждый пункт — с новой строки" : s.kind === "tip" ? "Короткий совет из практики" : "Текст раздела") + '">' + esc(s.body) + "</textarea></div>";
    });
    h += '<div class="row" style="gap:6px">' + Object.entries(SEC).map(([k, n]) => '<button type="button" class="btn small" data-sadd="' + k + '">+ ' + n + "</button>").join("") + "</div></div>";
    h += '<div id="ed-err" class="form-error" hidden></div><div class="row" style="gap:8px;border-top:1px solid var(--soft);padding-top:14px"><button type="button" class="btn primary" data-save="published">Опубликовать</button><button type="button" class="btn" data-save="draft">Сохранить черновик</button>' + (ed.id ? '<button type="button" class="btn danger" id="ed-del" style="margin-left:auto">Удалить</button>' : "") + "</div></section>";
    h += '<aside class="card col ed-prev"><p class="eyebrow">Так увидит ' + (ed.audience === "mentor" ? "наставник" : ed.audience === "all" ? "участник" : "стажёр") + '</p><div id="ed-prev">' + preview() + "</div></aside></div>";
    return h;
  }
  function syncPreview() { const p = document.getElementById("ed-prev"); if (p) p.innerHTML = preview(); }
  function bindEditor() {
    const $ = (s) => box.querySelector(s), all = (s) => box.querySelectorAll(s);
    $("#ed-back").addEventListener("click", () => { view = "list"; render(); });
    all("[data-kind]").forEach((b) => b.addEventListener("click", () => { ed.kind = b.dataset.kind; render(); }));
    all("[data-aud]").forEach((b) => b.addEventListener("click", () => { ed.audience = b.dataset.aud; render(); }));
    $("#ed-title").addEventListener("input", (e) => { ed.title = e.target.value; syncPreview(); });
    $("#ed-dur").addEventListener("input", (e) => { ed.duration = e.target.value; syncPreview(); });
    $("#ed-topic").addEventListener("change", (e) => { ed.topic = e.target.value || null; });
    const tagIn = $("#ed-tag");
    const addTag = () => { const v = tagIn.value.replace(/,/g, "").trim(); if (v && !ed.tags.includes(v) && ed.tags.length < 8) { ed.tags.push(v); render(); box.querySelector("#ed-tag").focus(); } else tagIn.value = ""; };
    tagIn.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(); } else if (e.key === "Backspace" && !tagIn.value && ed.tags.length) { ed.tags.pop(); render(); } });
    tagIn.addEventListener("change", () => { if (TAG_HINTS.includes(tagIn.value) || L.courses.some((c) => (c.tags || []).includes(tagIn.value))) addTag(); });
    all("[data-untag]").forEach((b) => b.addEventListener("click", () => { ed.tags.splice(+b.dataset.untag, 1); render(); }));
    all("[data-st]").forEach((x) => x.addEventListener("input", () => { ed.sections[+x.dataset.st].title = x.value; syncPreview(); }));
    all("[data-sb]").forEach((x) => x.addEventListener("input", () => { ed.sections[+x.dataset.sb].body = x.value; syncPreview(); }));
    all("[data-sk]").forEach((x) => x.addEventListener("change", () => { ed.sections[+x.dataset.sk].kind = x.value; render(); }));
    const move = (i, d) => { const s = ed.sections; [s[i], s[i + d]] = [s[i + d], s[i]]; render(); };
    all("[data-sup]").forEach((b) => b.addEventListener("click", () => move(+b.dataset.sup, -1)));
    all("[data-sdown]").forEach((b) => b.addEventListener("click", () => move(+b.dataset.sdown, 1)));
    all("[data-sdel]").forEach((b) => b.addEventListener("click", () => { ed.sections.splice(+b.dataset.sdel, 1); if (!ed.sections.length) ed.sections.push({ kind: "text", title: "", body: "" }); render(); }));
    all("[data-sadd]").forEach((b) => b.addEventListener("click", () => { ed.sections.push({ kind: b.dataset.sadd, title: "", body: "" }); render(); const t = box.querySelectorAll("[data-sb]"); t[t.length - 1].focus(); }));
    $("#ed-file").addEventListener("change", async (e) => {
      const f = e.target.files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      try {
        const r = await api("POST", "/api/courses/parse", fd);
        ed.sections = ed.sections.filter((s) => s.title || s.body).concat(r.sections);
        if (!ed.title) ed.title = f.name.replace(/\.(docx|txt|md)$/i, "");
        toast("Из файла «" + f.name + "» получилось разделов: " + r.sections.length + ". Проверьте их перед публикацией");
        render();
      } catch (err) { toast(err.message); }
    });
    all("[data-save]").forEach((b) => b.addEventListener("click", async () => {
      const body = { title: ed.title, kind: ed.kind, topic: ed.topic, audience: ed.audience, duration: ed.duration, tags: ed.tags, sections: ed.sections.filter((s) => s.title || s.body), status: b.dataset.save };
      try {
        if (ed.id) await api("PUT", "/api/courses/" + ed.id, body);
        else { const fd = new FormData(); Object.entries(body).forEach(([k, v]) => fd.append(k, typeof v === "string" ? v : v == null ? "" : JSON.stringify(v))); await api("POST", "/api/courses", fd); }
        toast(b.dataset.save === "draft" ? "Черновик сохранён" : "Материал опубликован — его можно назначить парам");
        view = "list"; await load();
      } catch (err) { const e = $("#ed-err"); e.textContent = err.message; e.hidden = false; }
    }));
    const del = $("#ed-del");
    if (del) del.addEventListener("click", async () => { if (!confirm("Удалить материал «" + ed.title + "»? Назначения тоже удалятся.")) return; await api("DELETE", "/api/courses/" + ed.id); toast("Материал удалён"); view = "list"; load(); });
  }

  // ---------- тесты: HR ----------
  function testsStaff() {
    let h = isHr ? '<section class="card row between" style="padding:14px 18px"><span class="small muted">ИИ составляет вопросы по каждому разделу материала, к каждому — цитата-источник. Вы проверяете, правите и публикуете.</span><button type="button" class="btn primary small" id="t-new">+ Создать тест</button></section>' : "";
    if (!L.tests.length) return h + '<p class="small muted">Тестов пока нет.</p>';
    h += '<div class="mat-grid">' + L.tests.map((t) => {
      const qs = t.questions.filter((q) => q.enabled), types = {};
      qs.forEach((q) => { types[q.qtype] = (types[q.qtype] || 0) + 1; });
      const avg = t.results.length ? Math.round((t.results.reduce((a, r) => a + r.score, 0) / t.results.length) * 100) : null;
      return '<section class="card col" style="gap:10px"><div class="row" style="gap:6px"><span class="chip ' + (t.status === "published" ? "ok" : "warn") + '">' + (t.status === "published" ? "опубликован" : "черновик") + '</span><span class="chip">' + esc(DIFF[t.difficulty] || "Средний") + '</span><span class="xs muted">' + esc(BY[t.generated_by] || "") + '</span></div><b style="font-size:16px">' + esc(t.title) + '</b><p class="small muted">' + qs.length + " " + Pulse.plural(qs.length, "вопрос", "вопроса", "вопросов") + " · " + Object.entries(types).map(([k, n]) => QT[k].toLowerCase() + " " + n).join(", ") + " · проходной " + Math.round(t.pass_score * 100) + "%</p>" + (t.assigned.length ? '<p class="xs muted">Назначен: ' + esc(t.assigned.join(", ")) + (avg != null ? " · средний результат " + avg + "%" : "") + "</p>" : "") + (t.results.length ? '<div class="row" style="gap:6px">' + t.results.map((r) => '<span class="chip ' + (r.score >= t.pass_score ? "ok" : "bad") + '">' + esc(r.who) + " · " + Math.round(r.score * 100) + "%</span>").join("") + "</div>" : "") + (isHr ? '<button type="button" class="btn small ' + (t.status === "published" ? "" : "primary") + '" data-topen="' + t.id + '" style="align-self:flex-start;margin-top:auto">' + (t.status === "published" ? "Открыть" : "Проверить и опубликовать") + "</button>" : "") + "</section>";
    }).join("") + "</div>";
    return h;
  }
  function genModal(courseId) {
    if (!L.courses.length) { toast("Сначала создайте материал — тест строится по нему"); return; }
    const st = { course: courseId || L.courses[0].id, n: 8, diff: "medium", types: { single: true, multi: true, truefalse: true }, pass: 0.7 };
    const m = Pulse.modal('<div class="modal" role="dialog" aria-modal="true" aria-labelledby="g-t"><div class="row between"><h2 class="head" id="g-t" style="font-size:20px">Тест по материалу · ИИ</h2><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div><div id="g-body"></div></div>');
    const draw = () => {
      m.back.querySelector("#g-body").innerHTML = '<div class="col" style="gap:14px"><div class="field"><label for="g-c">Материал</label><select class="input" id="g-c">' + L.courses.map((c) => '<option value="' + c.id + '"' + (c.id === st.course ? " selected" : "") + ">" + esc(c.kind + " · " + c.title) + " (" + c.sections_count + " разд.)</option>").join("") + '</select></div><div class="field"><label for="g-n">Вопросов: <b id="g-nv">' + st.n + '</b></label><input type="range" id="g-n" min="5" max="15" value="' + st.n + '" style="accent-color:var(--accent)"></div><div class="field"><span class="label">Сложность</span><div class="seg">' + Object.entries(DIFF).map(([k, n]) => '<button type="button" data-gd="' + k + '" aria-pressed="' + (st.diff === k) + '">' + n + '</button>').join("") + '</div><span class="xs muted">' + { easy: "Факты, которые прямо написаны в материале.", medium: "Понять правило и применить к простой ситуации.", hard: "Ситуации на объекте: выбрать правильное действие." }[st.diff] + '</span></div><div class="field"><span class="label">Типы вопросов</span><div class="row" style="gap:6px">' + Object.entries(QT).map(([k, n]) => '<button type="button" class="pill accent" data-gt="' + k + '" aria-pressed="' + st.types[k] + '">' + n + '</button>').join("") + '</div></div><div class="field"><span class="label">Проходной балл</span><div class="seg">' + [0.6, 0.7, 0.8, 0.9].map((v) => '<button type="button" data-gp="' + v + '" aria-pressed="' + (st.pass === v) + '">' + v * 100 + "%</button>").join("") + '</div></div><div id="g-err" class="form-error" hidden></div><button type="button" class="btn primary" id="g-go" style="align-self:flex-start">Составить черновик</button><p class="xs muted">ИИ работает локально. Вопросы без цитаты из материала отбрасываются, недостающие добавляются правилами.</p></div>';
      const q = (s) => m.back.querySelector(s);
      q("#g-c").addEventListener("change", (e) => { st.course = +e.target.value; });
      q("#g-n").addEventListener("input", (e) => { st.n = +e.target.value; q("#g-nv").textContent = st.n; });
      m.back.querySelectorAll("[data-gd]").forEach((b) => b.addEventListener("click", () => { st.diff = b.dataset.gd; draw(); }));
      m.back.querySelectorAll("[data-gt]").forEach((b) => b.addEventListener("click", () => { st.types[b.dataset.gt] = !st.types[b.dataset.gt]; if (!Object.values(st.types).some(Boolean)) st.types.single = true; draw(); }));
      m.back.querySelectorAll("[data-gp]").forEach((b) => b.addEventListener("click", () => { st.pass = +b.dataset.gp; draw(); }));
      q("#g-go").addEventListener("click", async () => {
        const b = q("#g-go"); b.disabled = true; b.innerHTML = '<span class="spin"></span> ИИ читает разделы и составляет вопросы…';
        try {
          T = await api("POST", "/api/tests/generate", { course_id: st.course, n: st.n, difficulty: st.diff, types: Object.keys(st.types).filter((k) => st.types[k]), pass_score: st.pass });
          m.close(); view = "test"; tab = "tests"; await load();
        } catch (e) { q("#g-err").textContent = e.message; q("#g-err").hidden = false; b.disabled = false; b.textContent = "Составить черновик"; }
      });
    };
    draw();
  }
  function qCard(q, i) {
    const multi = q.qtype === "multi", tf = q.qtype === "truefalse";
    let h = '<section class="card col q-ed' + (q.enabled ? "" : " off") + '" data-qc="' + q.id + '" style="gap:12px"><div class="row between nowrap" style="gap:10px"><span class="row nowrap" style="gap:10px"><span class="sec-n">' + (i + 1) + '</span><select class="input small" data-qt="' + q.id + '" style="width:auto" aria-label="Тип вопроса">' + Object.entries(QT).map(([k, n]) => '<option value="' + k + '"' + (q.qtype === k ? " selected" : "") + ">" + n + "</option>").join("") + '</select></span><label class="row nowrap xs muted" style="gap:8px;cursor:pointer"><input type="checkbox" data-qon="' + q.id + '"' + (q.enabled ? " checked" : "") + ' style="width:18px;height:18px;accent-color:var(--accent)"> в тесте</label></div>';
    h += '<textarea class="input" data-qtext rows="2" aria-label="Текст вопроса">' + esc(q.text) + "</textarea>";
    h += '<div class="col" style="gap:6px">' + q.options.map((o, k) => '<div class="row nowrap opt-row' + (q.correct.includes(k) ? " right" : "") + '" style="gap:8px"><input type="' + (multi ? "checkbox" : "radio") + '" name="c' + q.id + '" data-qcor value="' + k + '"' + (q.correct.includes(k) ? " checked" : "") + ' aria-label="Верный ответ" style="width:20px;height:20px;accent-color:var(--ok);flex-shrink:0"><input class="input small" data-qopt value="' + esc(o) + '"' + (tf ? " disabled" : "") + ' aria-label="Вариант ' + (k + 1) + '">' + (!tf && q.options.length > 2 ? '<button type="button" class="icon-btn" data-qoptdel="' + k + '" aria-label="Убрать вариант">×</button>' : "") + "</div>").join("") + (!tf && q.options.length < 5 ? '<button type="button" class="btn ghost small" data-qoptadd style="align-self:flex-start;padding-left:0">+ вариант</button>' : "") + "</div>";
    h += '<input class="input small" data-qexp value="' + esc(q.explanation || "") + '" placeholder="Пояснение к ответу — его увидит стажёр после проверки">';
    if (q.source) h += '<blockquote class="q-src"><span class="xs muted">Из материала:</span> «' + esc(q.source) + "»</blockquote>";
    h += '<div class="row" style="gap:6px"><button type="button" class="btn small primary" data-qsave hidden>Сохранить</button><button type="button" class="btn small" data-qregen>Другой вариант · ИИ</button><button type="button" class="btn ghost small" data-qdel style="margin-left:auto;color:var(--both)">Удалить</button></div>';
    return h + "</section>";
  }
  function testEditor() {
    const qs = T.questions, on = qs.filter((q) => q.enabled), cited = on.filter((q) => q.source && q.source !== "добавлен HR").length;
    const course = L.courses.find((c) => c.id === T.course_id);
    let h = '<div class="row between"><button type="button" class="btn ghost small" id="te-back" style="padding-left:0">← К тестам</button><span class="chip ' + (T.status === "published" ? "ok" : "warn") + '">' + (T.status === "published" ? "опубликован" : "черновик") + "</span></div>";
    h += '<section class="card col" style="gap:12px"><div class="row" style="gap:12px;align-items:flex-end"><div class="field" style="flex:1 1 320px"><label for="te-title">Название теста</label><input class="input" id="te-title" value="' + esc(T.title) + '"></div><div class="field"><span class="label">Проходной балл</span><div class="seg">' + [0.6, 0.7, 0.8, 0.9].map((v) => '<button type="button" data-tp="' + v + '" aria-pressed="' + (Math.abs(T.pass_score - v) < 0.01) + '">' + v * 100 + "%</button>").join("") + "</div></div></div>";
    h += '<div class="row" style="gap:8px"><span class="chip info">' + on.length + " " + Pulse.plural(on.length, "вопрос", "вопроса", "вопросов") + ' в тесте</span><span class="chip ' + (cited === on.length ? "ok" : "warn") + '">с цитатой из материала: ' + cited + " из " + on.length + '</span><span class="chip">' + esc(DIFF[T.difficulty] || "Средний") + '</span><span class="xs muted">' + esc(BY[T.generated_by] || "") + (course ? " · по материалу «" + esc(course.title) + "»" : "") + "</span></div></section>";
    h += '<div class="col" style="gap:14px">' + qs.map(qCard).join("") + "</div>";
    h += '<div class="row" style="gap:8px"><button type="button" class="btn small" id="te-add">+ Вопрос вручную</button></div>';
    h += '<section class="card row between" style="position:sticky;bottom:12px;z-index:5;box-shadow:var(--shadow-pop)"><span class="small muted">' + (T.status === "published" ? "Тест опубликован. Правки сразу видны тем, кто ещё не проходил." : "Проверьте вопросы и опубликуйте — тест назначится тем, кому назначен материал.") + '</span><span class="row" style="gap:8px"><button type="button" class="btn danger small" id="te-del">Удалить тест</button>' + (T.status !== "published" ? '<button type="button" class="btn primary" id="te-pub">Опубликовать</button>' : "") + "</span></section>";
    return h;
  }
  function readQ(card) {
    const q = T.questions.find((x) => x.id === +card.dataset.qc);
    return { qtype: card.querySelector("[data-qt]").value, text: card.querySelector("[data-qtext]").value, options: Array.from(card.querySelectorAll("[data-qopt]")).map((x) => x.value), correct: Array.from(card.querySelectorAll("[data-qcor]")).filter((x) => x.checked).map((x) => +x.value), explanation: card.querySelector("[data-qexp]").value, _q: q };
  }
  function bindTest() {
    const $ = (s) => box.querySelector(s), tid = T.id;
    const apply = (t) => { T = t; render(); };
    $("#te-back").addEventListener("click", () => { view = "list"; load(); });
    $("#te-title").addEventListener("change", async (e) => { T = await api("PUT", "/api/tests/" + tid, { title: e.target.value }); toast("Название сохранено"); });
    box.querySelectorAll("[data-tp]").forEach((b) => b.addEventListener("click", async () => apply(await api("PUT", "/api/tests/" + tid, { pass_score: +b.dataset.tp }))));
    box.querySelectorAll("[data-qc]").forEach((card) => {
      const id = card.dataset.qc, save = card.querySelector("[data-qsave]");
      const dirty = () => { save.hidden = false; card.classList.add("dirty"); };
      card.querySelectorAll("textarea, input").forEach((x) => x.addEventListener("input", dirty));
      card.querySelectorAll("[data-qcor]").forEach((x) => x.addEventListener("change", dirty));
      save.addEventListener("click", async () => { const d = readQ(card); delete d._q; try { apply(await api("PUT", "/api/tests/" + tid + "/questions/" + id, d)); toast("Вопрос сохранён"); } catch (e) { toast(e.message); } });
      card.querySelector("[data-qt]").addEventListener("change", async (e) => { const d = readQ(card); delete d._q; d.qtype = e.target.value; if (d.qtype === "truefalse") d.correct = [Math.min(d.correct[0] || 0, 1)]; try { apply(await api("PUT", "/api/tests/" + tid + "/questions/" + id, d)); } catch (err) { toast(err.message); } });
      card.querySelector("[data-qon]").addEventListener("change", async (e) => apply(await api("PUT", "/api/tests/" + tid + "/questions/" + id, { enabled: e.target.checked })));
      const add = card.querySelector("[data-qoptadd]");
      if (add) add.addEventListener("click", async () => { const d = readQ(card); delete d._q; d.options.push("Новый вариант"); apply(await api("PUT", "/api/tests/" + tid + "/questions/" + id, d)); });
      card.querySelectorAll("[data-qoptdel]").forEach((b) => b.addEventListener("click", async () => { const d = readQ(card), k = +b.dataset.qoptdel; delete d._q; d.options.splice(k, 1); d.correct = d.correct.filter((c) => c !== k).map((c) => (c > k ? c - 1 : c)); if (!d.correct.length) d.correct = [0]; try { apply(await api("PUT", "/api/tests/" + tid + "/questions/" + id, d)); } catch (e) { toast(e.message); } }));
      card.querySelector("[data-qregen]").addEventListener("click", async (e) => { e.target.disabled = true; e.target.textContent = "ИИ подбирает вопрос…"; apply(await api("POST", "/api/tests/" + tid + "/questions/" + id + "/regenerate")); toast("Вопрос заменён — проверьте его"); });
      card.querySelector("[data-qdel]").addEventListener("click", async () => apply(await api("DELETE", "/api/tests/" + tid + "/questions/" + id)));
    });
    $("#te-add").addEventListener("click", async () => { apply(await api("POST", "/api/tests/" + tid + "/questions", {})); const c = box.querySelectorAll("[data-qc]"); c[c.length - 1].scrollIntoView({ behavior: "smooth", block: "center" }); });
    $("#te-del").addEventListener("click", async () => { if (!confirm("Удалить тест?")) return; await api("DELETE", "/api/tests/" + tid); toast("Тест удалён"); view = "list"; load(); });
    const pub = $("#te-pub");
    if (pub) pub.addEventListener("click", async () => { if (box.querySelector(".q-ed.dirty")) { toast("Есть несохранённые вопросы — нажмите «Сохранить» у них"); return; } try { const r = await api("POST", "/api/tests/" + tid + "/publish"); toast("Тест опубликован, назначен: " + r.assigned); T.status = "published"; view = "list"; load(); } catch (e) { toast(e.message); } });
  }

  // ---------- стажёр и наставник: читалка ----------
  async function openReader(id) { R = await api("GET", "/api/courses/" + id); view = "read"; render(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  function reader() {
    const secs = R.sections, done = new Set(R.done || []);
    let h = '<button type="button" class="btn ghost small" id="rd-back" style="padding-left:0;align-self:flex-start">← К материалам</button>';
    h += '<section class="hero"><div class="sphere orb" data-orb="mesh" data-size="560" aria-hidden="true"></div><p class="tagline">' + esc(R.kind + " · ≈ " + R.duration) + '</p><h1>' + esc(R.title) + '</h1><p class="sub">' + (R.tags.length ? esc(R.tags.join(" · ")) : "Отмечайте прочитанные разделы — прогресс сохранится.") + "</p></section>";
    h += '<section class="card col" style="gap:10px;position:sticky;top:76px;z-index:4">' + Pulse.progress([{ n: done.size, cls: "ok", label: "прочитано" }, { n: secs.length - done.size, cls: "idle", label: "осталось" }], { title: done.size >= secs.length ? "Материал пройден" : "Прочитано " + done.size + " из " + secs.length }) + "</section>";
    h += '<article class="card col reader" style="gap:6px">' + secs.map((s, i) => secPreview(s, i, done.has(i)) + '<div class="row" style="justify-content:flex-end;margin:-4px 0 14px">' + (done.has(i) ? '<span class="chip ok">прочитано ✓</span>' : '<button type="button" class="btn small" data-rdone="' + i + '">Прочитано</button>') + "</div>").join("") + "</article>";
    const t = L.tests.find((x) => x.course_id === R.id);
    if (t && done.size >= secs.length) h += '<section class="card row between"><span><b>Проверьте себя.</b> <span class="small muted">' + t.questions.length + " " + Pulse.plural(t.questions.length, "вопрос", "вопроса", "вопросов") + " по этому материалу.</span></span><button type=\"button\" class=\"btn primary\" data-take=\"" + t.id + '">Пройти тест</button></section>';
    return h;
  }
  function bindReader() {
    box.querySelector("#rd-back").addEventListener("click", () => { view = "list"; load(); });
    box.querySelectorAll("[data-rdone]").forEach((b) => b.addEventListener("click", async () => {
      const r = await api("POST", "/api/courses/" + R.id + "/progress", { section: +b.dataset.rdone });
      R.done = r.done; R.progress = r.progress;
      if (r.progress >= 100) toast("Материал пройден — отлично!");
      render();
    }));
    box.querySelectorAll("[data-take]").forEach((b) => b.addEventListener("click", () => startTest(+b.dataset.take)));
  }

  // ---------- стажёр и наставник: тесты ----------
  function testsSide() {
    if (!L.tests.length) return '<section class="card col"><b>Тестов пока нет</b><p class="small muted">Тест появится, когда HR опубликует его по назначенному материалу.</p></section>';
    return '<div class="mat-grid">' + L.tests.map((t) => {
      const st = t.score == null ? ["", "не начат"] : t.passed ? ["ok", "сдан · " + Math.round(t.score * 100) + "%"] : ["bad", "не сдан · " + Math.round(t.score * 100) + "%"];
      return '<section class="card col" style="gap:10px"><div class="row" style="gap:6px"><span class="chip ' + st[0] + '">' + st[1] + '</span>' + (t.attempts ? '<span class="xs muted">попыток: ' + t.attempts + "</span>" : "") + '</div><b style="font-size:16px">' + esc(t.title) + '</b><p class="small muted">' + t.questions.length + " " + Pulse.plural(t.questions.length, "вопрос", "вопроса", "вопросов") + " · чтобы сдать, нужно " + Math.round(t.pass_score * 100) + '% верных</p><div class="row" style="gap:6px;margin-top:auto"><button type="button" class="btn small ' + (t.passed ? "" : "primary") + '" data-take="' + t.id + '">' + (t.score == null ? "Начать" : "Пройти ещё раз") + "</button>" + (t.result ? '<button type="button" class="btn small" data-review="' + t.id + '">Разбор</button>' : "") + "</div></section>";
    }).join("") + "</div>";
  }
  function startTest(id) { const t = L.tests.find((x) => x.id === id); play = { t, i: 0, ans: {}, res: null }; view = "take"; render(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  function review(t, res) {
    return t.questions.map((q, i) => {
      const r = res[q.id]; if (!r) return "";
      return '<div class="col rev ' + (r.ok ? "ok" : "bad") + '" style="gap:6px"><b class="small">' + (i + 1) + ". " + esc(q.text) + '</b><div class="col" style="gap:4px">' + q.options.map((o, k) => { const right = r.correct.includes(k), mine = r.chosen.includes(k); return '<span class="small rev-opt' + (right ? " right" : mine ? " wrong" : "") + '">' + (right ? "✓ " : mine ? "✕ " : "") + esc(o) + (mine ? ' <span class="xs muted">— ваш ответ</span>' : "") + "</span>"; }).join("") + "</div>" + (r.explanation ? '<p class="xs muted" style="line-height:1.5">' + esc(r.explanation) + "</p>" : "") + "</div>";
    }).join("");
  }
  function player() {
    const P = play, t = P.t, back = '<button type="button" class="btn ghost small" id="pl-back" style="padding-left:0;align-self:flex-start">← К тестам</button>';
    if (P.res) {
      const pct = Math.round(P.res.score * 100);
      return back + '<section class="card col result ' + (P.res.passed ? "ok" : "bad") + '" style="align-items:center;text-align:center;gap:10px;padding:32px"><p class="eyebrow">' + esc(t.title) + '</p><p class="head" style="font-size:64px" data-count>' + pct + '%</p><span class="chip ' + (P.res.passed ? "ok" : "bad") + '" style="font-size:13px;padding:6px 14px">' + (P.res.passed ? "Тест сдан" : "Пока не сдан — нужно " + Math.round(P.res.pass_score * 100) + "%") + '</span><p class="small muted">Верных ответов: ' + Object.values(P.res.result).filter((r) => r.ok).length + " из " + t.questions.length + " · попытка " + P.res.attempts + '</p><div class="row" style="gap:8px;justify-content:center">' + (P.res.passed ? "" : '<button type="button" class="btn primary" id="pl-again">Пройти ещё раз</button>') + (t.course_id ? '<button type="button" class="btn" data-reread="' + t.course_id + '">Перечитать материал</button>' : "") + '</div></section><section class="card col" style="gap:14px"><p class="eyebrow">Разбор ответов</p>' + review(t, P.res.result) + "</section>";
    }
    const q = t.questions[P.i], chosen = P.ans[q.id] || [], last = P.i === t.questions.length - 1;
    let h = back + '<section class="card col" style="gap:16px;max-width:760px;width:100%;align-self:center"><div class="row between"><p class="eyebrow">' + esc(t.title) + '</p><span class="xs muted">Вопрос ' + (P.i + 1) + " из " + t.questions.length + '</span></div><div class="prog-track" aria-hidden="true">' + t.questions.map((x, k) => '<span class="' + (k < P.i || (P.ans[x.id] || []).length ? "seg-ok" : k === P.i ? "seg-warn" : "seg-idle") + '" style="animation:none"></span>').join("") + "</div>";
    h += '<h2 class="head" style="font-size:20px;line-height:1.35">' + esc(q.text) + '</h2><p class="xs muted">' + QHINT[q.qtype] + '</p><div class="col" style="gap:8px">' + q.options.map((o, k) => '<button type="button" class="opt' + (chosen.includes(k) ? " on" : "") + '" data-pick="' + k + '" aria-pressed="' + chosen.includes(k) + '"><span class="opt-mark ' + (q.qtype === "multi" ? "sq" : "") + '"></span>' + esc(o) + "</button>").join("") + "</div>";
    h += '<div class="row between"><button type="button" class="btn" id="pl-prev"' + (P.i ? "" : " disabled") + '>Назад</button><button type="button" class="btn primary" id="pl-next"' + (chosen.length ? "" : " disabled") + ">" + (last ? "Завершить тест" : "Дальше") + "</button></div></section>";
    return h;
  }
  function bindPlayer() {
    const P = play, $ = (s) => box.querySelector(s);
    $("#pl-back").addEventListener("click", () => { view = "list"; tab = "tests"; load(); });
    if (P.res) {
      const a = $("#pl-again"); if (a) a.addEventListener("click", () => startTest(P.t.id));
      box.querySelectorAll("[data-reread]").forEach((b) => b.addEventListener("click", () => openReader(+b.dataset.reread)));
      return;
    }
    const q = P.t.questions[P.i];
    box.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => {
      const k = +b.dataset.pick, cur = P.ans[q.id] || [];
      P.ans[q.id] = q.qtype === "multi" ? (cur.includes(k) ? cur.filter((x) => x !== k) : cur.concat(k)) : [k];
      render();
    }));
    $("#pl-prev").addEventListener("click", () => { P.i--; render(); });
    $("#pl-next").addEventListener("click", async () => {
      if (P.i < P.t.questions.length - 1) { P.i++; render(); return; }
      const answers = {};
      P.t.questions.forEach((x) => { const a = P.ans[x.id] || []; answers[x.id] = x.qtype === "multi" ? a : a[0]; });
      P.res = await api("POST", "/api/tests/" + P.t.id + "/answer", { answers });
      render(); window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  function guide() {
    const G = L.guide, g = G[guideI] || { title: "", blocks: [] };
    let h = '<div class="widgets"><nav class="card col" style="flex:1 1 240px;padding:10px;gap:2px" aria-label="Статьи справочника">' + G.map((x, i) => '<button type="button" data-g="' + i + '" aria-current="' + (i === guideI) + '" style="text-align:left;border:0;border-radius:10px;padding:10px;min-height:44px;cursor:pointer;background:' + (i === guideI ? "var(--soft)" : "transparent") + ';font-size:14px"><span class="head" style="font-size:12px;color:var(--accent);margin-right:8px">0' + (i + 1) + "</span>" + esc(x.title) + "</button>").join("") + "</nav>";
    h += '<article class="card col" style="flex:3 1 480px;gap:12px"><p class="eyebrow">0' + (guideI + 1) + '</p><h2 class="head" style="font-size:24px">' + esc(g.title) + "</h2>";
    let table = [];
    const flush = () => { if (table.length) { h += '<div class="scroll-x"><table class="tbl">' + table.filter((r) => !/^\|[-| ]+\|$/.test(r)).map((r, i) => "<tr>" + r.split(/(?<!\\)\|/).slice(1, -1).map((c) => (i ? "<td>" : "<th>") + md(c.trim().replace(/\\\|/g, "|")) + (i ? "</td>" : "</th>")).join("") + "</tr>").join("") + "</table></div>"; table = []; } };
    const md = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, '<code class="formula">$1</code>');
    g.blocks.forEach((b) => {
      if (b.startsWith("|")) { table.push(b); return; }
      flush();
      if (b.startsWith("> ")) h += '<p class="small" style="background:var(--accent-soft);border-radius:12px;padding:12px;color:var(--under-fg)">' + md(b.slice(2)) + "</p>";
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
    const q = $("#m-q"); if (q) q.addEventListener("input", () => { fText = q.value; const pos = q.selectionStart; render(); const n = box.querySelector("#m-q"); n.focus(); n.setSelectionRange(pos, pos); });
    all("[data-fk]").forEach((b) => b.addEventListener("click", () => { fKind = b.dataset.fk; render(); }));
    all("[data-ft]").forEach((b) => b.addEventListener("click", () => { fTag = fTag === b.dataset.ft ? null : b.dataset.ft; render(); }));
    ["#m-new", "#m-new2"].forEach((s) => { const b = $(s); if (b) b.addEventListener("click", () => openEditor(null)); });
    all("[data-edit]").forEach((b) => b.addEventListener("click", () => openEditor(+b.dataset.edit)));
    all("[data-read]").forEach((b) => b.addEventListener("click", () => openReader(+b.dataset.read)));
    all("[data-gen]").forEach((b) => b.addEventListener("click", () => genModal(+b.dataset.gen)));
    const tn = $("#t-new"); if (tn) tn.addEventListener("click", () => genModal(null));
    all("[data-topen]").forEach((b) => b.addEventListener("click", () => { T = L.tests.find((t) => t.id === +b.dataset.topen); view = "test"; render(); window.scrollTo({ top: 0 }); }));
    all("[data-take]").forEach((b) => b.addEventListener("click", () => startTest(+b.dataset.take)));
    all("[data-review]").forEach((b) => b.addEventListener("click", () => { const t = L.tests.find((x) => x.id === +b.dataset.review); play = { t, i: 0, ans: {}, res: { score: t.score, passed: t.passed, pass_score: t.pass_score, attempts: t.attempts, result: t.result } }; view = "take"; render(); }));
    all("[data-assign]").forEach((b) => b.addEventListener("click", () => {
      const c = L.courses.find((x) => x.id === +b.dataset.assign);
      const m = Pulse.modal('<div class="modal" role="dialog" aria-modal="true" aria-label="Назначить материал"><div class="row between"><h2 class="head" style="font-size:18px">Назначить «' + esc(c.title) + '»</h2><button type="button" class="icon-btn" data-close aria-label="Закрыть">×</button></div><p class="small muted">' + (c.audience === "mentor" ? "Наставнику" : c.audience === "all" ? "Стажёру и наставнику" : "Стажёру") + " выбранных пар:</p>" + pairs.map((p) => '<label class="row nowrap small" style="gap:10px;min-height:40px"><input type="checkbox" value="' + p.id + '" style="width:20px;height:20px;accent-color:var(--accent)"><b>' + esc(p.code) + "</b> · " + esc(p.st.label) + "</label>").join("") + '<button type="button" class="btn primary" data-ok style="align-self:flex-start">Назначить</button></div>');
      m.back.querySelector("[data-ok]").onclick = async () => { const ids = Array.from(m.back.querySelectorAll("input:checked")).map((i) => +i.value); const r = await api("POST", "/api/courses/" + c.id + "/assign", { pair_ids: ids, side: c.audience }); m.close(); toast("Назначено парам: " + r.assigned); load(); };
    }));
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
