// Instrument cluster: speed, gear, throttle, brake, shift lights and longitudinal g.
// Only channels that exist in the data are shown (no DRS from 2026, no energy store).

import { el } from "./track.js";

const C = 120, R = 96;
const pt = (deg, r = R) => [C + r * Math.cos((deg * Math.PI) / 180), C + r * Math.sin((deg * Math.PI) / 180)];
const arc = (from, to, r = R) => {
  const [x0, y0] = pt(from, r), [x1, y1] = pt(to, r);
  const large = Math.abs(to - from) > 180 ? 1 : 0, sweep = to > from ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${large} ${sweep} ${x1.toFixed(2)} ${y1.toFixed(2)}`;
};
const text = (parent, str, attrs) => { const t = el("text", attrs, parent); t.textContent = str; return t; };

export function cluster(host, { rpmMax }) {
  const svg = el("svg", { viewBox: "0 0 240 240", role: "img", "aria-label": "Live speed, gear, throttle and brake" }, host);
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const paper = v("--paper"), muted = v("--muted"), hair = v("--hairline"), purple = v("--purple");
  const mono = v("--mono"), font = v("--font");

  el("circle", { cx: C, cy: C, r: 117, fill: "#0d0f12", stroke: hair }, svg);
  el("circle", { cx: C, cy: C, r: 80, fill: "none", stroke: hair, "stroke-dasharray": "1 5" }, svg);

  // pedals: brake on the left, throttle on the right, both filling upwards
  const gauge = (from, to, colour) => {
    el("path", { d: arc(from, to), fill: "none", stroke: "#22262d", "stroke-width": 11, "stroke-linecap": "round" }, svg);
    return el("path", { d: arc(from, to), fill: "none", stroke: colour, "stroke-width": 11, "stroke-linecap": "round",
      pathLength: 100, "stroke-dasharray": "0 100", style: "transition: stroke-dasharray 90ms linear, opacity 90ms linear" }, svg);
  };
  const brake = gauge(128, 232, v("--brake"));
  const throttle = gauge(52, -52, v("--throttle"));
  const label = { "font-family": font, "font-weight": 600, "font-stretch": "75%", "font-size": 8.5, "letter-spacing": 1.4, fill: muted, "text-anchor": "middle" };
  text(svg, "BRK", { ...label, x: pt(140, 70)[0], y: pt(140, 70)[1] + 3 });
  text(svg, "THR", { ...label, x: pt(40, 70)[0], y: pt(40, 70)[1] + 3 });

  // shift lights: the last four turn purple at the top of the rev range
  const N = 14, leds = [];
  for (let i = 0; i < N; i++) {
    leds.push(el("rect", { x: C - 56 + i * 8.15, y: 58, width: 5.6, height: 7.5, rx: 1.2, fill: "#22262d" }, svg));
  }
  const rpmText = text(svg, "", { x: C, y: 50, "font-family": mono, "font-size": 9, fill: muted, "text-anchor": "middle" });

  const speed = text(svg, "0", { x: C, y: 124, "font-family": mono, "font-weight": 700, "font-style": "italic", "font-size": 54,
    "letter-spacing": -2, fill: paper, "text-anchor": "middle" });
  text(svg, "KM/H", { ...label, x: C, y: 139 });

  el("rect", { x: C - 19, y: 150, width: 38, height: 40, rx: 4, fill: "none", stroke: hair }, svg);
  const gear = text(svg, "N", { x: C, y: 181, "font-family": mono, "font-weight": 700, "font-size": 30, fill: paper, "text-anchor": "middle" });

  // longitudinal g along the bottom: braking swings left, acceleration right
  el("path", { d: arc(112, 68, 108), fill: "none", stroke: "#22262d", "stroke-width": 3, "stroke-linecap": "round" }, svg);
  el("line", { x1: pt(90, 103)[0], y1: pt(90, 103)[1], x2: pt(90, 113)[0], y2: pt(90, 113)[1], stroke: muted, "stroke-width": 1 }, svg);
  const gDot = el("circle", { r: 4, fill: paper }, svg);
  const gText = text(svg, "", { x: C, y: 206, "font-family": mono, "font-size": 9, fill: muted, "text-anchor": "middle" });

  const rpmLow = rpmMax * 0.8;
  return ({ speed: s, gear: g, throttle: th, brake: br, rpm, g: lg }) => {
    speed.textContent = Math.round(s);
    gear.textContent = g > 0 ? g : "N";
    throttle.setAttribute("stroke-dasharray", `${th.toFixed(1)} 100`);
    throttle.style.opacity = th < 1.5 ? 0 : 1;
    brake.setAttribute("stroke-dasharray", `${br ? 100 : 0} 100`);
    brake.style.opacity = br ? 1 : 0;
    const lit = Math.round(Math.min(1, Math.max(0, (rpm - rpmLow) / (rpmMax - rpmLow))) * N);
    leds.forEach((led, i) => led.setAttribute("fill", i < lit ? (i >= N - 4 ? purple : paper) : "#22262d"));
    rpmText.textContent = `${(Math.round(rpm / 50) * 50).toLocaleString("en-US").replace(",", " ")} RPM`;
    const a = 90 + Math.max(-22, Math.min(22, (-lg / 5) * 22)); // 5 g of braking reaches the left end
    const [gx, gy] = pt(a, 108);
    gDot.setAttribute("cx", gx.toFixed(1)); gDot.setAttribute("cy", gy.toFixed(1));
    gDot.setAttribute("fill", lg < -0.6 ? v("--brake") : lg > 0.4 ? v("--throttle") : paper);
    gText.textContent = `${lg >= 0 ? "+" : "−"}${Math.abs(lg).toFixed(1)} G`;
  };
}
