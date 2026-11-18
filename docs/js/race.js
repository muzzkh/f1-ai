// Race weekend page: hero (result, circuit, live lap) and the race story below it.

import { $, esc, el, lapTime, reduced, params, context, shell, load, COMPOUND, compoundName } from "./lib.js";
import { Track, ramp, PEDAL } from "./track.js";
import { cluster } from "./cluster.js";
import { elevation } from "./track3d.js";
import { storyChart, driverChips, stintRibbons, compoundLegend, paceStrips, bars } from "./charts.js";

const ctx = await context();
shell("index.html", ctx);
const D = await load(`${ctx.dir}/race.json`);
const { event: E, results: R, track: T, lap: L, drivers: DR } = D;

// ---------- headline ----------
document.title = `${E.name} ${E.year} · F1 AI`;
$("eyebrow").innerHTML = [`Round ${E.round}`, E.date, `${E.circuit}, ${E.country}`].map((s) => `<span>${esc(s)}</span>`).join("");
$("title").innerHTML = `${esc(E.name.replace(/ Grand Prix$/, ""))}<br><em>Grand Prix</em>`;

const [p1, p2, p3] = R;
$("winner").style.setProperty("--team", p1.color);
$("winner").innerHTML = `
  <span class="winner__tag t-label">Winner</span><span class="winner__bar"></span>
  <span class="winner__code t-display">${esc(p1.code)}</span>
  <span class="winner__name">${esc(p1.name)}</span>
  <span class="winner__meta">${esc(p1.team)} · from P${p1.grid ?? "-"} on the grid</span>`;
$("podium").innerHTML = [p2, p3].filter(Boolean).map((d) => `
  <li style="--team:${d.color}"><span class="p t-num">P${d.pos}</span><span class="bar"></span>
  <span class="code">${esc(d.code)}</span><span class="who">${esc(d.name)} · ${esc(d.team)}</span>
  <span class="gap t-num">${d.gap != null ? "+" + d.gap.toFixed(3) : esc(d.status)}</span></li>`).join("");

const climber = R.filter((d) => d.pos && d.grid).sort((a, b) => (b.grid - b.pos) - (a.grid - a.pos))[0];
const fastest = R.filter((d) => d.best).sort((a, b) => a.best - b.best)[0];
const W = E.weather || {};
const climb = Math.max(...T.z) - Math.min(...T.z);
$("facts").innerHTML = [
  ["Race distance", `${E.laps} laps`, `${((E.laps * T.length) / 1000).toFixed(0)} km around ${E.circuit}`],
  ["Fastest lap", lapTime(fastest.best), `${fastest.name}, ${fastest.team}`],
  ["Biggest climb", `${climber.code} +${climber.grid - climber.pos}`, `P${climber.grid} on the grid to P${climber.pos}`],
  ["Track", W.track_temp_c != null ? `${Math.round(W.track_temp_c)} °C` : "-", `${W.rain ? "Rain during the race" : "Dry throughout"} · ${climb.toFixed(0)} m of elevation`],
].map(([k, v, n]) => `<div class="fact"><dt class="t-label">${esc(k)}</dt><dd><div class="v t-num">${esc(v)}</div><div class="n">${esc(n)}</div></dd></div>`).join("");

// ---------- circuit ----------
const svg = $("track");
svg.setAttribute("aria-label", `Map of ${E.circuit} with ${L.name}'s fastest lap of the race coloured along the track`);
const track = new Track(svg, T);
track.pitLane(T.pit, track.project);
track.mark(0, "S/F", true);
T.sectors.forEach((s, i) => track.mark(s, `S${i + 1}▸S${i + 2}`));
track.corners(T.corners);

