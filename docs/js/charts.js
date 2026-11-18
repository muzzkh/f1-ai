// Purpose-made race graphics, drawn as SVG from the design tokens.

import { el, html, esc, tip, focus, lapTime, signed, COMPOUND, compoundName, responsive } from "./lib.js";

const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
const INK = { paper: "#f4f1ea", ink2: "#b8b4aa", muted: "#7c7a73", hair: "#2a2e37", raised: "#1a1d23" };
const DASH = "5 4"; // the second driver of a team
const label = (parent, str, attrs) => { const t = el("text", { class: "ax", ...attrs }, parent); t.textContent = str; return t; };

function path(xs, ys) { // breaks the line where a value is missing
  let d = "", pen = false;
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] == null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${xs[i].toFixed(1)} ${ys[i].toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** Legend that doubles as a control: hover to highlight, click to pin. */
export function driverChips(host, drivers, order) {
  host.innerHTML = order.map((c) => {
    const d = drivers[c];
    return `<button type="button" class="chip" data-code="${c}" style="--team:${d.color}" title="${esc(d.name)} · ${esc(d.team)}">
      <i class="${d.second ? "is-second" : ""}"></i>${c}</button>`;
  }).join("");
  host.querySelectorAll(".chip").forEach((b) => {
    b.addEventListener("pointerenter", () => focus.set(b.dataset.code));
    b.addEventListener("pointerleave", () => focus.set(null));
    b.addEventListener("click", () => focus.pin(b.dataset.code));
  });
  focus.on((code) => host.querySelectorAll(".chip").forEach((b) => {
    b.classList.toggle("is-on", b.dataset.code === code);
    b.setAttribute("aria-pressed", b.dataset.code === focus.pinned);
  }));
}

/**
 * Lap-by-lap line chart for every driver (position or gap to the leader).
 * opts: key ("pos" | "gap"), height, yMax, yLabel, format(value)
 */
export function storyChart(host, D, opts) {
  const { laps, series, flags } = D.story, drivers = D.drivers;
  responsive(host, (W) => {
    host.innerHTML = "";
    const H = opts.height, m = { t: 22, r: 44, b: 30, l: 44 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": opts.aria }, host);
    // opts.start (code -> grid slot) adds the starting grid as a point before lap 1
    const off = opts.start ? 1 : 0, X = off ? [0, ...laps] : laps;
    const x = lin(off ? 0 : 1, laps.length, m.l, W - m.r);
    const yMax = opts.yMax, y = lin(opts.key === "pos" ? 1 : 0, yMax, m.t, H - m.b);
    const xs = X.map(x);

    for (const f of flags) { // neutralised laps
      const x0 = x(f.from - 0.5), x1 = x(f.to + 0.5);
      el("rect", { x: x0, y: m.t, width: x1 - x0, height: H - m.t - m.b, fill: "url(#hatch)", opacity: 0.6 }, svg);
      label(svg, f.kind === "SC" ? "Safety car" : f.kind === "VSC" ? "Virtual SC" : "Red flag", { x: (x0 + x1) / 2, y: m.t - 8, "text-anchor": "middle" });
    }
    const defs = el("defs", {}, svg);
    const pat = el("pattern", { id: "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
    el("rect", { width: 2, height: 6, fill: INK.hair }, pat);
    el("clipPath", { id: `clip-${opts.key}` }, defs).appendChild(el("rect", { x: m.l, y: m.t - 4, width: W - m.l - m.r, height: H - m.t - m.b + 8 }));

    const step = laps.length > 60 ? 10 : 5;
    for (let n = step; n <= laps.length; n += step) {
      el("line", { x1: x(n), x2: x(n), y1: m.t, y2: H - m.b, stroke: INK.hair, "stroke-width": 1, opacity: 0.5 }, svg);
      label(svg, n, { x: x(n), y: H - m.b + 16, "text-anchor": "middle" });
    }
    label(svg, off ? "GRID" : "LAP", { x: m.l, y: H - m.b + 16, "text-anchor": off ? "middle" : "start", class: "ax ax--cap" });
    if (opts.key === "gap") {
      const tick = yMax > 80 ? 20 : 10;
      for (let v = 0; v <= yMax; v += tick) {
        el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: INK.hair, "stroke-width": 1, opacity: v ? 0.5 : 1 }, svg);
        label(svg, v ? `+${v}s` : "Leader", { x: m.l - 8, y: y(v) + 3, "text-anchor": "end" });
      }
    }

    const lines = el("g", { "clip-path": `url(#clip-${opts.key})` }, svg), nodes = {};
    for (const s of series) {
      const d = drivers[s.code], vals = off ? [opts.start[s.code] ?? null, ...s[opts.key]] : s[opts.key];
      const ys = vals.map((v) => (v == null ? null : y(Math.min(v, yMax * 1.2))));
      const p = el("path", { d: path(xs, ys), fill: "none", stroke: d.color, "stroke-width": 2, "stroke-linejoin": "round",
        "stroke-dasharray": d.second ? DASH : null }, lines);
      nodes[s.code] = { p, ys };
      if (opts.key === "pos") { // direct labels at both ends
        const first = vals.findIndex((v) => v != null), last = vals.length - 1 - [...vals].reverse().findIndex((v) => v != null);
        if (first >= 0) {
          nodes[s.code].a = label(svg, s.code, { x: xs[first] - 8, y: ys[first] + 3.5, "text-anchor": "end", class: "ax ax--code" });
          nodes[s.code].b = label(svg, s.code, { x: xs[last] + 8, y: ys[last] + 3.5, "text-anchor": "start", class: "ax ax--code" });
        }
      }
    }
    const dot = el("circle", { r: 4.5, fill: INK.paper, stroke: "#0a0b0d", "stroke-width": 2, visibility: "hidden" }, svg);

    focus.on((code) => {
      for (const [c, n] of Object.entries(nodes)) {
        const on = !code || c === code;
        n.p.setAttribute("opacity", on ? 1 : 0.14);
        n.p.setAttribute("stroke-width", code && on ? 3 : 2);
        for (const t of [n.a, n.b]) if (t) t.setAttribute("opacity", on ? 1 : 0.25);
      }
      if (code && nodes[code]) lines.appendChild(nodes[code].p);
    });

    const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (ev) => {
      const box = svg.getBoundingClientRect(), px = ev.clientX - box.left, py = ev.clientY - box.top;
      const i = Math.max(0, Math.min(X.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (X.length - 1))));
      let best = null, dist = 1e9;
      for (const s of series) {
        const yy = nodes[s.code].ys[i];
        if (yy != null && Math.abs(yy - py) < dist) { dist = Math.abs(yy - py); best = s; }
      }
      if (!best) return;
      focus.set(best.code);
      dot.setAttribute("cx", xs[i]); dot.setAttribute("cy", nodes[best.code].ys[i]); dot.setAttribute("visibility", "visible");
      const d = drivers[best.code], k = i - off, gap = k >= 0 ? best.gap[k] : null;
      const place = k >= 0 ? best.pos[k] : opts.start[best.code];
      tip.show(ev, `<b>${esc(d.name)}</b><span>${esc(d.team)}</span>
        <dl><dt>${k >= 0 ? "Lap" : "Start"}</dt><dd>${k >= 0 ? laps[k] : "grid"}</dd><dt>Position</dt><dd>P${place ?? "-"}</dd>
        <dt>Gap to leader</dt><dd>${gap == null ? "-" : gap < 0.005 ? "leading" : "+" + gap.toFixed(1) + " s"}</dd></dl>`);
    });
    hit.addEventListener("pointerleave", () => { focus.set(null); tip.hide(); dot.setAttribute("visibility", "hidden"); });
  });
}

