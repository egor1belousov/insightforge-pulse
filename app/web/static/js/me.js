// Моя стажировка / Моя пара: своя анкета, свои оценки по темам, темы для разговора, запрос к HR.
(function () {
  "use strict";
  const { api, esc, toast } = window.Pulse;
  const box = document.getElementById("page");
  let D = null, reopen = false;
  const TALK = ["Нагрузка", "Отношения в паре", "Обучение", "Перспективы", "Другое"];

  async function load() { D = await api("GET", "/api/me"); render(); }
  function render() {
    const isM = D.participant.side === "mentor";
    let h = '<section class="hero"><div class="sphere" aria-hidden="true"></div><p class="tagline">' + (isM ? "Наставник " : "Стажёр ") + esc(D.participant.external_id) + (D.other ? " · " + (isM ? "стажёр " : "наставник ") + esc(D.other) : "") + "</p><h1>" + (isM ? "Ваша пара" : "Ваша стажировка") + ", " + D.month_number + '-й месяц</h1><p class="sub">Ваши ответы видит только HR. ' + (isM ? "Стажёр" : "Наставник") + " их не увидит — так анкеты остаются честными.</p></section>";
    const open = !D.submitted || reopen;
    h += '<div class="widgets"><section class="card col" style="flex:2 1 480px;' + (open ? "border-color:#0A7CD6" : "") + '"><div class="row between"><p class="eyebrow">Анкета за ' + esc(D.period_name) + "</p><span class=\"xs muted\">" + (open ? "ждём ваших ответов" : "следующая — в " + esc(D.next_name.replace(/ь$/, "е"))) + '</span></div><div id="survey-box"></div></section>';
    h += '<section class="card col" style="flex:1 1 300px"><p class="eyebrow">Мои оценки по темам</p>';
    h += D.bars.length ? D.bars.map((b) => '<div><div class="row between small"><span>' + esc(b.name) + "</span><b>" + b.now.toFixed(2) + (b.was != null ? ' <span class="muted" style="font-weight:400">(было ' + b.was.toFixed(2) + ")</span>" : "") + '</b></div><div class="bar" style="margin-top:6px"><span style="width:' + Math.round(b.now * 100) + '%;background:#0A7CD6"></span></div></div>').join("") : '<p class="small muted">Появятся после первой анкеты.</p>';
    h += '<p class="xs muted">Это только ваши оценки. Оценки ' + (isM ? "стажёра" : "наставника") + " вам не показываются.</p></section></div>";
    h += '<div class="widgets"><section class="card col" style="flex:1 1 360px"><p class="eyebrow">Темы для разговора</p>' + (D.talk.length ? D.talk.map((t) => '<div style="background:#F7F8FB;border-radius:12px;padding:12px"><b class="small">' + esc(t.title) + '</b><p class="small muted" style="margin-top:4px;line-height:1.5">' + esc(t.text) + "</p></div>").join("") : '<p class="small muted">Пока всё спокойно.</p>') + "</section>";
    const tr = D.talk_request;
    h += '<section class="card col" style="flex:1 1 360px;' + (tr ? "background:" + (tr.answered ? "#E9F6EE" : "#FFF4E5") : "") + '"><p class="eyebrow">Хочу поговорить с HR</p>';
    if (tr) h += '<p class="small"><b>' + (tr.answered ? esc(tr.answer || "HR назначил встречу") : "Запрос отправлен — HR свяжется в течение 2 рабочих дней") + '</b></p><p class="small muted">Тема: ' + esc(tr.topic) + ". " + (isM ? "Стажёр" : "Наставник") + " об этом не узнает.</p>";
    else h += '<p class="small muted">Нужно поговорить, а до анкеты далеко? Напишите HR напрямую. ' + (isM ? "Стажёр" : "Наставник") + ' не увидит ваш запрос.</p><div class="row" style="gap:6px" id="talk-topics">' + TALK.map((t, i) => '<button type="button" class="pill accent" data-t="' + esc(t) + '" aria-pressed="' + (i === 0) + '">' + esc(t) + '</button>').join("") + '</div><label class="sr-only" for="talk-text">Пара слов</label><textarea class="input" id="talk-text" rows="3" placeholder="Пара слов — по желанию"></textarea><button type="button" class="btn primary" id="talk-send" style="align-self:flex-start">Отправить HR</button>';
    h += "</section></div>";
    box.innerHTML = h;
    const sb = box.querySelector("#survey-box");
    if (open && D.questionnaire) PulseSurvey.render(sb, D.questionnaire, async (answers, comment) => {
      await api("POST", "/api/responses", { answers, comment }); reopen = false;
      toast(comment.trim() ? "Ответы отправлены. Комментарий разобран — HR увидит его в карточке пары" : "Спасибо! Ответы отправлены"); load();
    });
    else if (!D.questionnaire) sb.innerHTML = '<p class="small muted">Анкета ещё не настроена. HR пришлёт её в начале месяца.</p>';
    else sb.innerHTML = '<div class="issue done"><span><b>Анкета получена, спасибо.</b> Сигналы вашей пары пересчитаны.</span></div><button type="button" class="btn small" id="reopen" style="align-self:flex-start">Изменить ответы</button>';
    const ro = box.querySelector("#reopen"); if (ro) ro.addEventListener("click", () => { reopen = true; render(); });
    let topic = TALK[0];
    box.querySelectorAll("#talk-topics [data-t]").forEach((b) => b.addEventListener("click", () => { topic = b.dataset.t; box.querySelectorAll("#talk-topics [data-t]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); }));
    const ts = box.querySelector("#talk-send"); if (ts) ts.addEventListener("click", async () => { await api("POST", "/api/me/talk", { topic, text: box.querySelector("#talk-text").value }); toast("Запрос отправлен HR"); load(); });
  }
  load().catch((e) => { box.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>"; });
})();
