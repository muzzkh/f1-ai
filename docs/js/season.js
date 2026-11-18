// Season page: circuit calendar, championship progression, points grid.

import { $, esc, el, context, shell, tip, focus, responsive } from "./lib.js";
import { ramp } from "./track.js";
import { lin, INK, label, path, driverChips, bars } from "./charts.js";

const ctx = await context();
shell("season.html", ctx);
const S = ctx.season;
document.title = `${S.year} season · F1 AI`;

// the lower-placed driver of each team gets the dashed line
const seen = new Set();
const drivers = Object.fromEntries(S.drivers.map((d) => {
  const second = seen.has(d.team); seen.add(d.team);
  return [d.code, { ...d, second }];
}));
const order = S.drivers.map((d) => d.code);
const total = (d) => d.points.at(-1) ?? 0;

const [lead, second] = S.drivers;
const run = S.rounds.filter((r) => r.done).length;
$("eyebrow").innerHTML = [`${run} of ${S.rounds.length} rounds run`, `Standings after round ${S.last_round}`].map((s) => `<span>${esc(s)}</span>`).join("");
$("title").innerHTML = `${S.year}<br><em>Season</em>`;
const left = (S.rounds.length - run);
$("tiles").innerHTML = [
  ["Championship leader", lead.name, `${lead.team} · ${total(lead)} points`],
  ["Lead over second", `${total(lead) - total(second)} pts`, `${second.name}, ${second.team}`],
  ["Constructors' leader", S.constructors[0]?.team ?? "-", `${S.constructors[0]?.points ?? 0} points`],
  ["Still to run", `${left} round${left === 1 ? "" : "s"}`, S.rounds.find((r) => !r.done)?.name ?? "Season complete"],
].map(([k, v, n]) => `<div class="tile"><span class="t-label">${esc(k)}</span><b>${esc(v)}</b><small>${esc(n)}</small></div>`).join("");

// ---------- calendar ----------
const shape = (o) => {
  if (!o) return "";
  const xs = o.x, ys = o.y.map((v) => -v);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const k = Math.min(150 / (x1 - x0), 96 / (y1 - y0));
  const d = "M" + xs.map((x, i) => `${(80 + (x - (x0 + x1) / 2) * k).toFixed(1)} ${(54 + (ys[i] - (y0 + y1) / 2) * k).toFixed(1)}`).join("L") + "Z";
  return `<svg viewBox="0 0 160 108" aria-hidden="true"><path d="${d}"/></svg>`;
};
const colourOf = (code) => drivers[code]?.color ?? "#7c7a73";
$("calendar").innerHTML = S.rounds.map((r) => {
  const inner = `
    <header><span class="t-num">R${String(r.round).padStart(2, "0")}</span><span class="t-label">${esc(r.date)}${r.sprint ? " · sprint" : ""}</span></header>
    ${shape(r.outline)}
    <h3>${esc(r.name.replace(" Grand Prix", ""))}</h3>
    <p>${esc(r.circuit ?? "")}${r.outline ? ` · ${r.outline.km} km` : ""}</p>
    ${r.winner ? `<footer style="--team:${colourOf(r.winner.code)}"><i></i><b>${esc(r.winner.code ?? "")}</b><span>${esc(r.winner.name)}</span></footer>`
      : `<footer class="is-open"><span>${r.done ? "Result pending" : "Upcoming"}</span></footer>`}`;
  return r.built ? `<a class="round-card is-built" href="index.html?r=${r.round}">${inner}</a>`
    : `<div class="round-card${r.done ? "" : " is-future"}">${inner}</div>`;
}).join("");

