// Shared helpers: page shell, data loading, formatting, tooltip, hover focus.

export const $ = (id) => document.getElementById(id);
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
export const params = new URLSearchParams(location.search);

const NS = "http://www.w3.org/2000/svg";
export const el = (name, attrs = {}, parent) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
};
export const html = (tag, attrs = {}, parent, inner) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  if (inner != null) node.innerHTML = inner;
  if (parent) parent.appendChild(node);
  return node;
};

export const lapTime = (s) => {
  if (s == null || !isFinite(s)) return "-";
  const m = Math.floor(s / 60), r = s - m * 60;
  return m ? `${m}:${r.toFixed(3).padStart(6, "0")}` : r.toFixed(3);
};
export const signed = (v, n = 3) => (v == null || !isFinite(v) ? "-" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(n)}`);

/** Black or white, whichever reads better on a given team colour. */
export const inkOn = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? "#131316" : "#ffffff";
};

export const COMPOUND = { SOFT: "#f0384a", MEDIUM: "#f5c400", HARD: "#ebe9e3", INTERMEDIATE: "#3fbf5a", WET: "#3987e5", UNKNOWN: "#6b6e76" };
export const compoundName = (c) => (c || "unknown").charAt(0) + (c || "unknown").slice(1).toLowerCase();

const cache = new Map();
export const load = (path) => {
  if (!cache.has(path)) cache.set(path, fetch(`data/${path}`).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  return cache.get(path);
};

/** Season index plus the round this page is about (?r=NN, default latest). */
export async function context() {
  const season = await load("season.json");
  const wanted = parseInt(params.get("r"), 10);
  const built = season.rounds.filter((x) => x.built).map((x) => x.round);
  const round = built.includes(wanted) ? wanted : season.latest;
  return { season, round, dir: `r${String(round).padStart(2, "0")}`, info: season.rounds.find((x) => x.round === round) };
}

const PAGES = [["index.html", "Race"], ["duel.html", "Lap duel"], ["season.html", "Season"], ["video.html", "Video lab"], ["about.html", "About"]];

/** Fill the shared header and footer. `active` is the page file name. */
export function shell(active, ctx) {
  const q = ctx.round !== ctx.season.latest ? `?r=${ctx.round}` : "";
  const perRound = new Set(["index.html", "duel.html"]);
  const links = PAGES.map(([href, label]) =>
    `<a href="${href}${perRound.has(href) ? q : ""}"${href === active ? ' aria-current="page"' : ""}>${label}</a>`).join("");
  const options = ctx.season.rounds.filter((x) => x.built).map((x) =>
    `<option value="${x.round}"${x.round === ctx.round ? " selected" : ""}>R${String(x.round).padStart(2, "0")} · ${esc(x.name.replace(" Grand Prix", ""))}</option>`).join("");
  $("nav").innerHTML = `
    <div class="wrap nav__in">
      <a class="mark" href="index.html">F1<i>AI</i></a>
      <nav class="nav__links" aria-label="Sections">${links}</nav>
      <label class="round"><span class="t-label">${ctx.season.year}</span>
        <select id="roundPick" aria-label="Race weekend">${options}</select></label>
    </div>`;
  $("roundPick").addEventListener("change", (ev) => {
    const page = perRound.has(active) ? active : "index.html";
    location.href = `${page}?r=${ev.target.value}`;
  });
  $("foot").innerHTML = `
    <div class="wrap foot">
      <p>Circuit shape, elevation, corner numbers, pit lane and every lap are real data: timing and GPS from <a href="https://openf1.org">OpenF1</a>, the circuit survey from MultiViewer, standings from Jolpica. Track width and kerbs are stylised, because no public source has them. Car telemetry is sampled about four times a second, so traces are smooth between samples rather than exact. Snapshot built ${esc(ctx.season.generated)}.</p>
      <p>Unofficial fan project. Not associated in any way with the Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX and related marks are trade marks of Formula One Licensing B.V. · <a href="${esc(ctx.season.repo)}">Source on GitHub</a></p>
    </div>`;
}

// ---------- tooltip ----------
let tipNode;
export const tip = {
  show(ev, inner) {
    tipNode ||= html("div", { class: "tip", role: "status" }, document.body);
    tipNode.innerHTML = inner;
    tipNode.hidden = false;
    const pad = 14, w = tipNode.offsetWidth, h = tipNode.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
    tipNode.style.transform = `translate(${Math.max(8, x)}px, ${Math.max(8, y)}px)`;
  },
  hide() { if (tipNode) tipNode.hidden = true; },
};

// ---------- hover focus shared between charts ----------
const listeners = new Set();
let focused = null, pinned = null;
export const focus = {
  on(fn) { listeners.add(fn); fn(pinned ?? focused); },
  set(code) { if (code !== focused) { focused = code; listeners.forEach((fn) => fn(pinned ?? focused)); } },
  pin(code) { pinned = pinned === code ? null : code; listeners.forEach((fn) => fn(pinned ?? focused)); },
  get pinned() { return pinned; },
};

/** Call `render(width)` now and whenever the host's width changes. */
export function responsive(host, render) {
  let last = 0, timer;
  const run = () => {
    const cs = getComputedStyle(host); // draw inside the padding of a panel
    const w = Math.round(host.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
    if (w && w !== last) { last = w; render(w); }
  };
  new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(run, 80); }).observe(host);
  run();
}
