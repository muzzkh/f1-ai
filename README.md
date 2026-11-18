# F1 AI

Formula 1 race analysis drawn on the real circuits, an MCP server for AI
assistants, and a video-to-telemetry reader, in one Python project.

**Website:** https://muzzkh.github.io/f1-ai/

| Part | What it does | Where |
|---|---|---|
| Data layer | Timing, tyres, results, weather, telemetry and GPS for every session since 2023, cached on disk | `src/f1ai/data.py` |
| Analysis | Race pace, tyre stints, fuel-corrected degradation model, pit-loss measurement, strategy simulation, GPS-aligned lap comparison | `src/f1ai/analysis.py` |
| Track engine | Real circuit geometry: smooth outline, elevation, corners, pit lane, laps placed on the circuit | `src/f1ai/track.py` |
| Website | Race, lap duel, season, video lab and about pages, hand-written and fed by JSON | `docs/` |
| Dashboard | Six views over any session, on your machine | `dashboard/app.py` |
| MCP server | 13 tools that let an AI assistant query all of the above | `src/f1ai/mcp_server.py` |
| Video to telemetry | Reads speed, gear, throttle, brake and revs off an onboard video's on-screen cluster | `src/f1ai/video/` |

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

## Website

GitHub Pages serves `docs/` as it is. It cannot run Python, so the site is
static: hand-written HTML, CSS and JavaScript modules (no framework, no build
step) that draw everything from JSON files in `docs/data/`.

| Page | What is on it |
|---|---|
| `index.html` (Race) | Result, the real circuit with the race's fastest lap replaying on it (speed, gear and pedal layers, flat or in 3D with elevation), live instrument cluster, classification, full race replay, position and gap charts, tyre strategy, pace, strategy model |
| `duel.html` | The two fastest qualifying laps raced against each other: both cars on the circuit, twin clusters, synced traces, every corner compared |
| `season.html` | Calendar of every circuit outline, championship progression, points by round |
| `video.html` | The video reader at work: frames, the regions it reads, what it read against the truth |
| `about.html` | The project, the MCP tools, how to run it |

`?r=12` on the race and duel pages opens another weekend. `?t=31.5` opens the
lap paused at that moment.

Build the data:

```bash
.venv/Scripts/python.exe dashboard/build_site.py
```

That builds the latest finished weekend plus the season, video lab and tool
list. `--round 12` builds one weekend, `--all` every finished weekend not
built yet, `--no-replay` skips the race replay (22 large downloads per race),
`--if-new` does nothing when the latest weekend is already built.

The `Update website` workflow (`.github/workflows/update-site.yml`) runs every
Monday at 06:00 UTC with `--if-new` and commits the result, so the site picks
up each race by itself. GitHub pauses scheduled workflows after 60 days
without repository activity (the winter break is longer than that), so
re-enable it in the Actions tab before a new season.

Preview locally with any static server, for example:

```bash
.venv/Scripts/python.exe -m http.server 8600 --directory docs
```

The design direction (palette, type, grid, motion) is in `design/brief.md`.

## Track engine

`track.build_track(session, lap)` returns the circuit as an evenly sampled
closed line, oriented the way circuit maps are drawn, with elevation, official
corner numbers and the start line. `track.lap_on_track` places a lap's
telemetry on it, `track.pit_lane` traces the pit lane from a car that stopped,
and `track.outline` gives a circuit's shape alone.

What is real and what is not:

- **Real:** circuit shape, elevation, corner numbers, pit lane path, where each
  car was.
- **Measured along a driven line:** circuit length comes out about 2% shorter
  than the official centreline distance.
- **Not in any public source:** track width and kerbs. The site draws them to
  a stylised width and says so.

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

1. A **HUD profile** says where each graphic sits in the frame: number boxes,
   straight bars, curved gauges, on/off lights. Coordinates are fractions of
   the frame, so one profile works at any resolution.
2. **Numbers** (speed, gear) are read by a small neural network trained on
   digits rendered from the fonts installed on this machine, with blur, noise
   and slant added. It is trained on first use (about 30 s) and cached.
3. **Gauges** (throttle, brake, revs) are read by measuring how far the
   coloured part extends; **lights** by whether they are lit.
4. A clean-up pass removes misreads using the fact that a car's speed cannot
   jump between frames, then adds distance and longitudinal g.

The **instrument cluster** is defined once, in
`src/f1ai/video/cluster.json`. The website draws it live from that file, the
renderer burns the same geometry into video, and the reader's `cluster`
profile is derived from it, so the three always agree. The numerals in video
use a system font, so their shapes differ from the website's.

Measured on rendered test footage of a real qualifying lap (1280x720, MPEG-4
compressed): speed error about 0.01 km/h, gear and brake 100% correct,
throttle within 1 point, revs within about 100 rpm. The digit reader scores
99.6% on a font family it was never trained on.

**Real broadcast footage** has its own on-screen design and needs its own
profile: load the video in the dashboard, open *Calibrate HUD profile*, move
the boxes onto the graphics, check the live readout, and save. This has not
been tested on real broadcast video. The reported *frames with speed read*
percentage tells you whether a profile fits.

Command line (an invented lap, works offline; use `--year --event --driver`
for a real one):

```bash
.venv/Scripts/f1ai.exe render --synthetic --seconds 20 --profile cluster
```

```bash
.venv/Scripts/f1ai.exe extract data/videos/synthetic-cluster.mp4 --profile cluster
```

## Data sources and limits

- **OpenF1** (timing, tyres, telemetry, GPS, overtakes) - free, no account,
  2023 onwards, limited to about 30 requests a minute. Everything is cached in
  `data/cache`, so each session is only downloaded once.
- **MultiViewer** circuit API for the circuit survey; **Jolpica** for
  standings and winners.
- Car telemetry is sampled at about 4 Hz. Lap comparisons agree with official
  sector times to a few hundredths of a second; differences at the level of a
  single corner, and racing lines, are indicative.
- The pace model is deliberately simple (linear tyre wear, one fuel
  coefficient). It needs a dry race with at least two compounds in use, and the
  strategy simulation ignores traffic, safety cars and track evolution.
- The official F1 live-timing feed requires an F1 account sign-in, which is
  why this project does not use the FastF1 library.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -m "not network"
```

```bash
.venv/Scripts/python.exe -m pytest -m network
```

The offline suite checks the analysis against a made-up race with known
parameters and runs the full video round trip, including the instrument
cluster. The network suite checks real sessions, the track geometry and the
website's data files.

## Layout

```
src/f1ai/
  data.py         OpenF1 client, cache, Session object, telemetry, GPS
  analysis.py     pace, stints, pace model, strategy, lap comparison
  track.py        circuit geometry
  sitedata.py     JSON payloads for the website
  synth.py        invented lap for offline demos and tests
  mcp_server.py   MCP tools
  cli.py          f1ai command
  video/
    cluster.json  the instrument cluster, defined once
    cluster.py    draws it into video, derives its reading profile
    layout.py     HUD profiles
    digits.py     digit classifier
    render.py     telemetry -> video
    extract.py    video -> telemetry
    evaluate.py   alignment and accuracy
dashboard/
  app.py          Streamlit dashboard
  charts.py       its Plotly figures
  build_site.py   writes docs/data/
docs/             the website (HTML, css/, js/) and its data
design/           design brief and screenshots
tests/
data/             cache, videos, extracted telemetry, trained model (git-ignored)
```

Unofficial fan project, not associated with the Formula 1 companies.
