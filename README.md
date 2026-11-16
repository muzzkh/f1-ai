# F1 AI

Formula 1 data analysis, a dashboard, an MCP server for AI assistants, and a
video-to-telemetry pipeline, in one Python project.

**Website:** https://muzzkh.github.io/f1-ai/ - an interactive snapshot of the latest race weekend.

| Part | What it does | Where |
|---|---|---|
| Data layer | Timing data, tyres, results, weather and car telemetry for every session since 2023, cached on disk | `src/f1ai/data.py` |
| Analysis | Race pace, tyre stints, fuel-corrected degradation model, pit-loss measurement, strategy simulation, GPS-aligned lap comparison | `src/f1ai/analysis.py` |
| Dashboard | Six views over any session: race, pace & tyres, telemetry, video lab, championship, MCP | `dashboard/` |
| MCP server | 13 tools that let an AI assistant query all of the above | `src/f1ai/mcp_server.py` |
| Video to telemetry | Reads speed, gear, throttle, brake, RPM and DRS off an onboard video's HUD | `src/f1ai/video/` |

## Quick start

The environment is already set up in `.venv`. From this folder:

```bash
.venv/Scripts/python.exe -m streamlit run dashboard/app.py
```

Then open http://localhost:8501. To rebuild the environment from scratch:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

No API keys or accounts are needed.

## Dashboard

Pick a season, event and session in the sidebar.

- **Race** - classification, position-by-lap chart, lap times for chosen drivers.
- **Pace & tyres** - clean-lap pace ranking, tyre strategy for every driver, and
  for Grands Prix a fitted pace model (tyre degradation per compound, fuel
  effect, measured pit loss) with a ranking of predicted one- and two-stop
  strategies.
- **Telemetry** - any two laps overlaid: speed, time gap, throttle, brake, gear,
  a track map coloured by who is faster where, and a corner-by-corner table.
- **Video to telemetry** - render a test onboard from real telemetry, or load
  your own video, preview what the reader sees, calibrate the HUD profile,
  extract, compare against official data, download CSV.
- **Championship** - driver and constructor standings.
- **AI assistant (MCP)** - connection details and the tool list.

## MCP server

`.mcp.json` registers the server for Claude Code, which picks it up when
started in this folder. For other clients use the config shown on the
dashboard's MCP page. To run it by hand (stdio):

```bash
.venv/Scripts/python.exe -m f1ai.mcp_server
```

Tools: `get_schedule`, `get_standings`, `get_session_results`, `get_lap_times`,
`get_race_pace`, `get_tyre_strategy`, `get_tyre_degradation`,
`simulate_race_strategy`, `compare_drivers`, `get_lap_telemetry`,
`list_hud_profiles`, `render_onboard_video`, `video_to_telemetry`.

## Video to telemetry

How it works:

1. A **HUD profile** (JSON) says where each graphic sits in the frame: number
   boxes, straight bars, curved gauges, on/off lights. Coordinates are
   fractions of the frame, so one profile works at any resolution.
2. **Numbers** (speed, gear) are read by a small neural network trained on
   digits rendered from the fonts installed on this machine, with blur, noise
   and slant added. It is trained on first use (about 30 s) and cached.
3. **Gauges** (throttle, brake, RPM) are read by measuring how far the coloured
   part extends; **lights** (DRS) by whether they are lit.
4. A clean-up pass removes misreads using the fact that a car's speed cannot
   jump between frames, then adds distance and longitudinal g.

Measured accuracy on rendered test footage with known ground truth (a real
qualifying lap, 640x360, MPEG-4 compressed): speed error 0.02 km/h, gear and
brake 100% correct, throttle within 2.3 points. The digit reader scores 99.6%
on a font family it was never trained on.

**Real broadcast footage:** the two built-in profiles (`demo-halo`,
`demo-bars`) match the project's own renderer. Real footage has its own HUD
design, so it needs its own profile: load the video in the dashboard, open
*Calibrate HUD profile*, move the boxes onto the graphics, check the live
readout, and save. This has not been tested on real broadcast video. The
reported *frames with speed read* percentage tells you whether a profile fits.

Command line (an invented lap, works offline; use `--year --event --driver` for a real one):

```bash
.venv/Scripts/f1ai.exe render --synthetic --seconds 20
```

```bash
.venv/Scripts/f1ai.exe extract data/videos/synthetic-demo-halo.mp4
```

## Website

GitHub Pages serves the static site in `docs/`. It cannot run the live
dashboard, so the site is a snapshot: one page with interactive charts for the
latest race weekend. To refresh it after a race, rebuild and push:

```bash
.venv/Scripts/python.exe dashboard/build_site.py
```

Add `--year 2025 --event "Abu Dhabi"` to build it for a specific weekend.

## Data sources and limits

- **OpenF1** (timing, tyres, telemetry, positions) - free, no account, 2023
  onwards, limited to about 30 requests a minute. Everything is cached in
  `data/cache`, so each session is only downloaded once.
- **MultiViewer** circuit API for corner positions; **Jolpica** for standings.
- Car telemetry is sampled at about 4 Hz. Lap comparisons agree with official
  sector times to a few hundredths of a second; differences at the level of a
  single corner are indicative.
- The pace model is deliberately simple (linear tyre wear, one fuel
  coefficient). It needs a dry race with at least two compounds in use, and the
  strategy simulation ignores traffic, safety cars and track evolution.
- The official F1 live-timing feed now requires an F1 account sign-in, which is
  why this project does not use the FastF1 library.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -m "not network"
```

```bash
.venv/Scripts/python.exe -m pytest -m network
```

The offline suite checks the analysis against a made-up race with known
parameters and runs the full video round trip. The network suite checks real
sessions.

## Layout

```
src/f1ai/
  data.py         OpenF1 client, cache, Session object, lap telemetry
  analysis.py     pace, stints, pace model, strategy, lap comparison
  synth.py        invented lap for offline demos and tests
  mcp_server.py   MCP tools
  cli.py          f1ai command
  video/
    layout.py     HUD profiles
    digits.py     digit classifier
    render.py     telemetry -> video
    extract.py    video -> telemetry
    evaluate.py   alignment and accuracy
    profiles/     built-in HUD profiles
dashboard/        Streamlit app, Plotly charts, static site builder
docs/             the built website (GitHub Pages)
tests/
data/             cache, videos, extracted telemetry, trained model (git-ignored)
```
