// Объёмные шары с рельефной решёткой: считаются в Web Worker, рисуются на canvas один раз и берутся из кэша.
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

  // Пиксели шара S×S в RGBA. Считается в Web Worker, чтобы не блокировать страницу.
  function pixels(S, kind, tilt) {
    const r = S / 2, px = new Uint8ClampedArray(S * S * 4);
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
        const back = Math.max(0, -(nx * L[0] + ny * L[1]));
        const rim = Math.pow(1 - nz, 3) * (0.25 + 0.75 * back);
        const ao = 0.5 + 0.5 * h;
        // форма шара — по исходной нормали, рельеф — по возмущённой
        const macro = Math.max(0, nx * L[0] + ny * L[1] + nz * L[2]);
        const lit = (0.12 + 0.88 * Math.pow(macro, 1.1)) * (0.45 + 0.55 * dif) * ao * 1.25;
        const i = (y * S + x) * 4;
        px[i] = 8 + 80 * lit + 160 * spec + 30 * rim;
        px[i + 1] = 12 + 112 * lit + 170 * spec + 55 * rim;
        px[i + 2] = 34 + 218 * lit + 190 * spec + 120 * rim;
        px[i + 3] = 255 * clamp((1 - Math.sqrt(d2)) * r * 0.9);
      }
    }
    return px;
  }

  // Внутри Web Worker: только считаем пиксели и отдаём буфер без копирования.
  if (typeof document === "undefined") {
    self.onmessage = (e) => {
      const { id, S, kind, tilt } = e.data, px = pixels(S, kind, tilt);
      self.postMessage({ id, px }, [px.buffer]);
    };
    return;
  }

  const SRC = document.currentScript && document.currentScript.src;
  let worker = null, seq = 0;
  const waiting = new Map();
  try { worker = SRC && window.Worker ? new Worker(SRC) : null; } catch (e) { worker = null; }
  if (worker) {
    worker.onmessage = (e) => { const done = waiting.get(e.data.id); waiting.delete(e.data.id); if (done) done(e.data.px); };
    worker.onerror = () => { worker = null; waiting.forEach((done) => done(null)); waiting.clear(); };
  }
  function compute(S, kind, tilt) {
    if (!worker) return Promise.resolve(pixels(S, kind, tilt));
    return new Promise((resolve) => {
      const id = ++seq;
      waiting.set(id, (px) => resolve(px || pixels(S, kind, tilt)));
      worker.postMessage({ id, S, kind, tilt });
    });
  }

  const pending = new Map();
  function render(size, kind, tilt) {
    const key = size + "|" + kind + "|" + tilt;
    if (cache.has(key)) return Promise.resolve(cache.get(key));
    if (pending.has(key)) return pending.get(key);
    const ss = 2, S = size * ss;
    const job = compute(S, kind, tilt).then((px) => {
      const cv = document.createElement("canvas");
      cv.width = cv.height = S;
      cv.getContext("2d").putImageData(new ImageData(px, S, S), 0, 0);
      const out = document.createElement("canvas");
      out.width = out.height = size;
      const o = out.getContext("2d");
      o.imageSmoothingQuality = "high";
      o.drawImage(cv, 0, 0, size, size);
      cache.set(key, out);
      pending.delete(key);
      return out;
    });
    pending.set(key, job);
    return job;
  }

  const sizeOf = (el, css) => Math.min(1100, Math.round(css * Math.min(2, window.devicePixelRatio || 1) / 40) * 40);
  const keyOf = (el) => [sizeOf(el, Number(el.dataset.size) || el.clientWidth || 400), el.dataset.orb || "lattice", Number(el.dataset.tilt || 0.4)];
  function paint(el, src) {
    if (!el.isConnected) return;
    const cv = document.createElement("canvas");
    cv.width = cv.height = src.width;
    cv.getContext("2d").drawImage(src, 0, 0);
    cv.setAttribute("aria-hidden", "true");
    el.textContent = "";
    el.appendChild(cv);
    el.classList.add("orb-ready");
  }
  // Шары рисуются по одному: каждый появляется, как только готов, страница не ждёт остальных.
  const queue = [];
  let busy = false;
  function pump() {
    if (busy || !queue.length) return;
    busy = true;
    const el = queue.shift();
    const [size, kind, tilt] = keyOf(el);
    render(size, kind, tilt).then((src) => paint(el, src)).finally(() => { busy = false; pump(); });
  }
  function scan(root) {
    (root.querySelectorAll ? root : document).querySelectorAll(".orb:not([data-orb-q])").forEach((el) => {
      el.setAttribute("data-orb-q", "1");
      // уже нарисованный шар того же вида — сразу из кэша, без очереди
      const key = keyOf(el).join("|");
      if (cache.has(key)) paint(el, cache.get(key));
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
