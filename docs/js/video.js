// Video lab: flip through the rendered clip, see where the reader looks and what it read.

import { $, esc, el, context, shell, load, responsive, reduced, params } from "./lib.js";
import { lin, INK, label } from "./charts.js";

const ctx = await context();
shell("video.html", ctx);
const V = await load("video.json");
if (!V) {
  document.querySelector("main").innerHTML = `<div class="wrap"><p class="quiet" style="margin-top:60px">The video lab has not been built for this snapshot.</p></div>`;
  throw new Error("no video data");
}
const { sheet, regions, read, truth, t: T, accuracy: A, clip } = V;
$("eyebrow").innerHTML = [`${V.driver.name}`, `${V.event.name} ${V.event.year}`, `${V.session} · lap ${V.lap}`].map((s) => `<span>${esc(s)}</span>`).join("");

// ---------- flipbook ----------
const canvas = $("frame"), g = canvas.getContext("2d");
canvas.width = sheet.w; canvas.height = sheet.h;
const img = new Image();
img.src = sheet.src;
await img.decode().catch(() => {});

const svg = $("regions");
svg.setAttribute("viewBox", `0 0 ${sheet.w} ${sheet.h}`);
const HUE = { speed: "#f5c400", gear: "#3fd0ff", throttle: "#35d07f", brake: "#ff4d5a", rpm: "#a26bff" };

for (const [name, r] of Object.entries(regions)) {
  const col = HUE[name] ?? "#f4f1ea";
  if (r.kind === "arc") {
    const cx = r.center[0] * sheet.w, cy = r.center[1] * sheet.h;
    for (const rad of [r.r_inner, r.r_outer]) {
      const R = rad * sheet.h, a0 = (r.start_deg * Math.PI) / 180, a1 = (r.end_deg * Math.PI) / 180;
      el("path", { d: `M${cx + R * Math.cos(a0)} ${cy + R * Math.sin(a0)}A${R} ${R} 0 0 ${r.end_deg > r.start_deg ? 1 : 0} ${cx + R * Math.cos(a1)} ${cy + R * Math.sin(a1)}`,
        fill: "none", stroke: col, "stroke-width": 1 }, svg);
    }
  } else {
    const [x0, y0, x1, y1] = r.roi;
    el("rect", { x: x0 * sheet.w, y: y0 * sheet.h, width: (x1 - x0) * sheet.w, height: (y1 - y0) * sheet.h, fill: "none", stroke: col, "stroke-width": 1 }, svg);
  }
}
$("showRegions").addEventListener("change", (ev) => { svg.style.display = ev.target.checked ? "" : "none"; });

const ROWS = [["speed", "Speed", (v) => `${Math.round(v)} km/h`], ["gear", "Gear", (v) => `${Math.round(v)}`],
  ["throttle", "Throttle", (v) => `${Math.round(v)}%`], ["brake", "Brake", (v) => (v > 50 ? "on" : "off")], ["rpm", "Revs", (v) => `${Math.round(v / 10) * 10}`]];
$("readout").innerHTML = `<thead><tr><th></th><th>Read</th><th>Truth</th><th></th></tr></thead><tbody>${ROWS.map(([k, name]) =>
  `<tr style="--team:${HUE[k]}"><th><i></i>${name}</th><td class="t-num" id="rd-${k}"></td><td class="t-num" id="tr-${k}"></td><td id="ok-${k}"></td></tr>`).join("")}</tbody>`;
const close = { speed: 2, gear: 0.5, throttle: 5, brake: 50, rpm: 400 };

let k = 0, heads = [];
function show(index) {
  k = Math.max(0, Math.min(sheet.frames.length - 1, index));
  const f = sheet.frames[k];
  g.drawImage(img, (k % sheet.cols) * sheet.w, Math.floor(k / sheet.cols) * sheet.h, sheet.w, sheet.h, 0, 0, sheet.w, sheet.h);
  $("clock").textContent = `${T[f].toFixed(2)} s`;
  for (const [key, , fmt] of ROWS) {
    const a = read[key][f], b = truth[key][f];
    $(`rd-${key}`).textContent = a == null ? "-" : fmt(a);
    $(`tr-${key}`).textContent = b == null ? "-" : fmt(b);
    const ok = a != null && b != null && Math.abs(a - b) <= close[key];
    $(`ok-${key}`).textContent = ok ? "match" : "differs";
    $(`ok-${key}`).className = ok ? "is-ok" : "is-off";
  }
  heads.forEach((fn) => fn(f));
}

