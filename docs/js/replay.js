// Race replay: every car on the real circuit, with a timing tower and timeline.

import { el, esc, load, focus, responsive, params, reduced, COMPOUND, compoundName } from "./lib.js";
import { Track } from "./track.js";
import { lin, INK, label } from "./charts.js";

const cumsum = (deltas) => {
  const out = new Float32Array(deltas.length);
  let v = 0;
  for (let i = 0; i < deltas.length; i++) { v += deltas[i]; out[i] = v; }
  return out;
};
const countLE = (arr, t) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; arr[m] <= t ? (lo = m + 1) : (hi = m); } return lo; };
const clock = (t) => `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const STATUS = { SC: "Safety car", VSC: "Virtual safety car", RED: "Red flag" };

export async function mount(host, ctx, D) {
  host.innerHTML = `<p class="quiet">Loading the race…</p>`;
  const P = await load(`${ctx.dir}/replay.json`);
  if (!P) { host.innerHTML = `<p class="quiet">No replay is available for this race.</p>`; return; }
  const { drivers: DR, results: R, story, stints, event: E } = D;
  const series = Object.fromEntries(story.series.map((s) => [s.code, s]));
  const stintOf = Object.fromEntries(stints.map((s) => [s.code, s.stints]));
  const grid = [...R].sort((a, b) => (a.grid ?? 99) - (b.grid ?? 99)).map((d) => d.code);

  host.innerHTML = `
    <div class="replay__grid">
      <div class="replay__map"><svg class="track" role="img" aria-label="All cars on the circuit during the race"></svg>
        <div class="replay__badge"><b class="t-num" id="rpLap">LAP 1</b><span id="rpStatus">Green</span></div></div>
      <div class="tower"><div class="tower__head t-label"><span>Order</span><span id="rpAsOf"></span></div><ol id="rpTower"></ol></div>
    </div>
    <div class="replay__bar">
      <button class="play" id="rpPlay" type="button" aria-label="Play the race">
        <svg viewBox="0 0 14 14" aria-hidden="true"><path id="rpIcon" d="M3 1l10 6-10 6z"/></svg></button>
      <div class="seg" role="group" aria-label="Playback speed">
        ${[8, 20, 60].map((s) => `<button type="button" data-speed="${s}" aria-pressed="${s === 20}">${s}×</button>`).join("")}</div>
      <div class="replay__line" id="rpLine"></div>
      <b class="t-num replay__clock" id="rpClock">0:00:00</b>
    </div>
    <p class="note" id="rpPass">Purple ticks on the timeline are overtakes recorded by race control.</p>`;

  const svg = host.querySelector("svg.track");
  const track = new Track(svg, D.track, { data: false });
  track.pitLane(D.track.pit, track.project);
  track.mark(0, "S/F", true);
  document.documentElement.classList.contains("static") || svg.querySelectorAll(".draw,.fade").forEach((n) => { n.classList.remove("draw"); n.classList.remove("fade"); });

  const layer = el("g", {}, svg);
  const cars = P.cars.filter((c) => DR[c.code]).map((c) => {
    const d = DR[c.code], g = el("g", { "data-code": c.code }, layer);
    el("circle", { r: track.tw * 0.5, fill: d.color, stroke: d.second ? "#f4f1ea" : "#0a0b0d", "stroke-width": 2 }, g);
    const t = el("text", { class: "car-tag", y: -track.tw * 0.5 - 5 }, g);
    t.textContent = c.code;
    return { code: c.code, x: cumsum(c.x), y: cumsum(c.y), g, ends: P.lap_ends[c.code] || [], last: c.last };
  });
  focus.on((code) => cars.forEach((c) => {
    c.g.setAttribute("opacity", !code || c.code === code ? 1 : 0.28);
    if (c.code === code) layer.appendChild(c.g);
  }));

  // ---------- state (?rt=1500 opens the replay paused 1500 s into the race) ----------
  const pinnedAt = parseFloat(params.get("rt"));
  let t = Number.isFinite(pinnedAt) ? pinnedAt : 0, playing = false, speed = 20, last = null, lastOrder = "";

  // ---------- timeline ----------
  let head = () => {};
  const seek = (v) => { t = Math.max(0, Math.min(P.duration, v)); render(); };
  responsive(host.querySelector("#rpLine"), (W) => {
    const box = host.querySelector("#rpLine");
    box.innerHTML = "";
    const H = 46, s = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "slider", tabindex: 0,
      "aria-label": "Race timeline", "aria-valuemin": 0, "aria-valuemax": Math.round(P.duration) }, box);
    const x = lin(0, P.duration, 0, W);
    el("rect", { x: 0, y: 14, width: W, height: 14, rx: 2, fill: INK.raised }, s);
    for (const f of P.flags) {
      el("rect", { x: x(f.from), y: 14, width: Math.max(2, x(f.to) - x(f.from)), height: 14, fill: INK.paper, opacity: 0.35 }, s);
      label(s, f.kind === "RED" ? "RED" : f.kind, { x: (x(f.from) + x(f.to)) / 2, y: 9, "text-anchor": "middle" });
    }
    for (const o of P.overtakes) el("line", { x1: x(o.t), x2: x(o.t), y1: 16, y2: 26, stroke: "#a26bff", "stroke-width": 1, opacity: 0.8 }, s);
    const lead = cars.reduce((a, b) => (b.ends.length > a.ends.length ? b : a), cars[0]);
    for (let n = 10; n <= lead.ends.length; n += 10) {
      el("line", { x1: x(lead.ends[n - 1]), x2: x(lead.ends[n - 1]), y1: 28, y2: 33, stroke: INK.muted }, s);
      label(s, `L${n}`, { x: x(lead.ends[n - 1]), y: 44, "text-anchor": "middle" });
    }
    const knob = el("rect", { y: 8, width: 3, height: 26, rx: 1.5, fill: INK.paper }, s);
    head = (v) => { knob.setAttribute("x", x(v) - 1.5); s.setAttribute("aria-valuenow", Math.round(v)); };
    const at = (ev) => ((ev.clientX - s.getBoundingClientRect().left) / W) * P.duration;
    s.addEventListener("pointerdown", (ev) => { s.setPointerCapture(ev.pointerId); seek(at(ev)); });
    s.addEventListener("pointermove", (ev) => { if (ev.buttons) seek(at(ev)); });
    s.addEventListener("keydown", (ev) => {
      const d = { ArrowLeft: -30, ArrowRight: 30 }[ev.key];
      if (d) { seek(t + d); ev.preventDefault(); }
    });
    head(t);
  });

  const tower = host.querySelector("#rpTower");

  function render() {
    const f = Math.min(P.samples - 1.001, Math.max(0, t * P.hz)), i = Math.floor(f), u = f - i;
    let lapsLed = 0;
    for (const c of cars) {
      const [px, py] = track.project(c.x[i] + (c.x[i + 1] - c.x[i]) * u, c.y[i] + (c.y[i + 1] - c.y[i]) * u);
      c.g.setAttribute("transform", `translate(${px.toFixed(1)} ${py.toFixed(1)})`);
      lapsLed = Math.max(lapsLed, countLE(c.ends, t));
    }
    const n = Math.min(lapsLed, story.laps.length), finished = n >= story.laps.length;
    host.querySelector("#rpLap").textContent = finished ? "FINISHED" : `LAP ${n + 1} / ${E.laps}`;
    const flag = P.flags.find((x) => t >= x.from && t <= x.to);
    const st = host.querySelector("#rpStatus");
    st.textContent = finished ? "Chequered flag" : flag ? STATUS[flag.kind] : "Green";
    st.classList.toggle("is-neutral", !!flag && !finished);
    host.querySelector("#rpClock").textContent = clock(t);
    head(t);

    const order = n === 0 ? grid : [...story.series].sort((a, b) => (a.pos[n - 1] ?? 99) - (b.pos[n - 1] ?? 99)).map((s) => s.code);
    const key = `${n}`;
    if (key !== lastOrder) {
      lastOrder = key;
      host.querySelector("#rpAsOf").textContent = n === 0 ? "starting grid" : `end of lap ${n}`;
      tower.innerHTML = order.filter((c) => DR[c]).map((c, k) => {
        const d = DR[c], gap = n ? series[c]?.gap[n - 1] : null, pos = n ? series[c]?.pos[n - 1] : k + 1;
        const tyre = (stintOf[c] || []).find((s) => n + 1 >= s.from && n + 1 <= s.to) || (stintOf[c] || []).at(-1);
        const out = n && pos == null;
        return `<li data-code="${c}" style="--team:${d.color}" class="${out ? "is-out" : ""}">
          <span class="t-num">${out ? "–" : pos}</span><i></i><b>${c}</b>
          <span class="t-num gap">${out ? "out" : !n ? "" : gap == null ? "" : gap < 0.005 ? "leader" : "+" + gap.toFixed(1)}</span>
          <em title="${tyre ? compoundName(tyre.compound) : ""}" style="background:${tyre ? COMPOUND[tyre.compound] || COMPOUND.UNKNOWN : "transparent"}">${tyre ? tyre.compound[0] : ""}</em></li>`;
      }).join("");
      tower.querySelectorAll("li").forEach((li) => {
        li.addEventListener("pointerenter", () => focus.set(li.dataset.code));
        li.addEventListener("pointerleave", () => focus.set(null));
        li.addEventListener("click", () => focus.pin(li.dataset.code));
      });
    }
    const k = countLE(P.overtakes.map((o) => o.t), t) - 1; // most recent pass
    if (k >= 0) {
      const o = P.overtakes[k];
      host.querySelector("#rpPass").innerHTML = `Latest pass: <b>${esc(DR[o.by]?.name ?? o.by)}</b> on ${esc(DR[o.on]?.name ?? o.on)}${o.pos ? ` for P${o.pos}` : ""}. Purple ticks on the timeline are overtakes recorded by race control.`;
    }
  }

  function frame(now) {
    if (playing) {
      const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
      t += dt * speed;
      if (t >= P.duration) { t = P.duration; setPlaying(false); }
      render();
    }
    last = now;
    requestAnimationFrame(frame);
  }
  const setPlaying = (on) => {
    playing = on; last = null;
    host.querySelector("#rpIcon").setAttribute("d", on ? "M2 1h3.5v12H2zM8.5 1H12v12H8.5z" : "M3 1l10 6-10 6z");
    host.querySelector("#rpPlay").setAttribute("aria-label", on ? "Pause the race" : "Play the race");
  };
  host.querySelector("#rpPlay").addEventListener("click", () => { if (!playing && t >= P.duration) t = 0; setPlaying(!playing); });
  host.querySelectorAll("[data-speed]").forEach((b) => b.addEventListener("click", () => {
    speed = +b.dataset.speed;
    host.querySelectorAll("[data-speed]").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  // play only while the replay is on screen
  new IntersectionObserver((entries) => { if (!entries[0].isIntersecting && playing) setPlaying(false); }).observe(host);
  render();
  if (!reduced && !Number.isFinite(pinnedAt)) setPlaying(true);
  requestAnimationFrame(frame);
}
