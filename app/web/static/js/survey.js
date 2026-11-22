// Форма анкеты: используется на странице по ссылке и в «Моя стажировка».
(function () {
  "use strict";
  const { esc } = window.Pulse;

  function scaleOptions(q) {
    if (q.labels && q.labels.length > 2) return q.labels.map((l) => ({ v: l, t: l }));
    const lo = q.min == null ? 1 : q.min, hi = q.max == null ? 5 : q.max, out = [];
    for (let v = lo; v <= hi; v++) out.push({ v: String(v), t: String(v) });
    return out;
  }

  // Рисует анкету в контейнере; onSubmit(answers, comment) возвращает Promise.
  function render(box, questionnaire, onSubmit) {
    const qs = questionnaire.questions;
    const answers = {};
    let h = '<form class="col" novalidate style="gap:14px">';
    qs.filter((q) => q.qtype !== "text").forEach((q, i) => {
      const opts = scaleOptions(q);
      h += '<fieldset class="card col" style="gap:10px; margin:0"><legend class="sr-only">' + esc(q.text) + "</legend>";
      h += '<p style="font-weight:600">' + (i + 1) + ". " + esc(q.text) + "</p>";
      h += '<div class="row" role="radiogroup" aria-label="' + esc(q.text) + '" style="gap:6px">';
      opts.forEach((o) => {
        h += '<button type="button" class="pill" style="min-width:44px;min-height:44px" data-q="' + q.id + '" data-v="' + esc(o.v) + '" role="radio" aria-checked="false">' + esc(o.t) + "</button>";
      });
      h += "</div>";
      if (!(q.labels && q.labels.length > 2) && q.max != null) h += '<div class="row between xs muted"><span>' + q.min + " — совсем нет</span><span>" + q.max + " — полностью</span></div>";
      h += "</fieldset>";
    });
    const tq = qs.find((q) => q.qtype === "text");
    h += '<div class="field"><label for="sv-comment">' + esc(tq ? tq.text : "Комментарий") + ' <span class="muted">(необязательно)</span></label><textarea class="input" id="sv-comment" placeholder="Что получается, что мешает, о чём хотите сказать"></textarea></div>';
    h += '<div class="form-error" role="alert" hidden></div>';
    h += '<button type="submit" class="btn primary" style="min-height:50px">Отправить ответы</button>';
    h += '<p class="xs muted">Ваши ответы видит только HR. Другая сторона пары их не увидит.</p></form>';
    box.innerHTML = h;
    const form = box.querySelector("form"), err = box.querySelector(".form-error");
    box.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => {
      answers[b.dataset.q] = b.dataset.v;
      box.querySelectorAll('[data-q="' + b.dataset.q + '"]').forEach((x) => { const on = x === b; x.setAttribute("aria-checked", String(on)); x.setAttribute("aria-pressed", String(on)); });
    }));
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); err.hidden = true;
      const need = qs.filter((q) => q.qtype !== "text" && !answers[q.id]).length;
      if (need) { err.textContent = "Ответьте на все вопросы: осталось " + need + "."; err.hidden = false; return; }
      const btn = form.querySelector("button[type=submit]"); btn.disabled = true; btn.textContent = "Отправляем…";
      try { await onSubmit(answers, box.querySelector("#sv-comment").value); }
      catch (x) { err.textContent = x.message; err.hidden = false; btn.disabled = false; btn.textContent = "Отправить ответы"; }
    });
  }
  window.PulseSurvey = { render };
})();
