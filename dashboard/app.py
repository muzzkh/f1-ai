"""F1 AI dashboard. Run with:  streamlit run dashboard/app.py"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import charts  # noqa: E402
from f1ai import analysis as an  # noqa: E402
from f1ai import data, video  # noqa: E402
from f1ai.config import ROOT, TELEMETRY_DIR, VIDEO_DIR  # noqa: E402
from f1ai.video import layout as hud_layout  # noqa: E402
from f1ai.video import render as hud_render  # noqa: E402

st.set_page_config(page_title="F1 AI", page_icon="🏁", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px;}
      [data-testid="stMetric"] {background: #232321; border: 1px solid #30302d; border-radius: 10px; padding: 12px 16px;}
      [data-testid="stMetricLabel"] p {color: #c3c2b7; font-size: 0.8rem;}
      [data-testid="stMetricValue"] {font-size: 1.5rem;}
      h1 {font-size: 1.7rem !important; margin-bottom: 0;}
      .sub {color: #8a897f; margin: -6px 0 14px 0;}
    </style>
    """,
    unsafe_allow_html=True,
)


def plot(fig) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config=charts.CONFIG)


# ----------------------------------------------------------------------------
# cached data access
# ----------------------------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def completed(year: int) -> pd.DataFrame:
    return data.completed_events(year)[["RoundNumber", "EventName", "Sessions"]].reset_index(drop=True)


@st.cache_resource(show_spinner="Loading timing data...")
def session(year: int, rnd: int, code: str):
    return data.load_session(year, rnd, code)


@st.cache_resource(show_spinner="Loading car telemetry...")
def comparison(year: int, rnd: int, code: str, a: str, b: str, lap_a, lap_b):
    return an.compare_laps(session(year, rnd, code), a, b, lap_a, lap_b)


@st.cache_resource(show_spinner="Fitting pace model...")
def pace_model(year: int, rnd: int):
    return an.fit_pace_model(session(year, rnd, "R"))


@st.cache_data(ttl=1800, show_spinner="Loading standings...")
def standings(year: int) -> dict:
    return data.standings(year)


# ----------------------------------------------------------------------------
# sidebar
# ----------------------------------------------------------------------------

VIEWS = ["Race", "Pace & tyres", "Telemetry", "Video to telemetry", "Championship", "AI assistant (MCP)"]

with st.sidebar:
    st.markdown("## 🏁 F1 AI")
    view = st.radio("View", VIEWS, label_visibility="collapsed")
    st.divider()
    this_year = datetime.now(timezone.utc).year
    years = list(range(this_year, data.FIRST_SEASON - 1, -1))
    year = st.selectbox("Season", years)
    try:
        events = completed(year)
    except data.DataError as exc:
        st.error(str(exc))
        st.stop()
    if events.empty:
        st.info(f"No completed race weekends in {year} yet. Pick an earlier season.")
        st.stop()
    labels = {int(r.RoundNumber): f"R{int(r.RoundNumber)} · {r.EventName}" for r in events.itertuples()}
    rnd = st.selectbox("Event", list(labels)[::-1], format_func=labels.get)
    codes = events.loc[events["RoundNumber"] == rnd, "Sessions"].iloc[0]
    code = st.selectbox("Session", codes[::-1], format_func=data.SESSION_LABELS.get)
    st.caption("Timing data: OpenF1 · corners: MultiViewer · standings: Jolpica")

try:
    ses = session(year, rnd, code)
except data.DataError as exc:
    st.error(str(exc))
    st.stop()

drivers = data.driver_list(ses)
st.title(f"{ses.event_name} {ses.year}")
st.markdown(f'<p class="sub">{ses.name} · {ses.circuit}, {ses.country} · '
            f'{ses.date_start.strftime("%d %b %Y")}</p>', unsafe_allow_html=True)


def fmt(x) -> str:
    return an.format_laptime(x)


def lap_options(drv: str) -> list:
    laps = ses.laps[(ses.laps["Driver"] == drv) & ses.laps["LapTime"].notna() & ses.laps["LapStart"].notna()]
    return [None] + laps["LapNumber"].astype(int).tolist()


