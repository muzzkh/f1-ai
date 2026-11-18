// Circuit renderer: draws real track geometry as an SVG and colours a lap along it.

import { el } from "./lib.js";
export { el };

const lerp = (a, b, t) => a + (b - a) * t;
const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const mix = (stops, t) => {
  t = Math.min(1, Math.max(0, t));
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1], [t1, c1] = stops[i];
      const u = (t - t0) / (t1 - t0), a = hex(c0), b = hex(c1);
      return `rgb(${a.map((v, k) => Math.round(lerp(v, b[k], u))).join(",")})`;
    }
  }
  return stops[stops.length - 1][1];
};

// One hue, dark to light: magnitude reads as brightness (purple sector ramp).
export const SPEED_RAMP = [[0, "#3a1d7a"], [0.45, "#7b46e6"], [0.75, "#b58cff"], [1, "#f6f0ff"]];
export const ramp = (t) => mix(SPEED_RAMP, t);
export const PEDAL = { throttle: "#35d07f", brake: "#ff4d5a", coast: "#8a8f9b" };

export class Track {
  constructor(svg, track, { width = 1000, pad = 78, data = true } = {}) {
    this.svg = svg;
    this.n = track.x.length;
    this.length = track.length;
    this.step = track.step;
    const xs = track.x, ys = track.y.map((v) => -v); // screen y runs downwards
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    this.scale = (width - 2 * pad) / (maxX - minX);
    this.h = (maxY - minY) * this.scale + 2 * pad;
    this.w = width;
    this.project = (x, y) => [(x - minX) * this.scale + pad, (-y - minY) * this.scale + pad];
    this.pts = xs.map((x, i) => [(x - minX) * this.scale + pad, (ys[i] - minY) * this.scale + pad]);
    // Real width is not in any data source: a stylised constant, never thinner than 14 units.
    this.tw = Math.max(14, 15 * this.scale);
    svg.setAttribute("viewBox", `0 0 ${width} ${this.h.toFixed(1)}`);
    this.d = "M" + this.pts.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join("L") + "Z";
    this._base();
    this._kerbs();
    this.dataLayer = el("g", { class: "fade" }, svg);
    this.segs = !data ? [] : this.pts.map((p, i) => {
      const q = this.pts[(i + 1) % this.n];
      return el("line", { x1: p[0].toFixed(1), y1: p[1].toFixed(1), x2: q[0].toFixed(1), y2: q[1].toFixed(1),
        "stroke-width": (this.tw * 0.62).toFixed(1), "stroke-linecap": "round" }, this.dataLayer);
    });
    this.marks = el("g", { class: "fade" }, svg);
  }

  normal(i) { // unit vector pointing to the left of travel
    const a = this.pts[(i - 2 + this.n) % this.n], b = this.pts[(i + 2) % this.n];
    const dx = b[0] - a[0], dy = b[1] - a[1], m = Math.hypot(dx, dy) || 1;
    return [dy / m, -dx / m];
  }

  _base() {
    const common = { d: this.d, pathLength: 1 };
    el("path", { ...common, class: "trk-glow", "stroke-width": this.tw * 2.2 }, this.svg);
    el("path", { ...common, class: "trk-edge draw", "stroke-width": this.tw + 3 }, this.svg);
    el("path", { ...common, class: "trk-asphalt draw", "stroke-width": this.tw }, this.svg);
  }

