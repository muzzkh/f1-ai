// Lap duel: two laps raced against each other on the real circuit.

import { $, esc, el, lapTime, reduced, params, context, shell, load, tip, responsive, compoundName, inkOn } from "./lib.js";
import { Track } from "./track.js";
import { cluster } from "./cluster.js";
import { lin, INK, label } from "./charts.js";

const ctx = await context();
shell("duel.html", ctx);
const D = await load(`${ctx.dir}/duel.json`);
if (!D) {
  document.querySelector("main").innerHTML = `<div class="wrap"><p class="quiet" style="margin-top:60px">No lap duel is available for this weekend.</p></div>`;
  throw new Error("no duel data");
}
const { event: E, track: T, a: A, b: B, delta } = D;
// team colour identifies each car; team-mates share one, so the second goes paper white
const colA = A.color, colB = B.color.toLowerCase() === A.color.toLowerCase() ? "#f4f1ea" : B.color;
const n = T.x.length;

document.title = `${A.code} v ${B.code} · ${E.name} ${E.year} · F1 AI`;
$("eyebrow").innerHTML = [`${D.session}`, `Round ${E.round}`, `${E.circuit}, ${E.country}`].map((s) => `<span>${esc(s)}</span>`).join("");
const faster = D.gap > 0 ? A : B;
$("versus").innerHTML = `
  <div class="vs vs--a" style="--team:${colA};--on:${inkOn(colA)}"><span class="vs__code t-display">${esc(A.code)}</span>
    <span class="vs__name">${esc(A.name)}<small>${esc(A.team)}</small></span><b class="t-num">${lapTime(A.time)}</b></div>
  <div class="vs__gap"><span class="t-label">Gap</span><b class="t-num">${Math.abs(D.gap).toFixed(3)}</b><small>${esc(faster.code)} faster</small></div>
  <div class="vs vs--b" style="--team:${colB};--on:${inkOn(colB)}"><b class="t-num">${lapTime(B.time)}</b>
    <span class="vs__name">${esc(B.name)}<small>${esc(B.team)}</small></span><span class="vs__code t-display">${esc(B.code)}</span></div>`;

// ---------- circuit: who is faster where ----------
const svg = $("track");
svg.setAttribute("aria-label", `Map of ${E.circuit} coloured by which driver is faster through each part of the lap`);
const track = new Track(svg, T);
track.mark(0, "S/F", true);
T.sectors.forEach((s, i) => track.mark(s, `S${i + 1}▸S${i + 2}`));
track.corners(T.corners);
const owner = new Array(n).fill(colA);
for (const m of D.minis) for (let i = m.from; i <= m.to; i++) owner[i] = m.gain_a > 0 ? colA : colB;
track.colour((i) => owner[i]);
$("legend").innerHTML = `<span class="sw"><i style="background:${colA}"></i>${esc(A.code)} faster here</span><span class="sw"><i style="background:${colB}"></i>${esc(B.code)} faster here</span>`;
const moveB = track.car(colB), moveA = track.car(colA);

const side = (host, P, col) => {
  host.style.setProperty("--team", col);
  host.innerHTML = `<div class="cluster"></div>
    <dl class="mini"><div><dt>Top speed</dt><dd class="t-num">${P.top.toFixed(0)} km/h</dd></div>
    <div><dt>Full throttle</dt><dd class="t-num">${P.full_throttle.toFixed(0)}%</dd></div>
    <div><dt>Braking</dt><dd class="t-num">${P.braking.toFixed(0)}%</dd></div>
    <div><dt>Tyres</dt><dd>${esc(compoundName(P.compound))}</dd></div></dl>`;
  return cluster(host.querySelector(".cluster"), { rpmMax: Math.max(A.rpm_max, B.rpm_max) });
};
const updA = side($("sideA"), A, colA), updB = side($("sideB"), B, colB);

// ---------- playback ----------
const interp = (fi, arr) => {
  const i = Math.min(arr.length - 1, Math.floor(fi)), j = Math.min(arr.length - 1, i + 1);
  return arr[i] + (arr[j] - arr[i]) * (fi - Math.floor(fi));
};
const indexAt = (P, t) => {
  let lo = 0, hi = P.t.length - 1;
  if (t >= P.t[hi]) return hi + Math.min(0.999, (t - P.t[hi]) / Math.max(1e-3, P.time - P.t[hi]));
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; (P.t[mid] <= t ? (lo = mid) : (hi = mid)); }
  return lo + (t - P.t[lo]) / Math.max(1e-6, P.t[hi] - P.t[lo]);
};
const state = (P, fi) => {
  const i = Math.min(n - 1, Math.floor(fi));
  return { speed: interp(fi, P.speed), gear: P.gear[i], throttle: interp(fi, P.throttle), brake: P.brake[i], rpm: interp(fi, P.rpm), g: interp(fi, P.g) };
};
const end = Math.max(A.time, B.time);
const startAt = parseFloat(params.get("t")), pinned = Number.isFinite(startAt);
if (pinned) document.documentElement.classList.add("static");
let t = pinned ? Math.min(end, Math.max(0, startAt)) : 0, playing = !reduced && !pinned, last = null, hold = 0;
const heads = [];

