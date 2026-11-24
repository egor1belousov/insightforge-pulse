// ИИ-ассистент: плавающая кнопка и панель чата. Учитывает роль: стороны видят только своё.
(function () {
  "use strict";
  const main = document.getElementById("main");
  if (!main) return;
  const { api, esc } = window.Pulse, role = main.dataset.role, staff = role === "hr" || role === "lead";
  const SUGG = staff ? ["Что делать с П-02?", "Кому помочь первым?", "Что не так с программой?", "Есть риск ухода?"] : ["Когда можно взять отпуск?", "Что мне пройти из курсов?", "Как поговорить с HR?", "Что думает обо мне " + (role === "intern" ? "наставник" : "стажёр") + "?"];
  const greet = staff ? "Привет! Я вижу данные всех пар, методику и регламент. Спросите, что делать с конкретной парой, кому помочь первым или что не так с программой." : "Привет! Я отвечаю по регламенту стажировки и вашим собственным данным. Ответы другой стороны я не показываю.";
  const msgs = [{ who: "ai", text: greet, refs: [] }];
  const fab = document.createElement("button");
  fab.type = "button"; fab.className = "btn primary ai-fab"; fab.id = "chat-fab"; fab.setAttribute("aria-expanded", "false"); fab.setAttribute("aria-label", "Спросить ИИ-ассистента");
  fab.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z"></path></svg><span class="ai-fab-text">Спросить ИИ</span>';
  document.body.appendChild(fab);
  const panel = document.createElement("section");
  panel.setAttribute("aria-label", "ИИ-ассистент"); panel.hidden = true;
  panel.className = "ai-panel";
  panel.innerHTML = '<div style="background:#070A14;color:#fff;padding:14px 16px" class="row between nowrap"><div><b>ИИ-ассистент</b><p class="xs" style="color:#9AA6C6">' + (staff ? "данные пар + методика + регламент" : "регламент + ваши данные") + ' · модель работает локально</p></div><button type="button" class="icon-btn" data-close aria-label="Закрыть" style="background:transparent;color:#fff;border-color:rgba(255,255,255,.3)">×</button></div><div id="chat-log" class="col" style="flex:1;overflow:auto;padding:14px;gap:10px" aria-live="polite"></div><div class="row" id="chat-sugg" style="gap:6px;padding:0 14px 8px"></div><form class="row nowrap" id="chat-form" style="padding:10px 14px 14px;gap:8px;background:var(--card);border-top:1px solid var(--line)"><label class="sr-only" for="chat-in">Вопрос</label><input class="input small" id="chat-in" placeholder="Спросите о паре, программе или регламенте" autocomplete="off"><button type="submit" class="btn primary small">→</button></form>';
  document.body.appendChild(panel);
  const log = panel.querySelector("#chat-log"), input = panel.querySelector("#chat-in");
  function draw() {
    log.innerHTML = msgs.map((m) => '<div style="align-self:' + (m.who === "me" ? "flex-end" : "flex-start") + ";max-width:88%;background:" + (m.who === "me" ? "var(--accent)" : "var(--card)") + ";color:" + (m.who === "me" ? "#fff" : "var(--ink)") + ";border:1px solid " + (m.who === "me" ? "var(--accent)" : "var(--line)") + ";border-radius:" + (m.who === "me" ? "16px 16px 4px 16px" : "16px 16px 16px 4px") + ';padding:10px 12px;font-size:14px;line-height:1.5;white-space:pre-line">' + esc(m.text) + (m.refs && m.refs.length ? '<div class="xs" style="margin-top:6px;color:var(--muted)">Источники: ' + esc(m.refs.join(" · ")) + "</div>" : "") + (m.who === "ai" && m.fb != null ? '<div class="xs" style="margin-top:4px;color:var(--faint)">' + (m.src === "regulations" ? "цитата из регламента" : m.src === "data" ? "ответ из данных системы" : m.fb ? "ответ по правилам" : "ответ ИИ по данным системы") + "</div>" : "") + "</div>").join("");
    log.scrollTop = log.scrollHeight;
    panel.querySelector("#chat-sugg").innerHTML = msgs.length < 3 ? SUGG.map((s) => '<button type="button" class="pill" data-s="' + esc(s) + '">' + esc(s) + "</button>").join("") : "";
    panel.querySelectorAll("[data-s]").forEach((b) => b.addEventListener("click", () => send(b.dataset.s)));
  }
  async function send(text) {
    const t = (text || "").trim(); if (!t) return;
    msgs.push({ who: "me", text: t }); msgs.push({ who: "ai", text: "Думаю…", refs: [] }); input.value = ""; draw();
    try { const r = await api("POST", "/api/assistant", { message: t }); msgs[msgs.length - 1] = { who: "ai", text: r.answer, refs: r.refs, fb: r.fallback, src: r.source }; }
    catch (e) { msgs[msgs.length - 1] = { who: "ai", text: e.message, refs: [] }; }
    draw();
  }
  const toggle = (open) => { panel.hidden = !open; fab.setAttribute("aria-expanded", String(open)); if (open) { draw(); input.focus(); } };
  fab.addEventListener("click", () => toggle(panel.hidden));
  panel.querySelector("[data-close]").addEventListener("click", () => toggle(false));
  panel.querySelector("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) toggle(false); });
  window.PulseChat = { open: () => toggle(true) };
})();
