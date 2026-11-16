"""Build the static website (docs/) from live data.

GitHub Pages cannot run the Streamlit dashboard, so this exports a snapshot
of the latest race weekend as one self-contained page with interactive charts.

    python dashboard/build_site.py [--year 2025 --event "Abu Dhabi"] [--repo-url URL]
"""

from __future__ import annotations

import argparse
import asyncio
import html
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import plotly.offline
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import charts  # noqa: E402
from f1ai import analysis as an  # noqa: E402
from f1ai import data, video  # noqa: E402
from f1ai.config import ROOT, VIDEO_DIR  # noqa: E402

esc = html.escape
fmt = an.format_laptime
SHORT = {"SOFT": "S", "MEDIUM": "M", "HARD": "H", "INTERMEDIATE": "I", "WET": "W"}


def fig_html(fig, div_id: str) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id,
                       config={**charts.CONFIG, "responsive": True})


def tiles(items: list[tuple[str, str, str]]) -> str:
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div><div class="n">{esc(n)}</div></div>'
        for k, v, n in items) + "</div>"


def table(df: pd.DataFrame, numeric: set[str] = frozenset()) -> str:
    head = "".join(f'<th class="{"num" if c in numeric else ""}">{esc(str(c))}</th>' for c in df.columns)
    rows = "".join(
        "<tr>" + "".join(f'<td class="{"num" if c in numeric else ""}">{esc(str(v))}</td>' for c, v in zip(df.columns, r)) + "</tr>"
        for r in df.itertuples(index=False))
    return f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'


def whole(col) -> list[str]:
    return [str(int(v)) if pd.notna(v) else "-" for v in col]


# ----------------------------------------------------------------------------
# sections
# ----------------------------------------------------------------------------

def section_race(race) -> str:
    res = an.results_frame(race)
    w = an.weather_summary(race)
    best = res.dropna(subset=["BestLap_s"]).sort_values("BestLap_s").iloc[0]
    top = res.iloc[0]
    t = [("Winner", top["Name"], top["Team"]),
         ("Fastest lap", fmt(best["BestLap_s"]), best["Name"]),
         ("Race distance", f"{race.total_laps} laps", race.circuit)]
    if w:
        t.append(("Track temperature", f"{w['track_temp_c']:.0f} °C", "Rain during the race" if w["rain"] else "Dry"))
    gained = pd.to_numeric(res["Grid"], errors="coerce") - pd.to_numeric(res["Pos"], errors="coerce")
    tbl = pd.DataFrame({
        "Pos": whole(res["Pos"]), "Driver": res["Name"], "Team": res["Team"], "Grid": whole(res["Grid"]),
        "+/-": ["" if pd.isna(g) or g == 0 else f"{int(g):+d}" for g in gained],
        "Gap": ["Winner" if i == 0 else f"+{g:.3f}" if pd.notna(g) else s
                for i, (g, s) in enumerate(zip(res["Gap_s"], res["Status"]))],
        "Pts": [f"{p:g}" if pd.notna(p) else "-" for p in res["Points"]],
        "Best lap": res["BestLap_s"].map(fmt)})
    return f"""
<section id="race">
  <h2>{esc(race.event_name)} {race.year}</h2>
  <p class="sub">Race · {esc(race.circuit)}, {esc(race.country)} · {race.date_start.strftime('%d %B %Y')}</p>
  {tiles(t)}
  {table(tbl, {"Pos", "Grid", "+/-", "Gap", "Pts", "Best lap"})}
  <div class="chart">{fig_html(charts.position_chart(race), "fig-positions")}</div>
  <p class="note">Dotted lines are the second driver of each team. Hover a line for the driver and position.</p>
</section>"""


def section_pace(race) -> str:
    stints = an.stints(race)
    return f"""
<section id="pace">
  <h2>Pace and tyres</h2>
  <p class="sub">Who was actually quick, once pit laps, safety-car laps and traffic-slow laps are removed.</p>
  <div class="two">
    <div class="chart">{fig_html(charts.pace_bars(an.race_pace(race), race), "fig-pace")}</div>
    <div class="chart">{fig_html(charts.tyre_strategy(stints, race.total_laps), "fig-tyres")}</div>
  </div>
</section>"""