const vMin = Math.min(...L.speed), vMax = Math.max(...L.speed);
const LAYERS = {
  speed: {
    colour: (i) => ramp((L.speed[i] - vMin) / (vMax - vMin)),
    legend: `<span>${vMin}</span><span class="ramp" style="background:linear-gradient(90deg,#3a1d7a,#7b46e6 45%,#b58cff 75%,#f6f0ff)"></span><span>${vMax} km/h</span>`,
  },
  gear: {
    colour: (i) => ramp((L.gear[i] - 1) / 7),
    legend: `<span>1st</span><span class="ramp" style="background:linear-gradient(90deg,${[0, 1, 2, 3, 4, 5, 6, 7].map((g) => `${ramp(g / 7)} ${g * 12.5}% ${(g + 1) * 12.5}%`).join(",")})"></span><span>8th gear</span>`,
  },
  pedals: {
    colour: (i) => (L.brake[i] ? PEDAL.brake : L.throttle[i] >= 98 ? PEDAL.throttle : PEDAL.coast),
    legend: [["Full throttle", PEDAL.throttle], ["Braking", PEDAL.brake], ["Part throttle", PEDAL.coast]]
      .map(([k, c]) => `<span class="sw"><i style="background:${c}"></i>${k}</span>`).join(""),
  },
};
let relief = null; // the elevation view, created the first time it is opened
const setLayer = (name) => {
  track.colour(LAYERS[name].colour);
  relief?.setColour(LAYERS[name].colour);
  setLayer.current = name;
  $("legend").innerHTML = LAYERS[name].legend;
  document.querySelectorAll("[data-layer]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.layer === name));
};
document.querySelectorAll("[data-layer]").forEach((b) => b.addEventListener("click", () => setLayer(b.dataset.layer)));
setLayer("speed");
const moveCar = track.car(L.color);

const setView = (view) => {
  const three = view === "3d";
  if (three && !relief) {
    relief = elevation($("track3d"), T, LAYERS[setLayer.current].colour);
    $("note3d").textContent = `Drag to turn. ${relief.rise.toFixed(0)} m separates the lowest and highest points; heights are drawn ${relief.exaggeration}× taller than true scale so they can be seen.`;
  }
  svg.hidden = three; $("track3d").hidden = !three; $("note3d").hidden = !three;
  three ? relief.start() : relief?.stop();
  document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.view === view));
};
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

// ---------- instrument deck ----------
$("lapHud").style.setProperty("--team", L.color);
$("lapHud").innerHTML = `
  <div class="who"><i></i><span class="t-label">Fastest lap · ${esc(L.code)} · lap ${L.lap} · ${esc((L.compound || "").toLowerCase())}</span></div>
  <div class="timer t-num" id="timer">0:00.000</div>
  <div class="sectors">${[1, 2, 3].map((k) => `<div class="sector" id="sec${k}"><span class="k t-label">S${k}</span><span class="t t-num">-</span></div>`).join("")}</div>`;
const sectorStart = [0, ...T.sectors.map((s) => interp(s / T.step, L.t))];
const sectorEnd = [sectorStart[1] ?? L.time, sectorStart[2] ?? L.time, L.time];
const update = cluster($("cluster"), { rpmMax: L.rpm_max });

const trace = $("trace"), TW = 1000, TH = 96;
const tx = (i) => (i / track.n) * TW, ty = (v) => TH - 8 - (v / vMax) * (TH - 20);
const grad = el("linearGradient", { id: "tg", x1: 0, y1: 0, x2: 0, y2: 1 }, el("defs", {}, trace));
el("stop", { offset: 0, "stop-color": "#a26bff", "stop-opacity": 0.45 }, grad);
el("stop", { offset: 1, "stop-color": "#a26bff", "stop-opacity": 0 }, grad);
const line = "M" + L.speed.map((v, i) => `${tx(i).toFixed(1)} ${ty(v).toFixed(1)}`).join("L");
el("path", { d: `${line}L${TW} ${TH}L0 ${TH}Z`, fill: "url(#tg)" }, trace);
el("path", { d: line, fill: "none", stroke: "#a26bff", "stroke-width": 1.5, "vector-effect": "non-scaling-stroke" }, trace);
T.sectors.forEach((s) => el("line", { x1: tx(s / T.step), x2: tx(s / T.step), y1: 0, y2: TH, stroke: "#2a2e37", "vector-effect": "non-scaling-stroke" }, trace));
const head = el("line", { y1: 0, y2: TH, stroke: "#f4f1ea", "stroke-width": 1.5, "vector-effect": "non-scaling-stroke" }, trace);

