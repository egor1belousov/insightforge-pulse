// Программа (HR): пары и подбор наставника, участники и приглашения, поток и итоги.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page");
  let tab = new URLSearchParams(location.search).get("tab") || "pairs", O = null, D = null, picking = null, invites = [];
  const OUT = [["stay", "В штате", "#1F8F4E"], ["no", "Не оставлен", "#5B6478"], ["left", "Ушёл сам", "#C93434"]];

  async function load() { [O, D, invites] = await Promise.all([api("GET", "/api/program/overview"), api("GET", "/api/dashboard"), api("GET", "/api/auth/invites")]); render(); }

  function render() {
    let h = '<section class="hero"><div class="sphere orb" data-orb="dots" data-size="560" aria-hidden="true"></div><p class="tagline">Программа · ' + esc(D.months[D.months.length - 1].full) + '</p><h1>Пары, участники и итоги потока</h1><p class="sub">Формируйте пары, приглашайте людей, меняйте наставника — история пары сохраняется. В конце потока отметьте итоги: они станут метками для будущей модели риска ухода.</p></section>';
    h += '<div class="seg" role="tablist">' + [["pairs", "Пары"], ["people", "Участники"], ["flow", "Поток и итоги"]].map(([k, n]) => '<button type="button" role="tab" data-tab="' + k + '" aria-selected="' + (tab === k) + '">' + n + "</button>").join("") + "</div>";
    if (tab === "pairs") h += pairsTab(); else if (tab === "people") h += peopleTab(); else h += flowTab();
    box.innerHTML = h; bind();
  }
  function pairsTab() {
    let h = '<div class="widgets"><section class="card col" style="flex:2 1 520px"><p class="eyebrow">Пары программы</p><div class="scroll-x"><table class="tbl"><thead><tr><th>Пара</th><th>Стажёр</th><th>Наставник</th><th>Подразделение</th><th>Состояние</th><th>Индекс</th><th></th></tr></thead><tbody>';
    D.pairs.forEach((p) => { h += '<tr><td><a href="/pairs?id=' + p.id + '"><b>' + esc(p.code) + "</b></a></td><td>" + esc(p.intern) + "</td><td>" + esc(p.mentor) + "</td><td>" + esc(p.dept) + '</td><td><span class="chip" style="background:' + p.st.bg + ";color:" + p.st.fg + '">' + esc(p.st.label) + "</span></td><td><b>" + (p.health ?? "—") + '</b></td><td><button type="button" class="btn small" data-swap="' + p.id + '">Сменить наставника</button></td></tr>'; });
    h += "</tbody></table></div></section>";
    h += '<section class="card col" style="flex:1 1 300px"><p class="eyebrow">Стажёры без пары</p>' + (O.unpaired.length ? O.unpaired.map((u) => '<div class="list-row"><span class="grow small"><b>' + esc(u.external_id) + "</b> · " + esc(u.department || "—") + '</span><button type="button" class="btn primary small" data-pick="' + u.id + '">Подобрать наставника</button></div>').join("") : '<p class="small muted">Все стажёры в парах.</p>');
    h += '<p class="eyebrow" style="margin-top:8px">Свободные наставники</p>' + (O.free_mentors.length ? O.free_mentors.map((m) => '<div class="list-row small"><b>' + esc(m.external_id) + "</b>&nbsp;· " + esc(m.department || "—") + "</div>").join("") : '<p class="small muted">Свободных нет.</p>') + "</section></div>";
    if (picking) {
      h += '<section class="card col" style="border:1px solid var(--accent)"><div class="row between"><div><p class="eyebrow">' + esc(picking.title) + '</p><p class="small muted">' + esc(picking.sub) + '</p></div><button type="button" class="btn small" id="pick-cancel">Отмена</button></div>';
      h += picking.items.length ? picking.items.map((c) => '<div class="list-row"><span class="grow"><b class="small">' + esc(c.external_id) + '</b> <span class="xs muted">· ' + esc(c.reasons.join(" · ")) + '</span><span class="bar" style="display:block;margin-top:6px;max-width:320px"><span style="width:' + c.score + '%;background:var(--accent)"></span></span></span><span class="head" style="font-size:15px">' + c.score + '</span><button type="button" class="btn primary small" data-choose="' + c.id + '">Выбрать</button></div>').join("") : '<p class="small muted">Подходящих наставников нет — пригласите нового в разделе «Участники».</p>';
      h += "</section>";
    }
    return h;
  }
  function peopleTab() {
    let h = '<section class="card col"><p class="eyebrow">Пригласить</p><div class="row"><label class="sr-only" for="inv-email">Рабочая почта</label><input class="input small" id="inv-email" type="email" placeholder="s-107@pulse.demo" style="flex:1 1 220px;width:auto"><div class="seg" id="inv-role">' + [["intern", "Стажёр"], ["mentor", "Наставник"], ["lead", "Руководитель"]].map(([k, n], i) => '<button type="button" data-role="' + k + '" aria-pressed="' + (i === 0) + '">' + n + "</button>").join("") + '</div><label class="sr-only" for="inv-ext">ID в данных</label><input class="input small" id="inv-ext" placeholder="ID в данных, например С-107" style="flex:0 1 220px;width:auto"><button type="button" class="btn primary" id="inv-send">Отправить приглашение</button></div><p class="xs muted">Ссылка действует 7 дней и одноразовая. В демо-режиме письмо не уходит — ссылка появится ниже.</p><div id="inv-link"></div></section>';
    h += '<section class="card col"><p class="eyebrow">Участники</p><div class="scroll-x"><table class="tbl"><thead><tr><th>ID</th><th>Роль</th><th>Подразделение</th><th>Аккаунт</th><th>Анкета без входа</th></tr></thead><tbody>';
    O.people.forEach((p) => { h += "<tr><td><b>" + esc(p.external_id) + "</b></td><td>" + (p.side === "intern" ? "Стажёр" : "Наставник") + "</td><td>" + esc(p.department || "—") + "</td><td>" + (p.joined ? '<span class="chip ok">' + esc(p.email || "вошёл") + "</span>" : '<span class="chip">нет</span>') + '</td><td><button type="button" class="btn ghost small" data-copy="' + esc(location.origin + p.survey) + '">Скопировать ссылку</button></td></tr>'; });
    h += "</tbody></table></div></section>";
    if (invites.length) h += '<section class="card col"><p class="eyebrow">Приглашения</p>' + invites.map((i) => '<div class="list-row small"><span class="grow"><b>' + esc(i.email) + "</b> · " + esc(i.role) + (i.external_id ? " · " + esc(i.external_id) : "") + '</span><span class="chip ' + (i.used ? "ok" : "warn") + '">' + (i.used ? "принято" : "ждём входа") + "</span>" + (i.used ? "" : '<button type="button" class="btn ghost small" data-copy="' + esc(location.origin + i.link) + '">Ссылка</button>') + "</div>").join("") + "</section>";
    return h;
  }
  function flowTab() {
    const set = O.outcomes.filter((o) => o.outcome).length;
    let h = '<section class="card col"><div class="row between"><p class="eyebrow">Итоги стажировки · отмечено ' + set + " из " + O.outcomes.length + '</p></div><p class="small muted">Итоги со временем дадут настоящую проверку детектора: совпадали ли сигналы с тем, кто ушёл.</p>';
    O.outcomes.forEach((o) => { h += '<div class="list-row"><span class="grow small"><b>' + esc(o.intern) + '</b> <span class="muted">· ' + esc(o.code) + " · " + esc(o.dept || "") + '</span></span><span class="row" style="gap:6px">' + OUT.map(([k, n, c]) => '<button type="button" class="pill" data-out="' + k + '" data-pid="' + o.pair_id + '" aria-pressed="' + (o.outcome === k) + '"' + (o.outcome === k ? ' style="background:' + c + ";border-color:" + c + '"' : "") + ">" + n + "</button>").join("") + "</span></div>"; });
    return h + "</section>";
  }
  function bind() {
    box.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; picking = null; render(); }));
    box.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", async () => {
      const u = O.unpaired.find((x) => x.id === +b.dataset.pick);
      picking = { mode: "new", target: u.id, title: "Наставник для " + u.external_id, sub: "Подразделение: " + (u.department || "—") + ". Ранжирование: подразделение, загрузка, история сигналов. Решение — за вами.", items: await api("GET", "/api/participants/" + u.id + "/candidates") }; render();
    }));
    box.querySelectorAll("[data-swap]").forEach((b) => b.addEventListener("click", async () => {
      const p = D.pairs.find((x) => x.id === +b.dataset.swap);
      picking = { mode: "swap", target: p.id, title: "Замена наставника · " + p.code, sub: "Сейчас: " + p.mentor + ". История пары сохранится, на графиках появится отметка смены.", items: await api("GET", "/api/pairs/" + p.id + "/candidates") }; render();
    }));
    const pc = box.querySelector("#pick-cancel"); if (pc) pc.addEventListener("click", () => { picking = null; render(); });
    box.querySelectorAll("[data-choose]").forEach((b) => b.addEventListener("click", async () => {
      try {
        if (picking.mode === "new") { const r = await api("POST", "/api/pairs", { intern_id: picking.target, mentor_id: +b.dataset.choose }); toast("Создана пара " + r.code); }
        else { await api("POST", "/api/pairs/" + picking.target + "/mentor", { mentor_id: +b.dataset.choose, period: D.last + 1 }); toast("Наставник сменится со следующего месяца. История сохранена"); }
        picking = null; load();
      } catch (e) { toast(e.message); }
    }));
    let role = "intern";
    box.querySelectorAll("#inv-role [data-role]").forEach((b) => b.addEventListener("click", () => { role = b.dataset.role; box.querySelectorAll("#inv-role [data-role]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); }));
    const send = box.querySelector("#inv-send");
    if (send) send.addEventListener("click", async () => {
      try {
        const r = await api("POST", "/api/auth/invites", { email: box.querySelector("#inv-email").value, role, external_id: box.querySelector("#inv-ext").value || null });
        box.querySelector("#inv-link").innerHTML = '<div class="form-ok">Приглашение создано: <a href="' + esc(r.link) + '">' + esc(location.origin + r.link) + "</a></div>";
        toast("Приглашение отправлено: " + r.email); invites = await api("GET", "/api/auth/invites");
      } catch (e) { toast(e.message); }
    });
    box.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => { try { await navigator.clipboard.writeText(b.dataset.copy); toast("Ссылка скопирована"); } catch (e) { prompt("Ссылка:", b.dataset.copy); } }));
    box.querySelectorAll("[data-out]").forEach((b) => b.addEventListener("click", async () => {
      const on = b.getAttribute("aria-pressed") === "true";
      await api("POST", "/api/pairs/" + b.dataset.pid + "/outcome", { outcome: on ? null : b.dataset.out }); O = await api("GET", "/api/program/overview"); render();
    }));
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