def find_strategy_race(year: int, rnd: int):
    """Latest race (this one or earlier) where the dry-tyre model can be fitted."""
    candidates = [(year, r) for r in range(rnd, 0, -1)]
    try:
        prev = data.completed_events(year - 1)
        candidates += [(year - 1, int(r)) for r in prev["RoundNumber"][::-1]]
    except data.DataError:
        pass
    for y, r in candidates[:8]:
        try:
            ses = data.load_session(y, r, "R")
            model = an.fit_pace_model(ses)
            return ses, model, an.simulate_strategies(ses, model)
        except (ValueError, data.DataError):
            continue
    return None


def section_strategy(found, current) -> str:
    if not found:
        return ""
    ses, model, sim = found
    loss = an.pit_loss(ses)
    actual = " – ".join(f"{SHORT.get(c, '?')} {n}" for c, n in zip(sim["winner_actual"]["compounds"], sim["winner_actual"]["stint_laps"]))
    why = "" if (ses.year, ses.round) == (current.year, current.round) else (
        f" The {esc(current.event_name)} was run in mixed conditions, where a dry-tyre model does not apply, "
        f"so this shows the most recent dry race.")
    t = [("Fuel effect", f"{model.fuel_effect * 1000:+.0f} ms/lap", "the car gets quicker as fuel burns off"),
         ("Pit stop time loss", f"{loss['seconds']:.1f} s", f"{loss['stops_measured']} stops measured"),
         ("Model fit (R²)", f"{model.r2:.2f}", f"{model.n_laps} clean laps"),
         ("Typical error", f"±{model.residual_std:.2f} s", "per lap")]
    return f"""
<section id="strategy">
  <h2>Tyre model and strategy</h2>
  <p class="sub">{esc(ses.event_name)} {ses.year}.{why}</p>
  {tiles(t)}
  <div class="two">
    <div class="chart">{fig_html(charts.degradation_bars(model), "fig-deg")}</div>
    <div class="chart">{fig_html(charts.strategy_options(sim), "fig-strategy")}</div>
  </div>
  <p class="note">What the winner ({esc(str(sim['winner']))}) actually ran: {esc(actual)} laps. A least-squares model separates driver pace,
  tyre wear per compound and fuel burn; strategies are then ranked by predicted race time. It assumes clear air, no safety cars
  and linear tyre wear, with stints capped at the longest run seen on each compound.</p>
</section>"""


def section_telemetry(quali) -> tuple[str, str, int]:
    drivers = data.driver_list(quali)
    cmp = an.compare_laps(quali, drivers[0], drivers[1])
    sa, sb = cmp["summary_a"], cmp["summary_b"]
    gap = cmp["lap_delta_s"]
    t = [(f"{sa['driver']} · lap {sa['lap_number']}", fmt(sa["lap_time_s"]), f"top speed {sa['top_speed_kmh']:.0f} km/h"),
         (f"{sb['driver']} · lap {sb['lap_number']}", fmt(sb["lap_time_s"]), f"top speed {sb['top_speed_kmh']:.0f} km/h"),
         ("Gap", f"{abs(gap):.3f} s", f"{sa['driver'] if gap > 0 else sb['driver']} faster"),
         ("Full throttle", f"{sa['full_throttle_pct']:.0f}% vs {sb['full_throttle_pct']:.0f}%",
          f"braking {sa['braking_pct']:.0f}% vs {sb['braking_pct']:.0f}%")]
    crn = cmp["corners"].rename(columns=lambda s: s.replace("MinSpeed_", "Min speed ").replace("Gain_", "Time gained by "))
    out = f"""
<section id="telemetry">
  <h2>Telemetry: the top two in qualifying</h2>
  <p class="sub">{esc(quali.event_name)} {quali.year} qualifying. Each driver's fastest lap of the session, lined up by GPS position.</p>
  {tiles(t)}
  <div class="chart">{fig_html(charts.telemetry_compare(cmp), "fig-telemetry")}</div>
  <div class="two">
    <div class="chart">{fig_html(charts.track_map(cmp), "fig-map")}</div>
    <div>{table(crn, set(crn.columns) - {"Corner"})}</div>
  </div>
  <p class="note">Sector-level gaps match official timing to a few hundredths of a second. Corner-level numbers are indicative:
  the public feed samples the car about four times a second.</p>
</section>"""
    return out, sa["driver"], sa["lap_number"]