def lap_label(drv: str):
    times = ses.laps[ses.laps["Driver"] == drv].set_index("LapNumber")["LapTime"]
    return lambda n: "Fastest lap" if n is None else f"Lap {n} · {fmt(times.get(n))}"


# ----------------------------------------------------------------------------
# views
# ----------------------------------------------------------------------------

def view_race() -> None:
    res = an.results_frame(ses)
    w = an.weather_summary(ses)
    c = st.columns(4)
    if len(res):
        top = res.iloc[0]
        c[0].metric("Winner" if ses.is_race else "Fastest", top["Driver"], top["Team"], delta_color="off", delta_arrow="off")
        best = res.dropna(subset=["BestLap_s"]).sort_values("BestLap_s")
        if len(best):
            c[1].metric("Fastest lap", fmt(best.iloc[0]["BestLap_s"]), best.iloc[0]["Driver"], delta_color="off", delta_arrow="off")
    c[2].metric("Laps" if ses.is_race else "Drivers", ses.total_laps if ses.is_race else len(drivers))
    if w:
        c[3].metric("Track temperature", f"{w['track_temp_c']:.0f} °C",
                    ("Rain during session" if w["rain"] else "Dry") + f" · air {w['air_temp_c']:.0f} °C", delta_color="off", delta_arrow="off")

    def whole(col):
        return [str(int(v)) if pd.notna(v) else "-" for v in col]

    table = pd.DataFrame({"Pos": whole(res["Pos"]), "Driver": res["Driver"], "Name": res["Name"], "Team": res["Team"]})
    if ses.is_race:
        table["Grid"] = whole(res["Grid"])
        gained = pd.to_numeric(res["Grid"], errors="coerce") - pd.to_numeric(res["Pos"], errors="coerce")
        table["+/-"] = [("" if pd.isna(g) or g == 0 else f"{int(g):+d}") for g in gained]
        table["Gap"] = [("Winner" if i == 0 else f"+{g:.3f}" if pd.notna(g) else s)
                        for i, (g, s) in enumerate(zip(res["Gap_s"], res["Status"]))]
        table["Points"] = res["Points"]
    else:
        for q in ("Q1_s", "Q2_s", "Q3_s"):
            if q in res:
                table[q[:2]] = res[q].map(fmt)
    table["Best lap"] = res["BestLap_s"].map(fmt)
    st.dataframe(table, hide_index=True, width="stretch", height=min(38 * (len(table) + 1), 520))

    if ses.is_race:
        plot(charts.position_chart(ses))
    pick = st.multiselect("Drivers", drivers, default=drivers[:3], max_selections=6, key="lap_drivers")
    clean = st.toggle("Clean laps only (no pit, safety-car or slow laps)", value=True)
    if pick:
        plot(charts.lap_times(ses, pick, clean))


