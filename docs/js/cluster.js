// Instrument cluster: speed, gear, throttle, brake, revs, shift lights and longitudinal g.
// Geometry comes from data/cluster.json, the same definition the video renderer draws
// from (src/f1ai/video/cluster.json), so the cluster on the site and the one burnt
// into rendered video always match. Only channels that exist in the data are shown:
// there is no DRS from 2026 and no energy-store data.

import { el, load } from "./lib.js";

const spec = await load("cluster.json");
const [CX, CY] = spec.center;
const pt = (deg, r) => [CX + r * Math.cos((deg * Math.PI) / 180), CY + r * Math.sin((deg * Math.PI) / 180)];
const arc = (a) => {
  const [x0, y0] = pt(a.from, a.r), [x1, y1] = pt(a.to, a.r);
  const large = Math.abs(a.to - a.from) > 180 ? 1 : 0, sweep = a.to > a.from ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${a.r} ${a.r} 0 ${large} ${sweep} ${x1.toFixed(2)} ${y1.toFixed(2)}`;
};
const text = (parent, str, attrs) => { const t = el("text", attrs, parent); t.textContent = str; return t; };

export function cluster(host, { rpmMax }) {
  const C = spec.colors, css = getComputedStyle(document.documentElement);
  const mono = css.getPropertyValue("--mono").trim(), font = css.getPropertyValue("--font").trim();
  const svg = el("svg", { viewBox: `0 0 ${spec.size} ${spec.size}`, role: "img", "aria-label": "Live speed, gear, throttle, brake and revs" }, host);
  el("circle", { cx: CX, cy: CY, r: spec.panel_r, fill: C.panel, stroke: C.hairline }, svg);

  const gauge = (a, colour, cap = "round") => {
    el("path", { d: arc(a), fill: "none", stroke: C.track, "stroke-width": a.w, "stroke-linecap": cap }, svg);
    return el("path", { d: arc(a), fill: "none", stroke: colour, "stroke-width": a.w, "stroke-linecap": cap,
      pathLength: 100, "stroke-dasharray": "0 100", style: "transition: stroke-dasharray 90ms linear, opacity 90ms linear" }, svg);
  };
  const brake = gauge(spec.brake, C.brake), throttle = gauge(spec.throttle, C.throttle), revs = gauge(spec.rpm, C.rpm, "butt");

  const cap = { "font-family": font, "font-weight": 600, "font-stretch": "75%", "font-size": 8.5, "letter-spacing": 1.4, fill: C.muted, "text-anchor": "middle" };
  for (const l of spec.labels) text(svg, l.text, { ...cap, x: l.x, y: l.y });

  const L = spec.leds, leds = [];
  for (let i = 0; i < L.n; i++) leds.push(el("rect", { x: L.x + i * L.pitch, y: L.y, width: L.w, height: L.h, rx: 1.2, fill: C.track }, svg));
  const rpmText = text(svg, "", { x: CX, y: L.y - 8, "font-family": mono, "font-size": 9, fill: C.muted, "text-anchor": "middle" });

  const speed = text(svg, "0", { x: spec.speed.x, y: spec.speed.baseline, "font-family": mono, "font-weight": 700, "font-style": "italic",
    "font-size": spec.speed.size, "letter-spacing": -2, fill: C.paper, "text-anchor": "middle" });
  const gb = spec.gear.box;
  el("rect", { x: gb[0] - 2, y: gb[1] - 1, width: gb[2] - gb[0] + 4, height: gb[3] - gb[1] + 2, rx: 4, fill: "none", stroke: C.hairline }, svg);
  const gear = text(svg, "N", { x: spec.gear.x, y: spec.gear.baseline, "font-family": mono, "font-weight": 700, "font-size": spec.gear.size, fill: C.paper, "text-anchor": "middle" });

  // longitudinal g along the bottom: braking swings left, acceleration right
  const G = spec.g, mid = (G.from + G.to) / 2, half = Math.abs(G.from - G.to) / 2;
  el("path", { d: arc(G), fill: "none", stroke: C.track, "stroke-width": G.w, "stroke-linecap": "round" }, svg);
  el("line", { x1: pt(mid, G.r - 5)[0], y1: pt(mid, G.r - 5)[1], x2: pt(mid, G.r + 5)[0], y2: pt(mid, G.r + 5)[1], stroke: C.muted }, svg);
  const gDot = el("circle", { r: 4, fill: C.paper }, svg);
  const gText = text(svg, "", { x: CX, y: gb[3] + 16, "font-family": mono, "font-size": 9, fill: C.muted, "text-anchor": "middle" });

  const [r0, r1] = spec.rpm.scale, ledLow = rpmMax * L.from;
  return ({ speed: s, gear: g, throttle: th, brake: br, rpm, g: lg }) => {
    speed.textContent = Math.round(s);
    gear.textContent = g > 0 ? g : "N";
    throttle.setAttribute("stroke-dasharray", `${th.toFixed(1)} 100`);
    throttle.style.opacity = th < 1.5 ? 0 : 1;
    brake.setAttribute("stroke-dasharray", `${br ? 100 : 0} 100`);
    brake.style.opacity = br ? 1 : 0;
    revs.setAttribute("stroke-dasharray", `${(Math.min(1, Math.max(0, (rpm - r0) / (r1 - r0))) * 100).toFixed(1)} 100`);
    const lit = Math.round(Math.min(1, Math.max(0, (rpm - ledLow) / (rpmMax - ledLow))) * L.n);
    leds.forEach((led, i) => led.setAttribute("fill", i < lit ? (i >= L.n - L.purple ? C.rpm : C.paper) : C.track));
    rpmText.textContent = `${(Math.round(rpm / 50) * 50).toLocaleString("en-US").replace(",", " ")} RPM`;
    const a = mid + Math.max(-half, Math.min(half, (-(lg ?? 0) / G.range) * half));
    const [gx, gy] = pt(a, G.r);
    gDot.setAttribute("cx", gx.toFixed(1)); gDot.setAttribute("cy", gy.toFixed(1));
    gDot.setAttribute("fill", lg < -0.6 ? C.brake : lg > 0.4 ? C.throttle : C.paper);
    gText.textContent = lg == null ? "" : `${lg >= 0 ? "+" : "−"}${Math.abs(lg).toFixed(1)} G`;
  };
}
