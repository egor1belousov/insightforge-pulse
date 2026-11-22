// Верхняя панель: меню профиля, уведомления, выход.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  function pop(btnId, popId) {
    const b = $(btnId), p = $(popId);
    if (!b || !p) return;
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = p.hidden;
      document.querySelectorAll(".popover").forEach((x) => (x.hidden = true));
      document.querySelectorAll("[aria-expanded]").forEach((x) => x.setAttribute("aria-expanded", "false"));
      p.hidden = !open; b.setAttribute("aria-expanded", String(open));
      if (open && popId === "notif-pop") window.dispatchEvent(new Event("pulse:notif-open"));
    });
  }
  pop("menu-btn", "menu-pop");
  pop("notif-btn", "notif-pop");
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".popover")) document.querySelectorAll(".popover").forEach((x) => (x.hidden = true));
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".popover").forEach((x) => (x.hidden = true)); });
  const lo = $("logout-btn");
  if (lo) lo.addEventListener("click", async () => { await Pulse.api("POST", "/api/auth/logout"); location.href = "/login"; });
})();

// Уведомления и живые события (SSE) для HR и руководителя.
(function () {
  "use strict";
  const main = document.getElementById("main");
  if (!main) return;
  const role = main.dataset.role, staff = role === "hr" || role === "lead";
  const list = document.getElementById("notif-list"), cnt = document.getElementById("notif-count");
  async function loadNotif() {
    try {
      const n = await Pulse.api("GET", "/api/notifications");
      cnt.hidden = !n.unread; cnt.textContent = n.unread;
      list.innerHTML = n.items.length ? n.items.map((it) => '<a class="item" href="' + Pulse.esc(it.link || "#") + '"><span class="dot" style="margin-top:6px;background:' + (it.level === "warn" ? "#E38B00" : it.read ? "#B0B7C6" : "#0A7CD6") + '"></span><span class="col" style="gap:2px"><b class="small">' + Pulse.esc(it.title) + '</b><span class="xs muted">' + Pulse.esc(it.sub) + "</span></span></a>").join("") : '<p class="small muted" style="padding:10px">Новых уведомлений нет.</p>';
    } catch (e) { /* без уведомлений страница работает */ }
  }
  loadNotif();
  window.addEventListener("pulse:notif-open", async () => { await Pulse.api("POST", "/api/notifications/read"); cnt.hidden = true; });
  window.PulseShell = { loadNotif };
  if (!staff || !window.EventSource) return;
  const es = new EventSource("/api/events");
  es.addEventListener("pair_updated", (e) => {
    const d = JSON.parse(e.data);
    Pulse.toast(d.message);
    loadNotif();
    window.dispatchEvent(new CustomEvent("pulse:pair-updated", { detail: d }));
  });
  es.addEventListener("data_imported", (e) => { window.dispatchEvent(new CustomEvent("pulse:data-imported", { detail: JSON.parse(e.data) })); });
  es.addEventListener("talk_request", (e) => { const d = JSON.parse(e.data); Pulse.toast(d.who + " просит разговор с HR · тема: " + d.topic); loadNotif(); });
})();
