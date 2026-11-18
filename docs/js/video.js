// Video lab: play the generated clip, see where the reader looks, and watch a
// cluster and a map position rebuilt from nothing but what it read.

import { $, esc, el, context, shell, load, responsive, reduced, params } from "./lib.js";
import { lin, INK, label } from "./charts.js";
import { Track } from "./track.js";
import { cluster } from "./cluster.js";

const ctx = await context();
shell("video.html", ctx);
const V = await load("video.json");
if (!V || !V.clip?.src) {
  document.querySelector("main").innerHTML = `<div class="wrap"><p class="quiet" style="margin-top:60px">The video lab has not been built for this snapshot.</p></div>`;
  throw new Error("no video data");
}
const { regions, read, truth, t: T, accuracy: A, clip } = V;
const frames = T.length, [W, H] = clip.size;
$("eyebrow").innerHTML = [V.driver.name, `${V.event.name} ${V.event.year}`, `${V.session} · lap ${V.lap}`].map((s) => `<span>${esc(s)}</span>`).join("");

// ---------- the clip and what the reader looks at ----------
const video = $("clip");
video.poster = clip.poster;
video.src = clip.src;
const svg = $("regions");
svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
const HUE = { speed: "#f5c400", gear: "#3fd0ff", throttle: "#35d07f", brake: "#ff4d5a", rpm: "#a26bff" };
for (const [name, r] of Object.entries(regions)) {
  const col = HUE[name] ?? "#f4f1ea";
  if (r.kind === "arc") {
    const cx = r.center[0] * W, cy = r.center[1] * H;
    for (const rad of [r.r_inner, r.r_outer]) {
      const R = rad * H, a0 = (r.start_deg * Math.PI) / 180, a1 = (r.end_deg * Math.PI) / 180;
      el("path", { d: `M${cx + R * Math.cos(a0)} ${cy + R * Math.sin(a0)}A${R} ${R} 0 0 ${r.end_deg > r.start_deg ? 1 : 0} ${cx + R * Math.cos(a1)} ${cy + R * Math.sin(a1)}`,
        fill: "none", stroke: col, "stroke-width": 1.5 }, svg);
    }
  } else {
    const [x0, y0, x1, y1] = r.roi;
    el("rect", { x: x0 * W, y: y0 * H, width: (x1 - x0) * W, height: (y1 - y0) * H, fill: "none", stroke: col, "stroke-width": 1.5 }, svg);
  }
}
$("showRegions").addEventListener("change", (ev) => { svg.style.display = ev.target.checked ? "" : "none"; });

// ---------- rebuilt from the readings ----------
const update = cluster($("cluster"), { rpmMax: V.rpm_max });
const map = new Track($("map"), V.track, { data: false, pad: 60 });
map.mark(0, "S/F", true);
map.corners(V.track.corners);
document.documentElement.classList.add("static"); // the map is a readout, not an intro animation
const moveDot = map.car(V.driver.color);

const CELLS = [["speed", "Speed", (v) => `${Math.round(v)}`, "km/h", 2], ["gear", "Gear", (v) => `${Math.round(v)}`, "", 0.5],
  ["throttle", "Throttle", (v) => `${Math.round(v)}`, "%", 5], ["brake", "Brake", (v) => (v > 50 ? "on" : "off"), "", 50],
  ["rpm", "Revs", (v) => `${Math.round(v / 10) * 10}`, "rpm", 400]];
$("cells").innerHTML = CELLS.map(([k, name]) => `
  <div class="cell" style="--team:${HUE[k]}"><span class="t-label"><i></i>${name}</span>
    <b class="t-num" id="rd-${k}">-</b><small>truth <span class="t-num" id="tr-${k}">-</span></small><em id="ok-${k}"></em></div>`).join("");

let heads = [], current = -1;
function show(f) {
  f = Math.max(0, Math.min(frames - 1, f));
  if (f === current) return;
  current = f;
  $("clock").textContent = `${T[f].toFixed(2)} s`;
  update({ speed: read.speed[f] ?? 0, gear: read.gear[f] ?? 0, throttle: read.throttle[f] ?? 0, brake: (read.brake[f] ?? 0) > 50,
    rpm: read.rpm[f] ?? 0, g: read.g?.[f] ?? null });
  moveDot(((read.distance[f] ?? 0) / V.track.step) % map.n);
  for (const [key, , fmt, unit, tol] of CELLS) {
    const a = read[key][f], b = truth[key][f];
    $(`rd-${key}`).textContent = a == null ? "-" : `${fmt(a)}${unit && unit !== "km/h" && unit !== "rpm" ? unit : ""}`;
    $(`tr-${key}`).textContent = b == null ? "-" : `${fmt(b)}${unit ? " " + unit : ""}`;
    const ok = a != null && b != null && Math.abs(a - b) <= tol;
    $(`ok-${key}`).textContent = ok ? "match" : "differs";
    $(`ok-${key}`).className = ok ? "is-ok" : "is-off";
  }
  heads.forEach((fn) => fn(f));
}
const frameNow = () => Math.round(video.currentTime * clip.fps);
const seek = (f) => { video.currentTime = Math.max(0, Math.min(clip.seconds - 0.02, f / clip.fps)); show(f); };