def view_pace() -> None:
    pace = an.race_pace(ses)
    left, right = st.columns([1, 1.25])
    with left:
        plot(charts.pace_bars(pace, ses))
    with right:
        plot(charts.tyre_strategy(an.stints(ses), ses.total_laps if ses.is_race else int(ses.laps["LapNumber"].max())))

    if code != "R":
        st.info("The tyre degradation model and strategy simulation use the Grand Prix. Pick the Race session to see them.")
    else:
        st.subheader("Pace model")
        try:
            model = pace_model(year, rnd)
        except ValueError as exc:
            st.info(str(exc))
            model = None
        if model:
            loss = an.pit_loss(ses)
            c = st.columns(4)
            c[0].metric("Fuel effect", f"{model.fuel_effect * 1000:+.0f} ms/lap",
                        "fitted" if model.fuel_fitted else "typical value assumed", delta_color="off", delta_arrow="off")
            c[1].metric("Pit stop time loss", f"{loss['seconds']:.1f} s",
                        f"{loss['stops_measured']} stops measured" if loss["measured"] else "typical value assumed",
                        delta_color="off", delta_arrow="off")
            c[2].metric("Model fit (R²)", f"{model.r2:.2f}", f"{model.n_laps} clean laps", delta_color="off", delta_arrow="off")
            c[3].metric("Typical error", f"±{model.residual_std:.2f} s", "per lap", delta_color="off", delta_arrow="off")
            left, right = st.columns([1, 1.25])
            with left:
                if len(model.degradation) > 1:
                    plot(charts.degradation_bars(model))
                else:  # one compound: the number is the chart
                    comp, deg = next(iter(model.degradation.items()))
                    st.metric(f"{comp.title()} tyre degradation", f"{deg * 1000:+.0f} ms per lap of age",
                              f"fuel-corrected, {model.laps_per_compound[comp]} laps", delta_color="off", delta_arrow="off")
                offs = ", ".join(f"{k.title()} {v:+.2f} s" for k, v in model.compound_offset.items() if k != model.reference_compound)
                if offs:
                    st.caption(f"New-tyre pace vs {model.reference_compound.title()}: {offs}.")
            with right:
                try:
                    sim = an.simulate_strategies(ses, model)
                    plot(charts.strategy_options(sim))
                    short = {"SOFT": "S", "MEDIUM": "M", "HARD": "H", "INTERMEDIATE": "I", "WET": "W"}
                    actual = " - ".join(f"{short.get(c, '?')} {n}" for c, n in zip(sim["winner_actual"]["compounds"], sim["winner_actual"]["stint_laps"]))
                    st.caption(f"What {sim['winner']} actually ran: {actual} laps. The simulation assumes clear air, "
                               "no safety cars and linear tyre wear, with stints capped at the longest run on each compound.")
                except ValueError as exc:
                    st.info(str(exc))

    st.subheader("Best sectors")
    sb = an.sector_bests(ses)
    st.dataframe(
        pd.DataFrame({"Driver": sb["Driver"], "S1": sb["S1"].map(fmt), "S2": sb["S2"].map(fmt), "S3": sb["S3"].map(fmt),
                      "Best lap": sb["BestLap"].map(fmt), "Ideal lap": sb["Theoretical"].map(fmt),
                      "Left on table": sb["LeftOnTable"].map(lambda x: f"{x:.3f}" if pd.notna(x) else "-"),
                      "Speed trap (km/h)": sb["TopSpeedTrap"]}),
        hide_index=True, width="stretch", height=min(38 * (len(sb) + 1), 420))


def view_telemetry() -> None:
    c = st.columns(4)
    a = c[0].selectbox("Driver A", drivers, index=0)
    lap_a = c[1].selectbox("Lap A", lap_options(a), format_func=lap_label(a))
    b = c[2].selectbox("Driver B", drivers, index=min(1, len(drivers) - 1))
    lap_b = c[3].selectbox("Lap B", lap_options(b), format_func=lap_label(b))
    try:
        cmp = comparison(year, rnd, code, a, b, lap_a, lap_b)
    except (data.DataError, ValueError) as exc:
        st.info(str(exc))
        return
    sa, sb = cmp["summary_a"], cmp["summary_b"]
    m = st.columns(4)
    m[0].metric(f"{sa['driver']} · lap {sa['lap_number']}", fmt(sa["lap_time_s"]),
                f"{sa['compound'].title()}, top {sa['top_speed_kmh']:.0f} km/h", delta_color="off", delta_arrow="off")
    m[1].metric(f"{sb['driver']} · lap {sb['lap_number']}", fmt(sb["lap_time_s"]),
                f"{sb['compound'].title()}, top {sb['top_speed_kmh']:.0f} km/h", delta_color="off", delta_arrow="off")
    gap = cmp["lap_delta_s"]
    m[2].metric("Gap", f"{abs(gap):.3f} s", f"{sa['driver'] if gap > 0 else sb['driver']} faster", delta_color="off", delta_arrow="off")
    m[3].metric("Full throttle", f"{sa['full_throttle_pct']:.0f}% vs {sb['full_throttle_pct']:.0f}%",
                f"braking {sa['braking_pct']:.0f}% vs {sb['braking_pct']:.0f}%", delta_color="off", delta_arrow="off")
    plot(charts.telemetry_compare(cmp))
    left, right = st.columns([1.1, 1])
    with left:
        plot(charts.track_map(cmp))
    with right:
        st.markdown("**Corner by corner**")
        if len(cmp["corners"]):
            st.dataframe(cmp["corners"].rename(columns=lambda s: s.replace("MinSpeed_", "Min speed ").replace("Gain_", "Time gained by ")),
                         hide_index=True, width="stretch", height=400)
        else:
            st.caption("No corner map available for this circuit.")
    st.caption("Laps are aligned by GPS position. Sector-level gaps match official timing to a few hundredths of a "
               "second; corner-level numbers are indicative (the public feed samples at about 4 Hz).")


