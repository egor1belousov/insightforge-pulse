// Объёмные шары с рельефной решёткой: рисуются на canvas один раз и берутся из кэша.
// Разметка: <div class="orb" data-orb="lattice|mesh|dots" data-size="520" data-tilt="0.4"></div>
(function () {
  "use strict";
  const cache = new Map();
  const TAU = Math.PI * 2;
  const L = norm([-0.62, -0.66, 0.42]); // свет сверху слева
  const H = norm([L[0], L[1], L[2] + 1]); // полувектор для блика

  function norm(v) { const l = Math.hypot(v[0], v[1], v[2]); return [v[0] / l, v[1] / l, v[2] / l]; }
  const clamp = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const frac = (x) => x - Math.floor(x);

  // Высота рельефа в точке (u, v) сферы: 0 — канавка, 1 — вершина.
  const PATTERNS = {
    lattice(u, v) { // ромбическая решётка с выпуклыми ячейками
      const a = frac(u * 46 + v * 23), b = frac(u * 46 - v * 23);
      const e = Math.min(a, 1 - a, b, 1 - b) * 2;
      return smooth(0.08, 0.7, e);
    },
    mesh(u, v) { // тонкая проволочная сетка
      const a = frac(u * 64), b = frac(v * 34);
      const d = Math.min(a, 1 - a, b, 1 - b);
      return 1 - smooth(0.04, 0.16, d);
    },
    dots(u, v) { // мелкие выпуклые точки
      const a = frac(u * 90) - 0.5, b = frac(v * 46) - 0.5;
      return 1 - smooth(0.18, 0.42, Math.hypot(a, b));
    },
  };

  function render(size, kind, tilt) {
    const key = size + "|" + kind + "|" + tilt;
    if (cache.has(key)) return cache.get(key);
    const ss = 2, S = size * ss, r = S / 2, cv = document.createElement("canvas");
    cv.width = cv.height = S;
    const ctx = cv.getContext("2d"), img = ctx.createImageData(S, S), px = img.data;
    const pat = PATTERNS[kind] || PATTERNS.lattice, ct = Math.cos(tilt), st = Math.sin(tilt), eps = 0.0025;
    for (let y = 0; y < S; y++) {
      const ny = (y + 0.5 - r) / r;
      for (let x = 0; x < S; x++) {
        const nx = (x + 0.5 - r) / r, d2 = nx * nx + ny * ny;
        if (d2 >= 1) continue;
        const nz = Math.sqrt(1 - d2);
        // координаты текстуры в повёрнутой системе
        const Y = ny * ct - nz * st, Z = ny * st + nz * ct;
        const u = Math.atan2(nx, Z) / TAU + 0.5, v = Math.acos(Math.max(-1, Math.min(1, -Y))) / Math.PI;
        const h = pat(u, v), hu = pat(u + eps, v) - h, hv = pat(u, v + eps) - h;
        // возмущённая нормаль: рельеф решётки
        const k = 0.9 * Math.sqrt(Math.max(0.15, 1 - Y * Y));
        const n = norm([nx - hu * k * 9, ny - hv * 9, nz]);
        const dif = Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2]);
        const spec = Math.pow(Math.max(0, n[0] * H[0] + n[1] * H[1] + n[2] * H[2]), 38);
        // контровой свет только с теневой стороны, основной — сверху слева
        const back = Math.max(0, -(nx * L[0] + ny * L[1])) ;
        const rim = Math.pow(1 - nz, 3) * (0.25 + 0.75 * back);
        const ao = 0.5 + 0.5 * h;
        // форма шара — по исходной нормали, рельеф — по возмущённой
        const macro = Math.max(0, nx * L[0] + ny * L[1] + nz * L[2]);
        const lit = (0.12 + 0.88 * Math.pow(macro, 1.1)) * (0.45 + 0.55 * dif) * ao * 1.25;
        let R = 8 + 80 * lit + 160 * spec + 30 * rim;
        let G = 12 + 112 * lit + 170 * spec + 55 * rim;
        let B = 34 + 218 * lit + 190 * spec + 120 * rim;
        const edge = clamp((1 - Math.sqrt(d2)) * r * 0.9);
        const i = (y * S + x) * 4;
        px[i] = R > 255 ? 255 : R; px[i + 1] = G > 255 ? 255 : G; px[i + 2] = B > 255 ? 255 : B; px[i + 3] = 255 * edge;
      }
    }
    ctx.putImageData(img, 0, 0);
    const out = document.createElement("canvas");
    out.width = out.height = size;
    const o = out.getContext("2d");
    o.imageSmoothingQuality = "high";
    o.drawImage(cv, 0, 0, size, size);
    cache.set(key, out);
    return out;
  }

  const queue = [];
  let busy = false;
  function pump() {
    if (busy || !queue.length) return;
    busy = true;
    const el = queue.shift();
    (window.requestIdleCallback || ((f) => setTimeout(f, 16)))(() => {
      try { paint(el); } finally { busy = false; pump(); }
    });
  }
  function paint(el) {
    if (!el.isConnected) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const css = Number(el.dataset.size) || el.clientWidth || 400;
    const size = Math.min(1100, Math.round(css * dpr / 40) * 40);
    const src = render(size, el.dataset.orb || "lattice", Number(el.dataset.tilt || 0.4));
    const cv = document.createElement("canvas");
    cv.width = cv.height = size;
    cv.getContext("2d").drawImage(src, 0, 0);
    cv.setAttribute("aria-hidden", "true");
    el.textContent = "";
    el.appendChild(cv);
    el.classList.add("orb-ready");
  }
  function scan(root) {
    (root.querySelectorAll ? root : document).querySelectorAll(".orb:not([data-orb-q])").forEach((el) => {
      el.setAttribute("data-orb-q", "1");
      // уже нарисованный шар того же вида — сразу из кэша, без очереди
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const size = Math.min(1100, Math.round((Number(el.dataset.size) || 400) * dpr / 40) * 40);
      if (cache.has(size + "|" + (el.dataset.orb || "lattice") + "|" + Number(el.dataset.tilt || 0.4))) paint(el);
      else { queue.push(el); pump(); }
    });
  }
  function start() {
    scan(document);
    new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) scan(n.parentNode || n); }))).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  window.PulseOrbs = { render };
})();