function render() {
  const fa = indexAt(A, Math.min(t, A.time)), fb = indexAt(B, Math.min(t, B.time));
  moveB(fb); moveA(fa);
  updA(state(A, fa)); updB(state(B, fb));
  $("timer").textContent = `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}`;
  const g = interp(Math.min(fa, n - 1), delta);
  $("liveGap").textContent = `${Math.abs(g).toFixed(3)} s`;
  $("liveWho").textContent = Math.abs(g) < 0.0005 ? "level" : `${g > 0 ? A.code : B.code} ahead on the road`;
  heads.forEach((fn) => fn(fa));
}
function frame(now) {
  if (playing) {
    const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
    if (hold > 0) { hold -= dt; if (hold <= 0) t = 0; }
    else { t += dt; if (t >= end) { t = end; hold = 1.8; } }
    render();
  }
  last = now;
  requestAnimationFrame(frame);
}
const setPlaying = (on) => {
  playing = on; last = null;
  $("playIcon").setAttribute("d", on ? "M2 1h3.5v12H2zM8.5 1H12v12H8.5z" : "M3 1l10 6-10 6z");
  $("play").setAttribute("aria-label", on ? "Pause the laps" : "Play the laps");
};
$("play").addEventListener("click", () => { if (!playing && t >= end) t = 0; setPlaying(!playing); });

// ---------- traces ----------
const PANELS = [
  { key: "speed", title: "Speed (km/h)", h: 190, pair: true },
  { key: "delta", title: `Gap (s) · above zero, ${A.code} is ahead`, h: 120 },
  { key: "throttle", title: "Throttle (%)", h: 74, pair: true },
  { key: "brake", title: "Brake", h: 46, pair: true, step: true },
];
responsive($("traces"), (W) => {
  const host = $("traces");
  host.innerHTML = `<div class="keys"><span class="key"><i style="background:${colA}"></i>${esc(A.code)}</span><span class="key"><i style="background:${colB}"></i>${esc(B.code)}</span></div>`;
  heads.length = 0;
  const m = { l: 44, r: 14, gap: 26 }, H = PANELS.reduce((s, p) => s + p.h + m.gap, 0) + 22;
  const chart = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": "Speed, gap, throttle and brake for both laps against distance" }, host);
  const x = lin(0, n - 1, m.l, W - m.r);
  const line = (vals, y, step) => {
    let d = "";
    vals.forEach((v, i) => { d += step && i ? `H${x(i).toFixed(1)}V${y(v).toFixed(1)}` : `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`; });
    return d;
  };
  T.corners.forEach((c) => {
    el("line", { x1: x(c.i), x2: x(c.i), y1: 16, y2: H - 22, stroke: INK.hair, opacity: 0.55 }, chart);
    label(chart, c.label, { x: x(c.i), y: 10, "text-anchor": "middle" });
  });
  let top = 18;
  for (const p of PANELS) {
    const y0 = top + 14, y1 = top + p.h;
    label(chart, p.title.toUpperCase(), { x: m.l, y: top + 6, class: "ax ax--cap" });
    if (p.key === "delta") {
      const ext = Math.max(0.05, ...delta.map(Math.abs)), y = lin(ext, -ext, y0, y1);
      el("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), stroke: INK.muted }, chart);
      el("path", { d: `${line(delta, y)}L${x(n - 1)} ${y(0)}L${x(0)} ${y(0)}Z`, fill: "#f4f1ea", opacity: 0.08 }, chart);
      el("path", { d: line(delta, y), fill: "none", stroke: INK.paper, "stroke-width": 2 }, chart);
      for (const v of [ext, -ext]) label(chart, `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`, { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" });
    } else {
      const hi = p.key === "speed" ? Math.max(...A.speed, ...B.speed) : p.key === "brake" ? 1 : 100;
      const lo = p.key === "speed" ? Math.min(...A.speed, ...B.speed) * 0.9 : 0, y = lin(lo, hi, y1, y0);
      if (p.key === "speed") for (const v of [100, 200, 300]) if (v > lo && v < hi) {
        el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: INK.hair, opacity: 0.5 }, chart);
        label(chart, v, { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" });
      }
      el("path", { d: line(B[p.key], y, p.step), fill: "none", stroke: colB, "stroke-width": 2, "stroke-linejoin": "round" }, chart);
      el("path", { d: line(A[p.key], y, p.step), fill: "none", stroke: colA, "stroke-width": 2, "stroke-linejoin": "round" }, chart);
    }
    top += p.h + m.gap;
  }
  const km = T.length / 1000;
  for (let k = 1; k < km; k++) label(chart, `${k} km`, { x: x((k * 1000) / T.step), y: H - 6, "text-anchor": "middle" });
  const head = el("line", { y1: 16, y2: H - 22, stroke: INK.paper, "stroke-width": 1.5 }, chart);
  heads.push((fi) => { head.setAttribute("x1", x(fi)); head.setAttribute("x2", x(fi)); });
  const hit = el("rect", { x: m.l, y: 16, width: W - m.l - m.r, height: H - 38, fill: "transparent", style: "cursor:ew-resize" }, chart);
  const at = (ev) => Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - chart.getBoundingClientRect().left - m.l) / (W - m.l - m.r)) * (n - 1))));
  hit.addEventListener("pointermove", (ev) => {
    const i = at(ev);
    if (ev.buttons) { t = A.t[i]; hold = 0; render(); }
    tip.show(ev, `<b>${Math.round(i * T.step)} m</b><span>into the lap</span>
      <dl><dt>${esc(A.code)}</dt><dd>${A.speed[i]} km/h · gear ${A.gear[i]}</dd><dt>${esc(B.code)}</dt><dd>${B.speed[i]} km/h · gear ${B.gear[i]}</dd>
      <dt>Gap</dt><dd>${delta[i] >= 0 ? esc(A.code) : esc(B.code)} +${Math.abs(delta[i]).toFixed(3)} s</dd></dl>`);
  });
  hit.addEventListener("pointerdown", (ev) => { hit.setPointerCapture(ev.pointerId); t = A.t[at(ev)]; hold = 0; render(); });
  hit.addEventListener("pointerleave", tip.hide);
  render();
});