/** Tyre strategy: one ribbon per driver, a segment per stint. */
export function stintRibbons(host, rows, drivers, totalLaps, { labels = null } = {}) {
  responsive(host, (W) => {
    host.innerHTML = "";
    const rowH = 26, m = { t: 6, r: 14, b: 26, l: labels ? 132 : 44 }, H = m.t + m.b + rows.length * rowH;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": "Tyre strategy by driver" }, host);
    const x = lin(0, totalLaps, m.l, W - m.r);
    const step = totalLaps > 60 ? 10 : 5;
    for (let n = step; n <= totalLaps; n += step) {
      el("line", { x1: x(n), x2: x(n), y1: m.t, y2: H - m.b, stroke: INK.hair, opacity: 0.5 }, svg);
      label(svg, n, { x: x(n), y: H - m.b + 16, "text-anchor": "middle" });
    }
    label(svg, "LAP", { x: m.l, y: H - m.b + 16, class: "ax ax--cap" });
    rows.forEach((row, i) => {
      const y = m.t + i * rowH, d = drivers?.[row.code];
      const g = el("g", { "data-code": row.code }, svg);
      label(g, labels ? labels[i] : row.code, { x: m.l - 10, y: y + rowH / 2 + 4, "text-anchor": "end", class: labels ? "ax" : "ax ax--code" });
      for (const s of row.stints) {
        const x0 = x(s.from - 1) + 1, x1 = x(s.to) - 1, w = Math.max(2, x1 - x0);
        const rect = el("rect", { x: x0, y: y + 4, width: w, height: rowH - 8, rx: 3, fill: COMPOUND[s.compound] || COMPOUND.UNKNOWN }, g);
        if (w > 22) label(g, s.compound[0], { x: x0 + w / 2, y: y + rowH / 2 + 4, "text-anchor": "middle", class: "ax ax--on" });
        rect.addEventListener("pointermove", (ev) => tip.show(ev, `<b>${esc(d ? d.name : labels?.[i] ?? row.code)}</b><span>${compoundName(s.compound)} tyres</span>
          <dl><dt>Laps</dt><dd>${s.from}–${s.to} (${s.laps})</dd>
          ${s.age ? `<dt>Tyre age at start</dt><dd>${s.age} laps</dd>` : ""}
          ${s.pace ? `<dt>Median pace</dt><dd>${lapTime(s.pace)}</dd>` : ""}</dl>`));
        rect.addEventListener("pointerleave", tip.hide);
      }
    });
    focus.on((code) => svg.querySelectorAll("g[data-code]").forEach((g) => g.setAttribute("opacity", !code || g.dataset.code === code ? 1 : 0.25)));
  });
}