// ---------- championship progression ----------
driverChips($("chips"), drivers, order);
responsive($("progress"), (W) => {
  const host = $("progress");
  host.innerHTML = "";
  const H = 460, m = { t: 14, r: 86, b: 30, l: 44 }, n = S.last_round;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": "Championship points after each round" }, host);
  const max = total(lead), x = lin(1, Math.max(2, n), m.l, W - m.r), y = lin(0, max * 1.04, H - m.b, m.t);
  for (let v = 0; v <= max; v += max > 250 ? 100 : 50) {
    el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: INK.hair, opacity: 0.5 }, svg);
    label(svg, v, { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" });
  }
  for (let r = 1; r <= n; r++) if (n <= 12 || r % 2 === 0 || r === 1) label(svg, `R${r}`, { x: x(r), y: H - m.b + 16, "text-anchor": "middle" });
  const xs = Array.from({ length: n }, (_, i) => x(i + 1)), nodes = {};
  const g = el("g", {}, svg);
  let lastY = -99;
  for (const d of S.drivers) {
    const ys = d.points.map(y);
    const p = el("path", { d: path(xs, ys), fill: "none", stroke: d.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-dasharray": drivers[d.code].second ? "5 4" : null }, g);
    // direct labels at the right edge, skipped where they would collide
    const ly = ys.at(-1);
    let tag = null;
    if (Math.abs(ly - lastY) > 12) { tag = label(svg, `${d.code}  ${total(d)}`, { x: W - m.r + 8, y: ly + 4, class: "ax ax--code" }); lastY = ly; }
    nodes[d.code] = { p, ys, tag };
  }
  const dot = el("circle", { r: 4.5, fill: INK.paper, stroke: "#0a0b0d", "stroke-width": 2, visibility: "hidden" }, svg);
  focus.on((code) => {
    for (const [c, node] of Object.entries(nodes)) {
      const on = !code || c === code;
      node.p.setAttribute("opacity", on ? 1 : 0.14); node.p.setAttribute("stroke-width", code && on ? 3 : 2);
      if (node.tag) node.tag.setAttribute("opacity", on ? 1 : 0.25);
    }
    if (code && nodes[code]) g.appendChild(nodes[code].p);
  });
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  hit.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect(), px = ev.clientX - box.left, py = ev.clientY - box.top;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (n - 1))));
    let best = null, dist = 1e9;
    for (const d of S.drivers) { const dy = Math.abs(nodes[d.code].ys[i] - py); if (dy < dist) { dist = dy; best = d; } }
    focus.set(best.code);
    dot.setAttribute("cx", xs[i]); dot.setAttribute("cy", nodes[best.code].ys[i]); dot.setAttribute("visibility", "visible");
    const gained = best.points[i] - (i ? best.points[i - 1] : 0);
    tip.show(ev, `<b>${esc(best.name)}</b><span>${esc(best.team)}</span>
      <dl><dt>After</dt><dd>${esc(S.rounds[i]?.name.replace(" Grand Prix", "") ?? `round ${i + 1}`)}</dd>
      <dt>Points</dt><dd>${best.points[i]}</dd><dt>Scored there</dt><dd>+${gained}</dd></dl>`);
  });
  hit.addEventListener("pointerleave", () => { focus.set(null); tip.hide(); dot.setAttribute("visibility", "hidden"); });
});

// ---------- points grid ----------
const perRound = (d) => d.points.map((p, i) => p - (i ? d.points[i - 1] : 0));
const biggest = Math.max(1, ...S.drivers.flatMap(perRound));
$("grid").innerHTML = `<table class="heat"><thead><tr><th></th>${S.rounds.slice(0, S.last_round).map((r) =>
  `<th title="${esc(r.name)}">${String(r.round).padStart(2, "0")}</th>`).join("")}<th>Total</th></tr></thead><tbody>${S.drivers.map((d) => `
  <tr data-code="${d.code}" style="--team:${d.color}"><th><i></i>${d.code}</th>${perRound(d).map((p, i) =>
    `<td title="${esc(d.name)} · ${esc(S.rounds[i]?.name ?? "")}: ${p} points" style="${p > 0 ? `background:${ramp(0.08 + 0.72 * (p / biggest))};color:${p / biggest > 0.55 ? "#0a0b0d" : "#f4f1ea"}` : ""}">${p > 0 ? p : ""}</td>`).join("")}
  <td class="t-num sum">${total(d)}</td></tr>`).join("")}</tbody></table>`;
focus.on((code) => document.querySelectorAll(".heat tbody tr").forEach((tr) => tr.classList.toggle("is-dim", !!code && tr.dataset.code !== code)));

bars($("teams"), S.constructors.map((t) => ({ label: t.team, value: t.points })), { format: (v) => `${v} pts` });