// ---------- corner cards ----------
const firstBrake = (P, lo, hi) => { for (let i = lo; i <= hi; i++) if (P.brake[i]) return i; return null; };
const slowest = (P, lo, hi) => { let k = lo; for (let i = lo; i <= hi; i++) if (P.speed[i] < P.speed[k]) k = i; return k; };
$("corners").innerHTML = D.corners.map((c, k) => `
  <article class="corner"><header><b class="t-display">T${esc(c.label)}</b>
    <span class="t-num" style="color:${c.gain_a >= 0 ? colA : colB}">${c.gain_a >= 0 ? esc(A.code) : esc(B.code)} +${Math.abs(c.gain_a).toFixed(3)}s</span></header>
    <svg id="cc${k}" viewBox="0 0 240 170" role="img" aria-label="Both racing lines through turn ${esc(c.label)}"></svg>
    <dl><div style="--team:${colA}"><dt><i></i>${esc(A.code)} minimum</dt><dd class="t-num">${c.min_a.toFixed(0)} km/h</dd></div>
    <div style="--team:${colB}"><dt><i></i>${esc(B.code)} minimum</dt><dd class="t-num">${c.min_b.toFixed(0)} km/h</dd></div></dl></article>`).join("");
D.corners.forEach((c, k) => {
  const s = $(`cc${k}`), lo = c.from, hi = c.to, idx = [];
  for (let i = lo; i <= hi; i++) idx.push(i);
  const pts = (xs, ys) => idx.map((i) => [xs[i], -ys[i]]);
  const mid = pts(T.x, T.y), la = pts(A.line_x, A.line_y), lb = pts(B.line_x, B.line_y);
  const all = [...mid, ...la, ...lb], xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const k2 = Math.min(200 / Math.max(1, x1 - x0), 130 / Math.max(1, y1 - y0));
  const px = (p) => [120 + (p[0] - (x0 + x1) / 2) * k2, 85 + (p[1] - (y0 + y1) / 2) * k2];
  const d = (list) => "M" + list.map((p) => px(p).map((v) => v.toFixed(1)).join(" ")).join("L");
  el("path", { d: d(mid), fill: "none", stroke: "#262a32", "stroke-width": Math.max(12, 14 * k2), "stroke-linecap": "round", "stroke-linejoin": "round" }, s);
  // B is drawn wider underneath so both lines show even where they overlap
  for (const [P, line, col, w] of [[B, lb, colB, 4.5], [A, la, colA, 1.8]]) {
    el("path", { d: d(line), fill: "none", stroke: col, "stroke-width": w, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
    const [mx, my] = px(line[slowest(P, lo, hi) - lo]);
    el("circle", { cx: mx, cy: my, r: 4, fill: col, stroke: "#0a0b0d", "stroke-width": 1.5 }, s);
    const b = firstBrake(P, lo, hi);
    if (b != null && b > lo) {
      const [bx, by] = px(line[b - lo]), [qx, qy] = px(line[Math.min(line.length - 1, b - lo + 1)]);
      const dx = qx - bx, dy = qy - by, len = Math.hypot(dx, dy) || 1;
      el("line", { x1: bx - (dy / len) * 7, y1: by + (dx / len) * 7, x2: bx + (dy / len) * 7, y2: by - (dx / len) * 7, stroke: col, "stroke-width": 2.5, "stroke-linecap": "round" }, s);
    }
  }
  const [ax, ay] = px(mid[0]), [bx, by] = px(mid[Math.min(4, mid.length - 1)]); // direction of travel
  const ang = (Math.atan2(by - ay, bx - ax) * 180) / Math.PI;
  el("path", { d: "M-5 -4L4 0L-5 4", fill: "none", stroke: "#7c7a73", "stroke-width": 1.5, transform: `translate(${ax.toFixed(1)} ${ay.toFixed(1)}) rotate(${ang.toFixed(0)})` }, s);
});

setPlaying(playing);
render();
requestAnimationFrame(frame);