export function compoundLegend(host, compounds) {
  host.innerHTML = compounds.map((c) => `<span class="key"><i style="background:${COMPOUND[c]}"></i>${compoundName(c)}</span>`).join("");
}

/** Clean-lap pace: every lap as a dot, the median as a tick, sorted fastest first. */
export function paceStrips(host, pace, drivers) {
  responsive(host, (W) => {
    host.innerHTML = "";
    const rowH = 24, m = { t: 8, r: 64, b: 28, l: 44 }, H = m.t + m.b + pace.length * rowH;
    const all = pace.flatMap((p) => p.times).sort((a, b) => a - b);
    const lo = all[0], hi = all[Math.floor(all.length * 0.97)];
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": "Clean lap times by driver" }, host);
    const x = lin(lo - 0.15, hi + 0.15, m.l, W - m.r);
    for (let v = Math.ceil(lo); v <= hi; v += hi - lo > 6 ? 2 : 1) {
      el("line", { x1: x(v), x2: x(v), y1: m.t, y2: H - m.b, stroke: INK.hair, opacity: 0.5 }, svg);
      label(svg, lapTime(v).slice(0, -2), { x: x(v), y: H - m.b + 16, "text-anchor": "middle" });
    }
    pace.forEach((p, i) => {
      const y = m.t + i * rowH + rowH / 2, d = drivers[p.code];
      const g = el("g", { "data-code": p.code }, svg);
      label(g, p.code, { x: m.l - 10, y: y + 4, "text-anchor": "end", class: "ax ax--code" });
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: INK.raised }, g);
      p.times.forEach((t, k) => {
        if (t > hi + 0.15) return;
        const jitter = (((k * 7919) % 13) / 13 - 0.5) * 9; // deterministic spread
        const c = el("circle", { cx: x(t), cy: y + jitter, r: 2.6, fill: d.color, opacity: 0.6 }, g);
        c.addEventListener("pointermove", (ev) => tip.show(ev, `<b>${esc(d.name)}</b><span>${esc(d.team)}</span><dl><dt>Lap time</dt><dd>${lapTime(t)}</dd></dl>`));
        c.addEventListener("pointerleave", tip.hide);
      });
      el("line", { x1: x(p.median), x2: x(p.median), y1: y - 9, y2: y + 9, stroke: INK.paper, "stroke-width": 2.5, "stroke-linecap": "round" }, g);
      label(g, i === 0 ? lapTime(p.median) : signed(p.gap), { x: W - m.r + 8, y: y + 4, class: "ax ax--num" });
    });
    focus.on((code) => svg.querySelectorAll("g[data-code]").forEach((g) => g.setAttribute("opacity", !code || g.dataset.code === code ? 1 : 0.22)));
  });
}

/** Horizontal bars for a short list of labelled values (one series, one colour). */
export function bars(host, rows, { format = (v) => v, colour = "#a26bff" } = {}) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value))) || 1;
  host.innerHTML = rows.map((r) => `
    <div class="hbar"><span class="hbar__k">${esc(r.label)}</span>
      <span class="hbar__t"><i style="width:${Math.max(1, (Math.abs(r.value) / max) * 100)}%;background:${r.colour || colour}"></i></span>
      <span class="hbar__v t-num">${esc(format(r.value))}</span></div>`).join("");
}

export { lin, INK, label, path, html };