def _reader_for(layout: dict, w: int, h: int):
    with st.spinner("Preparing the digit reader (first run trains it, about 30 s)..."):
        return video.HudReader(layout, w, h)


def view_video() -> None:
    st.markdown("Reads speed, gear, throttle, brake and RPM straight off an onboard video's HUD graphics. "
                "Render a test clip from real telemetry to see it work against a known answer, or bring your own footage.")
    ss = st.session_state
    source = st.radio("Video source", ["Render a test onboard from this session", "Use a video file"], horizontal=True)
    profiles = hud_layout.list_profiles()

    if source.startswith("Render"):
        c = st.columns([1, 1, 1, 1])
        drv = c[0].selectbox("Driver", drivers, key="v_drv")
        lap = c[1].selectbox("Lap", lap_options(drv), format_func=lap_label(drv), key="v_lap")
        prof = c[2].selectbox("HUD style", sorted((p for p in profiles if p.startswith("demo-")), reverse=True), key="v_prof")
        secs = c[3].slider("Clip length (s)", 10, 120, 30, step=5)
        if st.button("Render video", type="primary"):
            try:
                tel = an.lap_telemetry(ses, drv, lap)
            except data.DataError as exc:
                st.error(str(exc))
                return
            name = f"{ses.year}-r{ses.round:02d}-{ses.code}-{tel.attrs['driver']}-lap{tel.attrs['lap_number']}-{prof}.mp4"
            bar = st.progress(0.0, "Rendering...")
            info = hud_render.render_onboard(
                tel, VIDEO_DIR / name, prof, max_seconds=secs, progress=lambda p: bar.progress(min(p, 1.0), "Rendering..."),
                caption=f"{tel.attrs['driver']}  {ses.event_name} {ses.year}  {ses.name}  lap {tel.attrs['lap_number']}")
            bar.empty()
            ss["video"] = {"path": info["path"], "profile": prof, "reference": tel,
                           "label": f"{tel.attrs['driver']} lap {tel.attrs['lap_number']}"}
            ss.pop("extracted", None)
    else:
        up = st.file_uploader("Upload an onboard video", type=["mp4", "mov", "mkv", "avi", "webm"])
        existing = sorted(p.name for p in VIDEO_DIR.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi", ".webm"))
        c = st.columns([2, 1])
        chosen = c[0].selectbox("...or pick a file from data/videos", [None] + existing, format_func=lambda x: x or "-")
        prof = c[1].selectbox("HUD profile", profiles, key="v_prof_file")
        path = None
        if up is not None:
            path = VIDEO_DIR / Path(up.name).name
            if not path.exists() or path.stat().st_size != up.size:
                path.write_bytes(up.getbuffer())
        elif chosen:
            path = VIDEO_DIR / chosen
        if path and (ss.get("video", {}).get("path") != str(path) or ss["video"].get("profile") != prof):
            ss["video"] = {"path": str(path), "profile": prof, "reference": None, "label": path.name}
            ss.pop("extracted", None)
        st.caption("Your own footage needs a HUD profile that matches its graphics. Start from a demo profile and "
                   "adjust it under 'Calibrate HUD profile' below until the boxes sit on the graphics.")

    vid = ss.get("video")
    if not vid or not Path(vid["path"]).exists():
        return
    try:
        info = video.video_info(vid["path"])
    except FileNotFoundError as exc:
        st.error(str(exc))
        return
    st.divider()
    st.markdown(f"**{vid['label']}** · {info['width']}x{info['height']} · {info['fps']:.0f} fps · {info['duration_s']:.1f} s")

    layout = ss.get("custom_layout") if ss.get("custom_layout_for") == vid["path"] else None
    layout = layout or hud_layout.load_profile(vid["profile"])

    left, right = st.columns([1.5, 1])
    with left:
        t = st.slider("Preview time (s)", 0.0, max(info["duration_s"] - 0.1, 0.1), min(5.0, info["duration_s"] / 2), step=0.1)
        boxes = st.toggle("Show where the profile looks", value=True)
        try:
            frame = video.grab_frame(vid["path"], t)
        except ValueError as exc:
            st.error(str(exc))
            return
        shown = video.draw_overlay(frame, layout) if boxes else frame
        st.image(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB), width="stretch")
    with right:
        st.markdown("**Read from this frame**")
        r = _reader_for(layout, info["width"], info["height"]).read(frame)
        m = st.columns(2)
        m[0].metric("Speed", "-" if np.isnan(r["Speed"]) else f"{r['Speed']:.0f} km/h",
                    f"confidence {r['SpeedConf'] * 100:.0f}%", delta_color="off", delta_arrow="off")
        if "nGear" in r:
            m[1].metric("Gear", "-" if np.isnan(r["nGear"]) else f"{r['nGear']:.0f}",
                        f"confidence {r['GearConf'] * 100:.0f}%", delta_color="off", delta_arrow="off")
        m = st.columns(2)
        if "Throttle" in r:
            m[0].metric("Throttle", f"{r['Throttle']:.0f}%")
        if "Brake" in r:
            m[1].metric("Brake", "On" if r["Brake"] > 50 else "Off")
        m = st.columns(2)
        if "RPM" in r:
            m[0].metric("RPM", f"{r['RPM']:.0f}")
        if "DRS" in r:
            m[1].metric("DRS", "Open" if r["DRS"] else "Closed")

    with st.expander("Calibrate HUD profile"):
        st.caption("Coordinates are fractions of the frame: roi = [left, top, right, bottom]. Arcs use a centre, inner "
                   "and outer radius (fractions of height) and start/end angles in degrees clockwise from 3 o'clock. "
                   "hsv_lo / hsv_hi are the gauge colour range (OpenCV HSV).")
        text = st.text_area("Profile JSON", json.dumps(layout, indent=2), height=380, key=f"layout_json_{vid['path']}_{vid['profile']}")
        b = st.columns([1, 1, 3])
        if b[0].button("Apply"):
            try:
                ss["custom_layout"] = hud_layout.validate(json.loads(text))
                ss["custom_layout_for"] = vid["path"]
                ss.pop("extracted", None)
                st.rerun()
            except (json.JSONDecodeError, hud_layout.LayoutError) as exc:
                st.error(f"Profile not valid: {exc}")
        if b[1].button("Save as profile"):
            try:
                saved = hud_layout.save_profile(json.loads(text))
                st.success(f"Saved as '{saved.stem}'. It now appears in the profile list.")
            except (json.JSONDecodeError, hud_layout.LayoutError) as exc:
                st.error(f"Profile not valid: {exc}")

    if st.button("Extract telemetry from video", type="primary"):
        bar = st.progress(0.0, "Reading frames...")
        tel = video.extract_telemetry(vid["path"], layout, progress=lambda p: bar.progress(min(p, 1.0), "Reading frames..."))
        bar.empty()
        csv = TELEMETRY_DIR / (Path(vid["path"]).stem + ".csv")
        tel.to_csv(csv, index=False, float_format="%.3f")
        ss["extracted"] = {"tel": tel, "csv": str(csv), "for": vid["path"]}

    ext = ss.get("extracted")
    if not ext or ext["for"] != vid["path"]:
        return
    tel, ref = ext["tel"], vid.get("reference")
    st.subheader("Extracted telemetry")
    rate = tel.attrs["speed_read_rate"] * 100
    acc = video.accuracy(tel, ref) if ref is not None else None
    m = st.columns(5)
    m[0].metric("Frames with speed read", f"{rate:.1f}%", f"{tel.attrs['frames_read']} frames", delta_color="off", delta_arrow="off")
    if acc:
        m[1].metric("Speed error", f"{acc['speed_mae_kmh']:.2f} km/h", f"95% within {acc['speed_p95_kmh']:.1f}", delta_color="off", delta_arrow="off")
        m[2].metric("Gear correct", f"{acc.get('gear_accuracy_pct', float('nan')):.1f}%")
        m[3].metric("Throttle error", f"{acc.get('throttle_mae_pct', float('nan')):.1f} pts")
        m[4].metric("Brake agreement", f"{acc.get('brake_agreement_pct', float('nan')):.1f}%")
    else:
        m[1].metric("Top speed", f"{tel['Speed'].max():.0f} km/h")
        m[2].metric("Minimum speed", f"{tel['Speed'].min():.0f} km/h")
        m[3].metric("Distance covered", f"{tel['Distance'].iloc[-1]:.0f} m")
        m[4].metric("Peak braking", f"{-tel['LongG'].min():.1f} g")
    if rate < 80:
        st.warning("Speed could not be read on many frames. The HUD profile probably does not line up with this "
                   "footage: open 'Calibrate HUD profile' and adjust it.")
    plot(charts.video_vs_reference(tel, ref, acc["offset_s"] if acc else 0.0))
    if acc:
        st.caption("Errors are measured against the official timing data the test clip was rendered from.")
    st.download_button("Download CSV", Path(ext["csv"]).read_bytes(), file_name=Path(ext["csv"]).name, mime="text/csv")


