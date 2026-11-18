// Elevation view: the circuit as a ribbon standing on its real height profile.
// Plain canvas, no 3D library. Drag to turn it.

import { reduced } from "./lib.js";

export function elevation(host, T, colourAt) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "The circuit in three dimensions, showing its real elevation changes");
  host.appendChild(canvas);
  const g = canvas.getContext("2d");
  const n = T.x.length;
  const mx = (Math.min(...T.x) + Math.max(...T.x)) / 2, my = (Math.min(...T.y) + Math.max(...T.y)) / 2;
  const X = T.x.map((v) => v - mx), Y = T.y.map((v) => v - my), Z = T.z;
  const radius = Math.max(...X.map((x, i) => Math.hypot(x, Y[i])));
  const rise = Math.max(...Z) || 1;
  // Real height changes are small next to a circuit's length, so they are
  // exaggerated to be visible. The factor is shown beside the view.
  const ex = Math.max(1, Math.round((0.16 * radius) / rise));
  let yaw = -0.45, pitch = 0.6, W = 0, H = 0, scale = 1, car = null, colour = colourAt, running = false, auto = !reduced, last = null;

  const proj = (x, y, z) => {
    const c = Math.cos(yaw), s = Math.sin(yaw), xr = x * c - y * s, yr = x * s + y * c;
    return [W / 2 + xr * scale, H * 0.56 - (yr * Math.sin(pitch) + z * ex * Math.cos(pitch)) * scale, yr];
  };
  function resize() {
    const dpr = Math.min(2, devicePixelRatio || 1);
    W = host.clientWidth; H = Math.round(W * 0.68);
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    scale = Math.min((W / 2 - 24) / radius, (H * 0.46) / (radius * Math.sin(pitch) + rise * ex * Math.cos(pitch)));
    draw();
  }
  function draw() {
    if (!W) return;
    g.clearRect(0, 0, W, H);
    const top = new Array(n), base = new Array(n);
    for (let i = 0; i < n; i++) { top[i] = proj(X[i], Y[i], Z[i]); base[i] = proj(X[i], Y[i], 0); }
    // footprint on the ground
    g.beginPath();
    base.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
    g.closePath();
    g.strokeStyle = "rgba(244,241,234,.10)"; g.lineWidth = 1; g.stroke();
    // far side first, so nearer walls cover it
    const order = [...Array(n).keys()].sort((a, b) => top[b][2] - top[a][2]);
    g.lineCap = "round";
    for (const i of order) {
      const j = (i + 1) % n, col = colour(i);
      g.beginPath();
      g.moveTo(top[i][0], top[i][1]); g.lineTo(top[j][0], top[j][1]); g.lineTo(base[j][0], base[j][1]); g.lineTo(base[i][0], base[i][1]);
      g.closePath();
      g.globalAlpha = 0.2; g.fillStyle = col; g.fill();
      g.globalAlpha = 1; g.strokeStyle = col; g.lineWidth = 3.2;
      g.beginPath(); g.moveTo(top[i][0], top[i][1]); g.lineTo(top[j][0], top[j][1]); g.stroke();
    }
    g.font = '600 11px "JetBrains Mono", monospace'; g.textAlign = "center";
    for (const c of T.corners) {
      const p = top[c.i % n];
      g.fillStyle = "#7c7a73"; g.fillText(c.label, p[0], p[1] - 9);
    }
    const s0 = top[0];
    g.strokeStyle = "#f4f1ea"; g.lineWidth = 2;
    g.beginPath(); g.moveTo(s0[0], s0[1]); g.lineTo(s0[0], s0[1] - 22); g.stroke();
    g.fillStyle = "#f4f1ea"; g.font = '700 10px "Archivo", sans-serif'; g.fillText("S/F", s0[0], s0[1] - 27);
    if (car) {
      const i = Math.floor(car.fi) % n, j = (i + 1) % n, u = car.fi - Math.floor(car.fi);
      const p = proj(X[i] + (X[j] - X[i]) * u, Y[i] + (Y[j] - Y[i]) * u, Z[i] + (Z[j] - Z[i]) * u);
      g.globalAlpha = 0.25; g.fillStyle = car.colour; g.beginPath(); g.arc(p[0], p[1], 13, 0, 7); g.fill();
      g.globalAlpha = 1; g.beginPath(); g.arc(p[0], p[1], 6, 0, 7); g.fill();
      g.strokeStyle = "#f4f1ea"; g.lineWidth = 2; g.stroke();
    }
  }
  function tick(now) {
    if (!running) return;
    if (auto && last != null) yaw += ((now - last) / 1000) * 0.1;
    last = now;
    draw();
    requestAnimationFrame(tick);
  }
  let drag = null;
  canvas.style.touchAction = "pan-y";
  canvas.style.cursor = "grab";
  canvas.addEventListener("pointerdown", (ev) => { drag = [ev.clientX, ev.clientY, yaw, pitch]; auto = false; canvas.setPointerCapture(ev.pointerId); });
  canvas.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    yaw = drag[2] + (ev.clientX - drag[0]) * 0.008;
    pitch = Math.min(1.25, Math.max(0.2, drag[3] + (ev.clientY - drag[1]) * 0.006));
    if (!running) draw();
  });
  canvas.addEventListener("pointerup", () => { drag = null; });
  new ResizeObserver(resize).observe(host);

  return {
    exaggeration: ex, rise,
    setColour(fn) { colour = fn; if (!running) draw(); },
    setCar(fi, col) { car = { fi, colour: col }; },
    start() { if (!running) { running = true; last = null; resize(); requestAnimationFrame(tick); } },
    stop() { running = false; },
    draw,
  };
}
