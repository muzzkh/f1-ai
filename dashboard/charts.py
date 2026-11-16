"""Plotly figure builders for the dashboard (dark surface)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from f1ai import analysis as an

SURFACE = "#1a1a19"
PANEL = "#232321"
GRID = "#30302d"
TEXT = "#f0efec"
TEXT_2 = "#c3c2b7"
MUTED = "#8a897f"
SERIES_A = "#3987e5"   # categorical slot 1 (dark step)
SERIES_B = "#d95926"   # categorical slot 2 (dark step)
COMPOUND = {"SOFT": "#e8002d", "MEDIUM": "#f5c400", "HARD": "#e6e6e3",
            "INTERMEDIATE": "#2fb344", "WET": "#3987e5", "UNKNOWN": "#77766e"}
COMPOUND_ORDER = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]
CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


def _base(fig: go.Figure, height: int, title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(color=TEXT_2, size=12, family="Inter, Segoe UI, system-ui, sans-serif"),
        title=dict(text=title, font=dict(color=TEXT, size=15), x=0, xanchor="left") if title else None,
        margin=dict(l=8, r=16, t=44 if title else 16, b=8),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(color=TEXT, size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, font=dict(color=TEXT_2),
                    bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED),
                     title_font=dict(color=TEXT_2), automargin=True)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED),
                     title_font=dict(color=TEXT_2), automargin=True)
    return fig


def empty(message: str, height: int = 220) -> go.Figure:
    fig = _base(go.Figure(), height)
    fig.add_annotation(text=message, showarrow=False, font=dict(color=MUTED, size=13))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def driver_styles(ses) -> dict[str, dict]:
    """Team colour per driver; the second driver of a team gets a dashed line
    so teammates are never told apart by colour alone."""
    seen: dict[str, int] = {}
    out = {}
    for _, d in ses.drivers.sort_values("DriverNumber").iterrows():
        n = seen.get(d["Team"], 0)
        seen[d["Team"]] = n + 1
        out[d["Driver"]] = {"color": d["TeamColor"], "dash": "solid" if n == 0 else "dot", "team": d["Team"]}
    return out


def position_chart(ses) -> go.Figure:
    pos = an.position_chart(ses)
    if pos.empty:
        return empty("No position data for this session")
    styles = driver_styles(ses)
    fig = go.Figure()
    for drv in pos.columns:
        s = pos[drv].dropna()
        if s.empty:
            continue
        st = styles.get(drv, {"color": MUTED, "dash": "solid", "team": ""})
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=drv, line=dict(color=st["color"], width=2, dash=st["dash"]),
            hovertemplate=f"<b>{drv}</b> · {st['team']}<br>Lap %{{x}} · P%{{y}}<extra></extra>", showlegend=False))
        fig.add_annotation(x=s.index[-1], y=s.values[-1], text=drv, showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=TEXT_2, size=11))
    _base(fig, 520, "Position by lap")
    fig.update_yaxes(range=[len(pos.columns) + 0.6, 0.4], tick0=1, dtick=1, title="Position", gridcolor=SURFACE)
    fig.update_xaxes(title="Lap", range=[1, pos.index.max() * 1.045])
    fig.update_layout(hovermode="closest", margin=dict(r=40))
    return fig


def pace_bars(pace: pd.DataFrame, ses) -> go.Figure:
    if pace.empty:
        return empty("Not enough clean laps to rank pace")
    styles = driver_styles(ses)
    p = pace.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=p["GapToBest"], y=p["Driver"], orientation="h",
        marker=dict(color=[styles.get(d, {}).get("color", MUTED) for d in p["Driver"]], cornerradius=4,
                    line=dict(color=SURFACE, width=2)),
        text=[f"+{g:.3f}" if g > 0 else an.format_laptime(m) for g, m in zip(p["GapToBest"], p["Median"])],
        textposition="outside", textfont=dict(color=TEXT_2, size=11), cliponaxis=False,
        customdata=np.stack([p["Team"], [an.format_laptime(x) for x in p["Median"]], p["Laps"]], axis=-1),
        hovertemplate="<b>%{y}</b> · %{customdata[0]}<br>Median %{customdata[1]} over %{customdata[2]} clean laps"
                      "<br>+%{x:.3f} s to quickest<extra></extra>"))
    _base(fig, max(320, 24 * len(p) + 80), "Median clean-lap pace, gap to quickest (s)")
    fig.update_xaxes(title=None, rangemode="tozero")
    fig.update_yaxes(gridcolor=SURFACE, tickfont=dict(color=TEXT_2))
    fig.update_layout(margin=dict(r=70))
    return fig


def lap_times(ses, drivers: list[str], clean_only: bool = True) -> go.Figure:
    laps = an.laps_frame(ses, drivers)
    if clean_only:
        laps = an.clean_laps(laps)
    laps = laps.dropna(subset=["LapTime"])
    if laps.empty:
        return empty("No laps to show for this selection")
    styles = driver_styles(ses)
    fig = go.Figure()
    for drv in drivers:
        g = laps[laps["Driver"] == drv].sort_values("LapNumber")
        if g.empty:
            continue
        st = styles[drv]
        fig.add_trace(go.Scatter(
            x=g["LapNumber"], y=g["LapTime"], mode="lines+markers", name=drv,
            line=dict(color=st["color"], width=2, dash=st["dash"]),
            marker=dict(size=8, color=st["color"], line=dict(color=SURFACE, width=2)),
            customdata=np.stack([[an.format_laptime(x) for x in g["LapTime"]], g["Compound"].str.title(),
                                 g["TyreLife"].fillna(0).astype(int)], axis=-1),
            hovertemplate=f"<b>{drv}</b> lap %{{x}}<br>%{{customdata[0]}} · %{{customdata[1]}}, "
                          f"%{{customdata[2]}} laps old<extra></extra>"))
    _base(fig, 400, "Lap times" + (" (clean laps only)" if clean_only else ""))
    fig.update_xaxes(title="Lap")
    fig.update_yaxes(title="Lap time (s)")
    fig.update_layout(hovermode="closest")
    return fig


def _stint_bars(fig: go.Figure, rows: list[dict]) -> None:
    """rows: label, compound, start (0-based lap), laps, hover"""
    df = pd.DataFrame(rows)
    for comp in COMPOUND_ORDER:
        g = df[df["compound"] == comp]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            y=g["label"], x=g["laps"], base=g["start"], orientation="h", name=comp.title(),
            marker=dict(color=COMPOUND[comp], line=dict(color=SURFACE, width=2), cornerradius=3),
            customdata=g["hover"], hovertemplate="%{customdata}<extra></extra>"))
    fig.update_layout(barmode="overlay", bargap=0.28)


def tyre_strategy(stints: pd.DataFrame, total_laps: int) -> go.Figure:
    if stints.empty:
        return empty("No stint data for this session")
    rows = []
    for s in stints.itertuples():
        pace = f" · median {an.format_laptime(s.MedianPace)}" if np.isfinite(s.MedianPace) else ""
        age = "" if not np.isfinite(s.StartTyreLife) or s.StartTyreLife <= 1 else f" · {int(s.StartTyreLife - 1)} laps old at start"
        rows.append({"label": s.Driver, "compound": s.Compound if s.Compound in COMPOUND else "UNKNOWN",
                     "start": s.StartLap - 1, "laps": s.Laps,
                     "hover": f"<b>{s.Driver}</b> stint {s.Stint}: {s.Compound.title()}<br>"
                              f"Laps {s.StartLap}-{s.EndLap} ({s.Laps} laps){age}{pace}"})
    fig = go.Figure()
    _stint_bars(fig, rows)
    order = list(dict.fromkeys(stints["Driver"]))
    _base(fig, max(340, 24 * len(order) + 90), "Tyre strategy")
    fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], gridcolor=SURFACE, tickfont=dict(color=TEXT_2))
    fig.update_xaxes(title="Lap", range=[0, total_laps])
    return fig


def strategy_options(sim: dict) -> go.Figure:
    rows, labels = [], []
    short = {"SOFT": "S", "MEDIUM": "M", "HARD": "H"}
    for i, s in enumerate(sim["strategies"][:8], start=1):
        label = f"{i}. {'-'.join(short[c] for c in s['compounds'])}  +{s['gap_to_best_s']:.1f}s"
        labels.append(label)
        start = 0
        for c, n in zip(s["compounds"], s["stint_laps"]):
            rows.append({"label": label, "compound": c, "start": start, "laps": n,
                         "hover": f"{c.title()}: laps {start + 1}-{start + n} ({n} laps)"})
            start += n
    fig = go.Figure()
    _stint_bars(fig, rows)
    _base(fig, 60 + 34 * len(labels) + 40, "Predicted fastest strategies")
    fig.update_yaxes(categoryorder="array", categoryarray=labels[::-1], gridcolor=SURFACE, tickfont=dict(color=TEXT_2))
    fig.update_xaxes(title="Lap", range=[0, sim["total_laps"]])
    return fig


def degradation_bars(model: an.PaceModel) -> go.Figure:
    comps = [c for c in COMPOUND_ORDER if c in model.degradation]
    fig = go.Figure(go.Bar(
        x=[c.title() for c in comps], y=[model.degradation[c] for c in comps],
        marker=dict(color=[COMPOUND[c] for c in comps], cornerradius=4, line=dict(color=SURFACE, width=2)),
        text=[f"{model.degradation[c]:+.3f}" for c in comps], textposition="outside",
        textfont=dict(color=TEXT_2), cliponaxis=False,
        customdata=[model.laps_per_compound[c] for c in comps],
        hovertemplate="<b>%{x}</b><br>%{y:+.3f} s per lap of tyre age<br>fitted on %{customdata} laps<extra></extra>"))
    _base(fig, 300, "Tyre degradation (s lost per lap of age, fuel-corrected)")
    fig.update_yaxes(zeroline=True, zerolinecolor=MUTED, title=None)
    fig.update_layout(bargap=0.5)
    return fig


def telemetry_compare(cmp: dict) -> go.Figure:
    f, a, b = cmp["frame"], cmp["driver_a"], cmp["driver_b"]
    la = f"{a} lap {cmp['summary_a']['lap_number']}" if a == b else a
    lb = f"{b} lap {cmp['summary_b']['lap_number']}" if a == b else b
    fig = make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.035,
                        row_heights=[0.38, 0.18, 0.16, 0.10, 0.18])
    x = f["Distance"]

    def pair(row, col, shape="linear", unit=""):
        for name, suffix, colr in ((la, "A", SERIES_A), (lb, "B", SERIES_B)):
            fig.add_trace(go.Scatter(
                x=x, y=f[f"{col}_{suffix}"], mode="lines", name=name, legendgroup=name, showlegend=row == 1,
                line=dict(color=colr, width=2, shape=shape),
                hovertemplate=f"{name} %{{y:.0f}}{unit}<extra></extra>"), row=row, col=1)

    pair(1, "Speed", unit=" km/h")
    fig.add_trace(go.Scatter(
        x=x, y=f["Delta"], mode="lines", name="Gap", showlegend=False, line=dict(color=TEXT, width=2),
        fill="tozeroy", fillcolor="rgba(240,239,236,0.10)",
        hovertemplate="gap %{y:+.3f} s<extra></extra>"), row=2, col=1)
    pair(3, "Throttle", unit="%")
    pair(4, "Brake", shape="hv")
    pair(5, "nGear", shape="hv")
    for c in cmp["corner_positions"].itertuples():
        fig.add_vline(x=c.Distance, line=dict(color=GRID, width=1), layer="below")
        fig.add_annotation(x=c.Distance, y=1.0, yref="paper", yanchor="bottom", text=c.Corner.lstrip("T"),
                           showarrow=False, font=dict(color=MUTED, size=10))
    _base(fig, 760)
    fig.update_layout(hovermode="x unified", hoversubplots="axis", margin=dict(t=56),
                      legend=dict(y=1.035))
    titles = ["Speed (km/h)", f"Gap (s)<br>+ = {la} ahead", "Throttle (%)", "Brake", "Gear"]
    for i, t in enumerate(titles, start=1):
        fig.update_yaxes(title=dict(text=t, font=dict(size=11)), row=i, col=1)
    fig.update_yaxes(zeroline=True, zerolinecolor=MUTED, row=2, col=1)
    fig.update_yaxes(tickvals=[0, 100], ticktext=["off", "on"], range=[-15, 115], row=4, col=1)
    fig.update_yaxes(dtick=2, row=5, col=1)
    fig.update_xaxes(title="Distance (m)", row=5, col=1)
    fig.update_xaxes(showspikes=True, spikecolor=MUTED, spikethickness=1, spikemode="across", spikedash="solid")
    return fig


def track_map(cmp: dict) -> go.Figure:
    f, a, b = cmp["frame"], cmp["driver_a"], cmp["driver_b"]
    if f["X"].isna().any():
        return empty("No position data for this lap")
    same = a == b
    la = f"lap {cmp['summary_a']['lap_number']}" if same else a
    lb = f"lap {cmp['summary_b']['lap_number']}" if same else b
    fig = go.Figure()
    shown = set()
    ms = cmp["mini_sectors"].set_index("MiniSector")
    for n, g in f.groupby("MiniSector"):
        gain = float(ms.at[n, "Gain_A"])
        who, col = (la, SERIES_A) if gain > 0 else (lb, SERIES_B)
        nxt = f[f["MiniSector"] == n + 1].head(1)  # join up with the next slice
        g = pd.concat([g, nxt])
        fig.add_trace(go.Scatter(
            x=g["X"], y=g["Y"], mode="lines", line=dict(color=col, width=6), name=f"{who} faster",
            legendgroup=who, showlegend=who not in shown,
            hovertemplate=f"<b>{who}</b> faster by {abs(gain):.3f} s<br>{ms.at[n, 'Start']:.0f}-{ms.at[n, 'End']:.0f} m<extra></extra>"))
        shown.add(who)
    crn = cmp["corner_positions"]
    if len(crn):
        cx, cy = f["X"].mean(), f["Y"].mean()
        dx, dy = crn["X"] - cx, crn["Y"] - cy
        norm = np.hypot(dx, dy).replace(0, 1)
        span = max(f["X"].max() - f["X"].min(), f["Y"].max() - f["Y"].min())
        fig.add_trace(go.Scatter(
            x=crn["X"] + dx / norm * span * 0.035, y=crn["Y"] + dy / norm * span * 0.035, mode="text",
            text=crn["Corner"].str.lstrip("T"), textfont=dict(color=MUTED, size=10), hoverinfo="skip", showlegend=False))
    _base(fig, 440, "Where each is faster")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(legend=dict(orientation="h", y=-0.02, yanchor="top", x=0.5, xanchor="center"))
    return fig


def video_vs_reference(ext: pd.DataFrame, ref: pd.DataFrame | None, offset: float = 0.0) -> go.Figure:
    rows = [("Speed", "Speed (km/h)", "linear"), ("Throttle", "Throttle (%)", "linear"),
            ("Brake", "Brake", "hv"), ("nGear", "Gear", "hv")]
    rows = [r for r in rows if r[0] in ext]
    fig = make_subplots(rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[0.4] + [0.6 / max(len(rows) - 1, 1)] * (len(rows) - 1))
    for i, (col, title, shape) in enumerate(rows, start=1):
        if ref is not None:
            t = ref["Time"] + offset
            m = (t >= ext["Time"].min()) & (t <= ext["Time"].max())
            fig.add_trace(go.Scatter(
                x=t[m], y=ref[col][m], mode="lines", name="Official timing data", legendgroup="ref", showlegend=i == 1,
                # drawn wide and underneath, so a perfect match still shows both
                line=dict(color=SERIES_A, width=6, shape=shape), opacity=0.55,
                hovertemplate="official %{y:.0f}<extra></extra>"), row=i, col=1)
        fig.add_trace(go.Scatter(
            x=ext["Time"], y=ext[col], mode="lines", name="Read from video", legendgroup="ext", showlegend=i == 1,
            line=dict(color=SERIES_B, width=1.5, shape=shape),
            hovertemplate="video %{y:.0f}<extra></extra>"), row=i, col=1)
        fig.update_yaxes(title=dict(text=title, font=dict(size=11)), row=i, col=1)
    _base(fig, 150 + 130 * len(rows))
    fig.update_layout(hovermode="x unified", hoversubplots="axis", margin=dict(t=40))
    fig.update_xaxes(title="Video time (s)", row=len(rows), col=1)
    return fig


def standings_bars(rows: list[dict], label: str, title: str) -> go.Figure:
    if not rows:
        return empty("Standings unavailable")
    df = pd.DataFrame(rows).iloc[::-1]
    fig = go.Figure(go.Bar(
        x=df["points"], y=df[label], orientation="h",
        marker=dict(color=SERIES_A, cornerradius=4, line=dict(color=SURFACE, width=2)),
        text=df["points"].map(lambda p: f"{p:g}"), textposition="outside", textfont=dict(color=TEXT_2, size=11),
        cliponaxis=False, customdata=df["wins"],
        hovertemplate="<b>%{y}</b><br>%{x:g} points · %{customdata} wins<extra></extra>"))
    _base(fig, max(300, 24 * len(df) + 80), title)
    fig.update_yaxes(gridcolor=SURFACE, tickfont=dict(color=TEXT_2))
    fig.update_xaxes(title=None)
    fig.update_layout(margin=dict(r=50))
    return fig