// ---------- traces: read against truth ----------
const PANELS = [["speed", "Speed (km/h)", 170], ["throttle", "Throttle (%)", 80], ["gear", "Gear", 70]];
responsive($("readTrace"), (width) => {
  const host = $("readTrace");
  host.innerHTML = `<div class="keys"><span class="key"><i style="background:#a26bff;opacity:.55;height:6px"></i>Telemetry (truth)</span><span class="key"><i style="background:#f4f1ea;height:2px"></i>Read from video</span></div>`;
  heads = [];
  const m = { l: 44, r: 14, gap: 24 }, height = PANELS.reduce((s, p) => s + p[2] + m.gap, 0) + 20;
  const s = el("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart", role: "img", "aria-label": "Values read from the video against the telemetry it was generated from" }, host);
  const x = lin(0, frames - 1, m.l, width - m.r);
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
  for (let sec = 5; sec < clip.seconds; sec += 5) label(s, `${sec} s`, { x: x(sec * clip.fps), y: height - 4, "text-anchor": "middle" });
  const head = el("line", { y1: 8, y2: height - 20, stroke: INK.paper, "stroke-width": 1.5 }, s);
  heads.push((f) => { head.setAttribute("x1", x(f)); head.setAttribute("x2", x(f)); });
  const hit = el("rect", { x: m.l, y: 0, width: width - m.l - m.r, height, fill: "transparent", style: "cursor:ew-resize" }, s);
  const pick = (ev) => seek(Math.round(((ev.clientX - s.getBoundingClientRect().left - m.l) / (width - m.l - m.r)) * (frames - 1)));
  hit.addEventListener("pointerdown", (ev) => { hit.setPointerCapture(ev.pointerId); pick(ev); });
  hit.addEventListener("pointermove", (ev) => { if (ev.buttons) pick(ev); });
  const f = current; current = -1; show(Math.max(0, f));
});

// ---------- playback ----------
const setIcon = () => {
  $("playIcon").setAttribute("d", video.paused ? "M3 1l10 6-10 6z" : "M2 1h3.5v12H2zM8.5 1H12v12H8.5z");
  $("play").setAttribute("aria-label", video.paused ? "Play" : "Pause");
};
$("play").addEventListener("click", () => (video.paused ? video.play() : video.pause()));
video.addEventListener("play", setIcon);
video.addEventListener("pause", setIcon);
video.addEventListener("seeked", () => show(frameNow()));
const loop = () => { if (!video.paused) show(frameNow()); requestAnimationFrame(loop); };
requestAnimationFrame(loop);
const pinned = parseInt(params.get("f"), 10); // ?f=200 opens paused on that frame
if (Number.isFinite(pinned)) {
  show(pinned);
  video.addEventListener("loadedmetadata", () => seek(pinned), { once: true });
} else {
  show(0);
  if (!reduced) video.play().catch(() => {});
}
setIcon();

// ---------- accuracy ----------
$("tiles").innerHTML = [
  ["Frames with speed read", `${A.speed_read_rate_pct.toFixed(1)}%`, `${clip.frames} frames, ${W}×${H}`],
  ["Speed error", `${A.speed_mae_kmh.toFixed(2)} km/h`, `95% within ${A.speed_p95_kmh.toFixed(1)} km/h`],
  ["Gear correct", `${A.gear_accuracy_pct.toFixed(1)}%`, "of samples"],
  ["Throttle error", `${A.throttle_mae_pct.toFixed(1)} pts`, "out of 100"],
  ["Brake agreement", `${A.brake_agreement_pct.toFixed(1)}%`, "on or off"],
  ["Revs error", `${A.rpm_mae.toFixed(0)} rpm`, "read from a short arc"],
].map(([a, b, c]) => `<div class="tile"><span class="t-label">${esc(a)}</span><b class="t-num">${esc(b)}</b><small>${esc(c)}</small></div>`).join("");
