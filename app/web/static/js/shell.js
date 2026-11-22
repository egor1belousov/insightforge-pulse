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