  _kerbs() { // stylised: red and white on the inside of tight corners
    const k = 4, n = this.n, turn = new Array(n);
    for (let i = 0; i < n; i++) {
      const a = this.pts[(i - k + n) % n], b = this.pts[i], c = this.pts[(i + k) % n];
      const h1 = Math.atan2(b[1] - a[1], b[0] - a[0]), h2 = Math.atan2(c[1] - b[1], c[0] - b[0]);
      let dh = h2 - h1;
      while (dh > Math.PI) dh -= 2 * Math.PI;
      while (dh < -Math.PI) dh += 2 * Math.PI;
      turn[i] = dh / (k * this.step); // radians per metre, sign gives the side
    }
    const g = el("g", { class: "fade" }, this.svg);
    let run = [];
    const flush = () => {
      if (run.length > 4) {
        const d = "M" + run.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join("L");
        const base = { d, fill: "none", "stroke-width": 3.4, "stroke-dasharray": "7 7" };
        el("path", { ...base, stroke: "#ff4d5a" }, g);
        el("path", { ...base, stroke: "#f4f1ea", "stroke-dashoffset": 7 }, g);
      }
      run = [];
    };
    for (let i = 0; i < n; i++) {
      if (Math.abs(turn[i]) > 1 / 95) {
        const nv = this.normal(i), side = turn[i] > 0 ? -1 : 1; // screen y is flipped
        const off = (this.tw / 2 + 2.2) * side;
        run.push([this.pts[i][0] + nv[0] * off, this.pts[i][1] + nv[1] * off]);
      } else flush();
    }
    flush();
  }

  /** Lines across the track at given distances, with a label beside each. */
  mark(s, label, long = false) {
    const i = Math.round(s / this.step) % this.n, p = this.pts[i], nv = this.normal(i);
    const half = this.tw / 2 + (long ? 9 : 6);
    el("line", { class: "trk-mark", x1: p[0] - nv[0] * half, y1: p[1] - nv[1] * half, x2: p[0] + nv[0] * half, y2: p[1] + nv[1] * half }, this.marks);
    const t = el("text", { class: "trk-tag", x: p[0] - nv[0] * (half + 16), y: p[1] - nv[1] * (half + 16) }, this.marks);
    t.textContent = label;
  }

  corners(list) {
    for (const c of list) {
      const p = this.pts[c.i % this.n], off = this.tw / 2 + 20;
      const t = el("text", { class: "trk-corner", x: p[0] + c.ax * off, y: p[1] - c.ay * off }, this.marks);
      t.textContent = c.label;
    }
  }

  /** The pit lane as traced by a car that stopped (display coordinates in metres). */
  pitLane(pit, project) {
    if (!pit) return;
    const d = "M" + pit.x.map((x, i) => project(x, pit.y[i]).map((v) => v.toFixed(1)).join(" ")).join("L");
    const g = el("g", { class: "fade" }, this.svg);
    this.svg.insertBefore(g, this.dataLayer);
    el("path", { d, fill: "none", stroke: "#3a3f4a", "stroke-width": this.tw * 0.55, "stroke-linecap": "round", "stroke-linejoin": "round" }, g);
    el("path", { d, fill: "none", stroke: "#7c7a73", "stroke-width": 1.2, "stroke-dasharray": "5 5" }, g);
  }

  colour(fn) { this.segs.forEach((seg, i) => seg.setAttribute("stroke", fn(i))); }

  /** Screen position at a fractional sample index. */
  at(fi) {
    const i = Math.floor(fi) % this.n, u = fi - Math.floor(fi), a = this.pts[i], b = this.pts[(i + 1) % this.n];
    return [lerp(a[0], b[0], u), lerp(a[1], b[1], u)];
  }

  car(colour) {
    const g = el("g", { class: "fade" }, this.svg);
    const tails = [[260, 0.16], [130, 0.3], [50, 0.6]].map(([len, op]) => {
      const p = el("path", { d: this.d, fill: "none", stroke: colour, "stroke-width": this.tw * 0.5, "stroke-linecap": "round",
        opacity: op, pathLength: this.length, "stroke-dasharray": `${len} ${this.length}` }, g);
      return [p, len];
    });
    const halo = el("circle", { r: this.tw * 1.25, fill: colour, opacity: 0.22 }, g);
    const dot = el("circle", { r: this.tw * 0.52, fill: colour, stroke: "#f4f1ea", "stroke-width": 2.5 }, g);
    return (fi) => {
      const [x, y] = this.at(fi), s = fi * this.step;
      for (const node of [halo, dot]) { node.setAttribute("cx", x.toFixed(1)); node.setAttribute("cy", y.toFixed(1)); }
      for (const [p, len] of tails) p.setAttribute("stroke-dashoffset", (len - s).toFixed(1));
    };
  }
}