// ---------- playback ----------
function interp(fi, arr) {
  const i = Math.min(arr.length - 1, Math.floor(fi)), j = Math.min(arr.length - 1, i + 1);
  return arr[i] + (arr[j] - arr[i]) * (fi - Math.floor(fi));
}
function indexAt(t) { // fractional sample index for a lap time (L.t is increasing)
  let lo = 0, hi = L.t.length - 1;
  if (t >= L.t[hi]) return hi + Math.min(0.999, (t - L.t[hi]) / Math.max(1e-3, L.time - L.t[hi]));
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; (L.t[mid] <= t ? (lo = mid) : (hi = mid)); }
  return lo + (t - L.t[lo]) / Math.max(1e-6, L.t[hi] - L.t[lo]);
}
// ?t=31.5 opens the page paused at that moment of the lap, with no intro animation.
const startAt = parseFloat(params.get("t")), pinned = Number.isFinite(startAt);
if (pinned) document.documentElement.classList.add("static");
let t = pinned ? Math.min(L.time, Math.max(0, startAt)) : 0, playing = !reduced && !pinned, last = null, hold = 0;

function render() {
  const fi = indexAt(t), i = Math.min(track.n - 1, Math.floor(fi));
  moveCar(fi);
  relief?.setCar(fi, L.color);
  update({ speed: interp(fi, L.speed), gear: L.gear[i], throttle: interp(fi, L.throttle), brake: L.brake[i], rpm: interp(fi, L.rpm), g: interp(fi, L.g) });
  $("timer").textContent = `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}`;
  const x = tx(fi); head.setAttribute("x1", x); head.setAttribute("x2", x);
  trace.setAttribute("aria-valuenow", Math.round((fi / track.n) * 100));
  for (let k = 0; k < 3; k++) {
    const node = $(`sec${k + 1}`), out = node.querySelector(".t");
    const done = t >= sectorEnd[k] - 1e-3, live = !done && t >= sectorStart[k];
    node.classList.toggle("is-done", done); node.classList.toggle("is-live", live);
    out.textContent = done ? (L.sector_times[k] ?? 0).toFixed(3) : live ? (t - sectorStart[k]).toFixed(1) : "-";
  }
}
function frame(now) {
  if (playing) {
    const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
    if (hold > 0) { hold -= dt; if (hold <= 0) t = 0; }
    else { t += dt; if (t >= L.time) { t = L.time; hold = 1.6; } }
    render();
  }
  last = now;
  requestAnimationFrame(frame);
}
const setPlaying = (on) => {
  playing = on; last = null;
  $("playIcon").setAttribute("d", on ? "M2 1h3.5v12H2zM8.5 1H12v12H8.5z" : "M3 1l10 6-10 6z");
  $("play").setAttribute("aria-label", on ? "Pause the lap" : "Play the lap");
};
$("play").addEventListener("click", () => { if (!playing && t >= L.time) t = 0; setPlaying(!playing); });
const scrub = (ev) => {
  const box = trace.getBoundingClientRect();
  const fi = Math.min(0.9999, Math.max(0, (ev.clientX - box.left) / box.width)) * track.n;
  t = interp(fi, L.t); hold = 0; render();
};
trace.addEventListener("pointerdown", (ev) => { trace.setPointerCapture(ev.pointerId); scrub(ev); });
trace.addEventListener("pointermove", (ev) => { if (ev.buttons) scrub(ev); });
trace.addEventListener("keydown", (ev) => {
  const d = { ArrowLeft: -1, ArrowRight: 1 }[ev.key];
  if (d) { t = Math.min(L.time, Math.max(0, t + d)); hold = 0; render(); ev.preventDefault(); }
});
trace.setAttribute("aria-valuemin", 0); trace.setAttribute("aria-valuemax", 100);
setPlaying(playing);
render();
requestAnimationFrame(frame);
if (params.get("view") === "3d") { setView("3d"); relief.draw(); }

// ---------- classification ----------
const top = R.slice(0, 10), maxGap = Math.max(...top.map((d) => d.gap ?? 0)) || 1;
$("rows").innerHTML = top.map((d, i) => `
  <div class="row" style="--team:${d.color}">
    <span class="p t-num">${d.pos ?? "-"}</span><span class="bar"></span><span class="code">${esc(d.code)}</span>
    <span class="who"><b>${esc(d.name)}</b><small>${esc(d.team)}</small></span>
    <span class="gapbar${d.gap == null && i ? " is-lapped" : ""}"><i style="width:${d.gap ? Math.max(1.5, (d.gap / maxGap) * 100) : 0}%"></i></span>
    <span class="gap t-num">${i === 0 ? "Winner" : d.gap != null ? "+" + d.gap.toFixed(3) : esc(d.status)}</span>
  </div>`).join("");