def section_video(quali, driver: str, lap: int, assets: Path) -> str:
    tel = an.lap_telemetry(quali, driver, lap)
    clip = VIDEO_DIR / "site-demo.mp4"
    caption = f"{driver}  {quali.event_name} {quali.year}  Qualifying  lap {lap}"
    video.render_onboard(tel, clip, "demo-halo", max_seconds=30, caption=caption)
    ext = video.extract_telemetry(clip, "demo-halo")
    acc = video.accuracy(ext, tel)

    # short looping preview of the footage the reader was given
    cap = cv2.VideoCapture(str(clip))
    frames, i = [], 0
    while len(frames) < 100:
        ok, frame = cap.read()
        if not ok:
            break
        if i % 2 == 0:
            small = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
            frames.append(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
        i += 1
    cap.release()
    frames[0].save(assets / "onboard.webp", save_all=True, append_images=frames[1:], duration=80, loop=0, quality=55, method=4)
    boxed = video.draw_overlay(video.grab_frame(clip, 6.0), "demo-halo")
    h, w = boxed.shape[:2]
    crop = boxed[int(h * 0.60):, int(w * 0.30): int(w * 0.70)]
    cv2.imwrite(str(assets / "hud-boxes.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 88])

    t = [("Frames with speed read", f"{ext.attrs['speed_read_rate'] * 100:.1f}%", f"{ext.attrs['frames_read']} frames"),
         ("Speed error", f"{acc['speed_mae_kmh']:.2f} km/h", f"95% within {acc['speed_p95_kmh']:.1f} km/h"),
         ("Gear correct", f"{acc['gear_accuracy_pct']:.1f}%", "of samples"),
         ("Throttle error", f"{acc['throttle_mae_pct']:.1f} pts", "out of 100"),
         ("Brake agreement", f"{acc['brake_agreement_pct']:.1f}%", "on / off")]
    return f"""
<section id="video">
  <h2>Video to telemetry</h2>
  <p class="sub">Reading speed, gear, throttle, brake and RPM straight off the pixels of an onboard video.</p>
  <div class="two media">
    <figure><img src="assets/onboard.webp" alt="Rendered onboard clip with a speed and gear dial" loading="lazy">
      <figcaption>Test footage: {esc(driver)}'s lap rendered from its real telemetry, so the right answer is known.</figcaption></figure>
    <figure><img src="assets/hud-boxes.jpg" alt="The HUD with the regions the reader looks at outlined" loading="lazy">
      <figcaption>Where the reader looks. A small neural network reads the digits; gauges are measured by how far their colour extends.</figcaption></figure>
  </div>
  {tiles(t)}
  <div class="chart">{fig_html(charts.video_vs_reference(ext, tel, acc['offset_s']), "fig-video")}</div>
  <p class="note">Measured on footage this project renders itself. Real broadcast video has a different HUD design and needs its own
  layout profile, calibrated in the dashboard; that has not been tested yet.</p>
</section>"""


def section_championship(year: int) -> str:
    try:
        s = data.standings(year)
    except data.DataError:
        return ""
    if not s["drivers"]:
        return ""
    return f"""
<section id="championship">
  <h2>Championship</h2>
  <p class="sub">{year} standings after round {s['round']}.</p>
  <div class="two">
    <div class="chart">{fig_html(charts.standings_bars(s['drivers'], 'driver', 'Drivers (points)'), "fig-drivers")}</div>
    <div class="chart">{fig_html(charts.standings_bars(s['constructors'], 'team', 'Constructors (points)'), "fig-teams")}</div>
  </div>
</section>"""


def section_project(repo_url: str) -> str:
    from f1ai import mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    rows = pd.DataFrame([{"Tool": t.name, "What it does": " ".join((t.description or "").split())} for t in tools])
    cards = [
        ("Dashboard", "A Streamlit app with six views over any session since 2023: race, pace and tyres, telemetry, "
                      "video lab, championship. Everything on this page comes from it."),
        ("MCP server", f"{len(tools)} tools that let an AI assistant such as Claude answer F1 questions with real numbers "
                       "instead of guessing."),
        ("Data analysis", "Clean-lap pace, a fuel-corrected tyre model, measured pit loss, strategy ranking and "
                          "GPS-aligned lap comparison."),
        ("Video to telemetry", "Turns an onboard video's HUD into a telemetry CSV, with a renderer that makes test "
                               "footage to measure accuracy against."),
    ]
    card_html = "".join(f'<div class="card"><h3>{esc(a)}</h3><p>{esc(b)}</p></div>' for a, b in cards)
    return f"""
<section id="project">
  <h2>The project</h2>
  <p class="sub">This page is a snapshot. The full project runs on your own machine, for any session, with no API keys.</p>
  <div class="cards">{card_html}</div>
  <h3 class="h3">Run it</h3>
  <pre><code>git clone {esc(repo_url)}.git
cd {esc(repo_url.rstrip('/').split('/')[-1])}
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS / Linux: .venv/bin/python
.venv/Scripts/python -m streamlit run dashboard/app.py</code></pre>
  <h3 class="h3">MCP tools</h3>
  {table(rows)}
</section>"""


# ----------------------------------------------------------------------------
# page
# ----------------------------------------------------------------------------

CSS = """
:root{--bg:#141413;--surface:#1a1a19;--panel:#232321;--line:#30302d;--text:#f0efec;--text2:#c3c2b7;--muted:#8a897f;--accent:#3987e5}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 Inter,"Segoe UI",system-ui,-apple-system,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
nav{position:sticky;top:0;z-index:10;background:rgba(20,20,19,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
nav .in{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;gap:18px;align-items:center;overflow-x:auto;white-space:nowrap}
nav .brand{font-weight:700;color:var(--text);margin-right:8px}
nav a{color:var(--text2);font-size:.9rem}
main{max-width:1180px;margin:0 auto;padding:0 16px 64px}
header.hero{padding:64px 0 28px}
.kicker{color:var(--muted);font-size:.8rem;letter-spacing:.08em;text-transform:uppercase}
h1{font-size:clamp(2.2rem,6vw,3.6rem);line-height:1.05;margin:.3em 0 .35em;letter-spacing:-.02em}
.lede{color:var(--text2);font-size:1.15rem;max-width:62ch;margin:0 0 22px}
.btns{display:flex;gap:10px;flex-wrap:wrap}
.btn{display:inline-block;padding:10px 18px;border-radius:8px;border:1px solid var(--line);color:var(--text);font-weight:600;font-size:.95rem}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn:hover{text-decoration:none;filter:brightness(1.12)}
section{padding:44px 0 8px;border-top:1px solid var(--line);margin-top:36px;scroll-margin-top:44px}
h2{font-size:1.6rem;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 20px;max-width:80ch}
.h3{font-size:1.05rem;margin:28px 0 10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:0 0 18px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:0}
.tile .k{color:var(--text2);font-size:.8rem}
.tile .v{font-size:1.4rem;font-weight:600;line-height:1.3;overflow-wrap:anywhere}
.tile .n{color:var(--muted);font-size:.8rem}
.chart{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px;margin:0 0 16px;min-width:0;overflow:hidden}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:start}
.table{overflow:auto;max-height:460px;border:1px solid var(--line);border-radius:10px;margin:0 0 16px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--panel);color:var(--text2);font-weight:600;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
.note{color:var(--muted);font-size:.86rem;max-width:95ch;margin:0 0 8px}
figure{margin:0 0 16px}
figure img{width:100%;display:block;border-radius:10px;border:1px solid var(--line);background:#000}
figcaption{color:var(--muted);font-size:.84rem;margin-top:6px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h3{margin:0 0 6px;font-size:1rem}.card p{margin:0;color:var(--text2);font-size:.9rem}
pre{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow:auto;font-size:.85rem}
code{font-family:ui-monospace,Consolas,monospace}
footer{color:var(--muted);font-size:.82rem;border-top:1px solid var(--line);margin-top:48px;padding-top:20px}
@media (max-width:820px){.two{grid-template-columns:minmax(0,1fr)}header.hero{padding-top:40px}}
"""


def build(out: Path, year: int | None, event: str | None, repo_url: str) -> Path:
    if year and event:
        race = data.load_session(year, event, "R")
    else:
        y, r, _ = data.latest_completed_event()
        race = data.load_session(y, r, "R")
    quali = data.load_session(race.year, race.round, "Q")
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "plotly.min.js").write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    print(f"building site for {race.title}")
    tel_html, pole, pole_lap = section_telemetry(quali)
    body = "".join([
        section_race(race),
        section_pace(race),
        section_strategy(find_strategy_race(race.year, race.round), race),
        tel_html,
        section_video(quali, pole, pole_lap, assets),
        section_championship(race.year),
        section_project(repo_url),
    ])
    stamp = datetime.now(timezone.utc).strftime("%d %B %Y")
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>F1 AI · race analysis, MCP server and video-to-telemetry</title>
<meta name="description" content="Formula 1 data analysis, a dashboard, an MCP server for AI assistants and a video-to-telemetry pipeline. Snapshot of the {esc(race.event_name)} {race.year}.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🏁</text></svg>">
<style>{CSS}</style>
<script src="assets/plotly.min.js"></script>
</head>
<body>
<nav><div class="in"><a class="brand" href="#top">🏁 F1 AI</a><a href="#race">Race</a><a href="#pace">Pace &amp; tyres</a>
<a href="#strategy">Strategy</a><a href="#telemetry">Telemetry</a><a href="#video">Video</a><a href="#championship">Championship</a>
<a href="#project">Project</a><a href="{esc(repo_url)}">GitHub</a></div></nav>
<main id="top">
<header class="hero">
  <div class="kicker">Snapshot · {esc(race.event_name)} {race.year} · generated {stamp}</div>
  <h1>F1 AI</h1>
  <p class="lede">Formula 1 race analysis, an MCP server that gives AI assistants real timing data, and a pipeline that
  reads telemetry off onboard video. Open source, no API keys.</p>
  <div class="btns"><a class="btn primary" href="{esc(repo_url)}">View on GitHub</a><a class="btn" href="#race">Latest race</a></div>
</header>
{body}
<footer>
  <p>Timing data from <a href="https://openf1.org">OpenF1</a>, corner positions from MultiViewer, standings from Jolpica.
  Charts are interactive: hover for values, drag to zoom, double-click to reset.</p>
  <p>Unofficial fan project. Not associated in any way with the Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE
  WORLD CHAMPIONSHIP, GRAND PRIX and related marks are trade marks of Formula One Licensing B.V.</p>
</footer>
</main>
</body>
</html>"""
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")
    print(f"wrote {index} ({index.stat().st_size // 1024} KB)")
    return index


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Build the static website into docs/")
    p.add_argument("--year", type=int)
    p.add_argument("--event")
    p.add_argument("--out", default=str(ROOT / "docs"))
    p.add_argument("--repo-url", default="https://github.com/muzzkh/f1-ai")
    args = p.parse_args()
    build(Path(args.out), args.year, args.event, args.repo_url)


if __name__ == "__main__":
    main()