def view_championship() -> None:
    try:
        s = standings(year)
    except data.DataError as exc:
        st.info(str(exc))
        return
    if not s["drivers"]:
        st.info("Standings are not available for this season yet.")
        return
    st.markdown(f"**{year} championship after round {s['round']}**")
    c = st.columns(3)
    lead, second = s["drivers"][0], s["drivers"][1] if len(s["drivers"]) > 1 else None
    c[0].metric("Drivers' leader", lead["driver"], f"{lead['points']:g} pts · {lead['wins']} wins", delta_color="off", delta_arrow="off")
    if second:
        c[1].metric("Lead over second", f"{lead['points'] - second['points']:g} pts", second["driver"], delta_color="off", delta_arrow="off")
    if s["constructors"]:
        t = s["constructors"][0]
        c[2].metric("Constructors' leader", t["team"], f"{t['points']:g} pts", delta_color="off", delta_arrow="off")
    left, right = st.columns([1.2, 1])
    with left:
        plot(charts.standings_bars(s["drivers"], "driver", "Drivers (points)"))
    with right:
        plot(charts.standings_bars(s["constructors"], "team", "Constructors (points)"))


def view_mcp() -> None:
    st.markdown(
        "The same data and tools behind this dashboard are exposed as an **MCP server**, so an AI assistant "
        "can answer F1 questions with real numbers instead of guessing.")
    st.markdown("**Claude Code** picks the server up automatically from `.mcp.json` when started in this folder. "
                "For Claude Desktop or another client, add:")
    py = Path(sys.executable)
    st.code(json.dumps({"mcpServers": {"f1ai": {"command": str(py), "args": ["-m", "f1ai.mcp_server"],
                                                 "cwd": str(ROOT)}}}, indent=2), language="json")
    st.markdown("**Things to ask**")
    st.markdown(
        "- *Who had the best race pace at the last Grand Prix, and how did the tyres hold up?*\n"
        "- *Compare the two front-row qualifying laps: where was the time gained?*\n"
        "- *Was a two-stop faster than a one-stop at Abu Dhabi 2025?*\n"
        "- *Render an onboard of the pole lap, read the telemetry back from the video and tell me how accurate it was.*")
    try:
        from f1ai import mcp_server

        tools = asyncio.run(mcp_server.mcp.list_tools())
        st.markdown(f"**{len(tools)} tools**")
        st.dataframe(pd.DataFrame([{"Tool": t.name, "What it does": " ".join((t.description or "").split())} for t in tools]),
                     hide_index=True, width="stretch", height=38 * (len(tools) + 1))
    except Exception as exc:  # the tool list is informational only
        st.caption(f"Could not list tools: {exc}")


{"Race": view_race, "Pace & tyres": view_pace, "Telemetry": view_telemetry, "Video to telemetry": view_video,
 "Championship": view_championship, "AI assistant (MCP)": view_mcp}[view]()