// ---------- traces: read against truth ----------
const PANELS = [["speed", "Speed (km/h)", 170], ["throttle", "Throttle (%)", 80], ["gear", "Gear", 70]];
responsive($("trace"), (W) => {
  const host = $("trace");
  host.innerHTML = `<div class="keys"><span class="key"><i style="background:#a26bff;opacity:.55;height:6px"></i>Telemetry (truth)</span><span class="key"><i style="background:#f4f1ea;height:2px"></i>Read from video</span></div>`;
  heads = [];
  const m = { l: 44, r: 14, gap: 24 }, H = PANELS.reduce((s, p) => s + p[2] + m.gap, 0) + 20, n = T.length;
  const s = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": "Values read from the video against the telemetry it was rendered from" }, host);
  const x = lin(0, n - 1, m.l, W - m.r);
  let top = 6;
  for (const [key, title, h] of PANELS) {
    const y0 = top + 14, y1 = top + h, vals = [...truth[key], ...read[key]].filter((v) => v != null);
    const hi = Math.max(...vals), lo = key === "speed" ? Math.min(...vals) * 0.9 : 0, y = lin(lo, hi, y1, y0);
    label(s, title.toUpperCase(), { x: m.l, y: top + 6, class: "ax ax--cap" });
    for (const v of [lo, hi]) label(s, Math.round(v), { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" });
    const d = (arr, step) => arr.map((v, i) => (step && i ? `H${x(i).toFixed(1)}V${y(v).toFixed(1)}` : `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)).join("");
    // truth is drawn wide underneath so a perfect match still shows both
    el("path", { d: d(truth[key], key === "gear"), fill: "none", stroke: "#a26bff", "stroke-width": 6, opacity: 0.55, "stroke-linejoin": "round" }, s);
    el("path", { d: d(read[key], key === "gear"), fill: "none", stroke: INK.paper, "stroke-width": 1.5, "stroke-linejoin": "round" }, s);
    top += h + m.gap;
  }
  for (let sec = 5; sec < T[n - 1]; sec += 5) label(s, `${sec} s`, { x: x(sec * clip.fps), y: H - 4, "text-anchor": "middle" });
  const head = el("line", { y1: 8, y2: H - 20, stroke: INK.paper, "stroke-width": 1.5 }, s);
  heads.push((f) => { head.setAttribute("x1", x(f)); head.setAttribute("x2", x(f)); });
  const hit = el("rect", { x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent", style: "cursor:ew-resize" }, s);
  const pick = (ev) => {
    const f = ((ev.clientX - s.getBoundingClientRect().left - m.l) / (W - m.l - m.r)) * (n - 1);
    let best = 0;
    sheet.frames.forEach((fr, i) => { if (Math.abs(fr - f) < Math.abs(sheet.frames[best] - f)) best = i; });
    show(best);
  };
  hit.addEventListener("pointerdown", (ev) => { hit.setPointerCapture(ev.pointerId); playing = false; setIcon(); pick(ev); });
  hit.addEventListener("pointermove", (ev) => { if (ev.buttons) pick(ev); });
  show(k);
});

// ---------- playback ----------
const pinned = parseInt(params.get("f"), 10);
let playing = !reduced && !Number.isFinite(pinned), last = 0;
const frameMs = ((sheet.frames[1] - sheet.frames[0]) / clip.fps) * 1000;
function setIcon() {
  $("playIcon").setAttribute("d", playing ? "M2 1h3.5v12H2zM8.5 1H12v12H8.5z" : "M3 1l10 6-10 6z");
  $("play").setAttribute("aria-label", playing ? "Pause" : "Play");
}
$("play").addEventListener("click", () => { playing = !playing; setIcon(); });
function tick(now) {
  if (playing && now - last >= frameMs) { last = now; show((k + 1) % sheet.frames.length); }
  requestAnimationFrame(tick);
}
setIcon();
show(Number.isFinite(pinned) ? pinned : 0);
requestAnimationFrame(tick);

// ---------- accuracy ----------
$("tiles").innerHTML = [
  ["Frames with speed read", `${A.speed_read_rate_pct.toFixed(1)}%`, `${clip.frames} frames, ${clip.size[0]}×${clip.size[1]}`],
  ["Speed error", `${A.speed_mae_kmh.toFixed(2)} km/h`, `95% within ${A.speed_p95_kmh.toFixed(1)} km/h`],
  ["Gear correct", `${A.gear_accuracy_pct.toFixed(1)}%`, "of samples"],
  ["Throttle error", `${A.throttle_mae_pct.toFixed(1)} pts`, "out of 100"],
  ["Brake agreement", `${A.brake_agreement_pct.toFixed(1)}%`, "on or off"],
  ["Revs error", `${A.rpm_mae.toFixed(0)} rpm`, "read from a short arc"],
].map(([a, b, c]) => `<div class="tile"><span class="t-label">${esc(a)}</span><b class="t-num">${esc(b)}</b><small>${esc(c)}</small></div>`).join("");