// ---------- race story ----------
const order = D.story.series.map((s) => s.code);
driverChips($("chips"), DR, order);
const grid = Object.fromEntries(R.filter((d) => d.grid).map((d) => [d.code, d.grid]));
storyChart($("positions"), D, { key: "pos", height: 460, yMax: order.length, start: grid, aria: "Position of every driver from the grid to the flag" });
const finite = D.story.series.flatMap((s) => s.gap.filter((v) => v != null)).sort((a, b) => a - b);
const gapMax = Math.min(120, Math.ceil((finite[Math.floor(finite.length * 0.9)] || 60) / 10) * 10);
storyChart($("gaps"), D, { key: "gap", height: 380, yMax: gapMax, aria: "Gap of every driver to the race leader at the end of each lap" });

// ---------- tyres and pace ----------
const used = [...new Set(D.stints.flatMap((r) => r.stints.map((s) => s.compound)))];
compoundLegend($("compounds"), ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"].filter((c) => used.includes(c)));
stintRibbons($("stints"), D.stints, DR, E.laps);
paceStrips($("pace"), D.pace, DR);

// ---------- strategy model ----------
const S = D.strategy, box = $("strategy");
if (S.available) {
  const short = { SOFT: "S", MEDIUM: "M", HARD: "H" };
  box.innerHTML = `
    <div class="tiles">
      <div class="tile"><span class="t-label">Fuel effect</span><b class="t-num">${S.fuel_ms.toFixed(0)} ms/lap</b><small>${S.fuel_fitted ? "the car gets quicker as fuel burns off" : "typical value assumed"}</small></div>
      <div class="tile"><span class="t-label">Pit stop time loss</span><b class="t-num">${S.pit_loss.toFixed(1)} s</b><small>${S.stops_measured} stops measured</small></div>
      <div class="tile"><span class="t-label">Model fit (R²)</span><b class="t-num">${S.r2.toFixed(2)}</b><small>${S.laps_used} clean laps, ±${S.error.toFixed(2)} s a lap</small></div>
    </div>
    <div class="split">
      <div><h3 class="t-label">Tyre wear, seconds lost per lap of age</h3><div id="deg"></div></div>
      <div><h3 class="t-label">Predicted fastest strategies</h3><div id="options"></div>
        <p class="note">What ${esc(S.winner)} actually ran: ${S.actual.compounds.map((c, i) => `${short[c] ?? c[0]} ${S.actual.stint_laps[i]}`).join(" – ")} laps.</p></div>
    </div>`;
  bars($("deg"), Object.entries(S.deg).map(([c, v]) => ({ label: compoundName(c), value: v, colour: COMPOUND[c] })), { format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(3)} s` });
  const rows = S.options.map((o) => {
    let from = 1;
    return { code: null, stints: o.compounds.map((c, i) => { const s = { compound: c, from, to: from + o.stint_laps[i] - 1, laps: o.stint_laps[i] }; from += o.stint_laps[i]; return s; }) };
  });
  stintRibbons($("options"), rows, null, S.total_laps, { labels: S.options.map((o, i) => `${i + 1}. ${o.compounds.map((c) => short[c]).join("-")}  +${o.gap_to_best_s.toFixed(1)}s`) });
} else {
  box.innerHTML = `<p class="quiet">${esc(S.reason || "No strategy model for this session.")}</p>`;
}

// ---------- replay (loaded only when it exists and the reader scrolls to it) ----------
const replayHost = $("replay");
if (ctx.info.replay) {
  new IntersectionObserver((entries, io) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); import("./replay.js").then((m) => m.mount(replayHost, ctx, D)); }
  }, { rootMargin: "400px" }).observe(replayHost);
} else {
  $("replaySection").hidden = true;
}
$("duelLink").href = `duel.html${ctx.round !== ctx.season.latest ? `?r=${ctx.round}` : ""}`;
