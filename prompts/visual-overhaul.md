# Prompt: visual overhaul of F1 AI

Paste everything below the line into a new Claude Code session opened in this repository.

---

You are taking over an existing, working project and giving it a complete visual overhaul. The engineering is sound; the presentation is generic. Your job is to make it look and feel like a professionally designed motorsport product, built around real track geometry and rich, purpose-made data graphics.

## What exists

Repository `muzzkh/f1-ai`, live at https://muzzkh.github.io/f1-ai/. Read `README.md` first, then the code.

- `src/f1ai/data.py` loads timing data from OpenF1 (free, no key, 2023 onwards, about 30 requests a minute, cached in `data/cache`). `src/f1ai/analysis.py` computes pace, a tyre and fuel model, strategy ranking and GPS-aligned lap comparison.
- `dashboard/app.py` is a Streamlit dashboard. `dashboard/charts.py` holds the Plotly figures. `dashboard/build_site.py` exports one static page into `docs/`, which GitHub Pages serves.
- `src/f1ai/video/` renders an onboard-style clip from telemetry and reads telemetry back off video frames. `src/f1ai/mcp_server.py` exposes 13 MCP tools.
- `.github/workflows/update-site.yml` rebuilds `docs/` every Monday and commits to `main`.
- Tests: `.venv/Scripts/python.exe -m pytest -m "not network"` and `-m network`. Local previews are defined in `.claude/launch.json` (`f1ai-dashboard` on 8501, `f1ai-site` on 8600).

Today the site is a single dark page of default-looking Plotly charts. The "track map" is a thin coloured line, the on-screen instrument cluster in the rendered video is a plain circle with basic arcs, and stat tiles are plain boxes. That is what must change.

## The goal

Make the data overwhelmingly visual. A visitor should understand a race weekend by looking, not by reading tables. Every important number should have a designed graphic, and the circuit itself should be the centrepiece of most views.

## Design direction

Study two references before designing: formula1.com and landonorris.com. Open both, and open the current live site next to them. Take notes on what makes them feel professional: confident display typography at large sizes, strict grids, full-bleed imagery, deliberate motion, strong colour discipline, dense data presented with team colour as an organising device, and (on the Norris site) immersive scroll-driven and 3D moments.

Match that level of craft with an identity of our own. Do not reuse their logos, wordmarks, proprietary typefaces, photographs, team logos, driver portraits, icons or page layouts, and do not adopt either site's signature colour pairing as ours. This is a public site under the owner's name, so imitating a brand's look is a legal risk, and it would also read as a copy rather than a product. Use freely licensed fonts, team colours from the data, driver codes and numbers, and graphics we generate. Keep the "unofficial fan project" notice in the footer.

Because taste is subjective, do not build everything before showing anything. First produce one finished race page hero (track, instrument cluster, headline stats) in your chosen direction, show desktop and mobile screenshots, and get approval. Then roll the system out.

## Workstreams

### 1. Track engine: real circuits, not sketches

Build a reusable module that turns data into accurate circuit geometry for any circuit and season. These sources were verified on 18 November 2026:

- The MultiViewer circuit API (already used in `data.circuit_corners`) returns a track outline (`x`, `y`, about 280 points), numbered corners with positions, marshal sectors and a display `rotation`.
- OpenF1 `location` returns every car's `x`, `y`, `z` at about 3.7 Hz. A whole race for one driver comes back in a single request (about 36,000 points, 4.5 MB), so a full field is about 22 requests. `z` carries elevation but contains zeros and outliers that must be filtered.
- OpenF1 also has `overtakes`, `intervals`, `position`, `race_control` and `team_radio`.

From these, produce per circuit: a smooth closed centreline resampled every few metres (refine the outline with dense fastest-lap GPS), an elevation profile, the pit lane path (from cars on pit-in laps), start/finish, sector boundaries, corner labels placed clear of the track, and the correct orientation. Real track width and kerb positions are not in the data, so generate them procedurally (a constant-width ribbon, kerbs on the inside of tight corners) and say on the site that width and kerbs are stylised. Cache the result as JSON so the front end and the Python side share one geometry.

### 2. Signature visuals

Build these on the track engine. Each should be interactive and good enough to screenshot.

- **Race replay.** Every car as a team-coloured marker moving around the real circuit, with a scrubber, play speed, lap counter, a live timing tower, tyre compound chips, safety-car and flag state, and overtake markers. Quantise and delta-encode positions so one race stays near 1 to 2 MB, and load it lazily.
- **Lap duel.** Two cars ghosting a lap against each other on the map, with the live gap, both instrument clusters animating, and the telemetry traces scrubbing in sync.
- **Circuit data layers.** The lap drawn on the track coloured by speed, gear, throttle and braking, switchable, with braking zones and top-speed points marked.
- **Corner cards.** A zoomed view of each corner with both racing lines, braking point, minimum speed and throttle pick-up.
- **3D circuit.** A tilted or fully 3D track with elevation. State the vertical exaggeration.
- **Race story.** Gap-to-leader race trace, a redesigned position chart, stint ribbons for tyre strategy, and lap-time distributions per driver.
- **Season view.** A calendar grid of every circuit outline, championship progression across rounds, and a driver-by-round points grid.
- **Video lab.** The frame, the regions being read and the extracted trace animating together.

### 3. Instrument cluster

Design a proper cluster: speed, gear, throttle, brake, RPM with shift lights, and longitudinal g. Define it once and use that definition both as a live web component and in the rendered video (`video/render.py`), so the two always match. Only show channels the data contains: there is no DRS from 2026 and no energy-store data, so do not invent them. Lateral g may be derived from GPS curvature and speed if labelled as an estimate.

The video reader must still read the new cluster. Update the HUD profiles in `video/profiles/` and keep the round-trip accuracy tests in `tests/test_video.py` passing at their current thresholds. Keep text and gauge contrast high enough for that.

### 4. Chart and component system

Create design tokens (colour, type scale, spacing, radii, motion) and build every chart and tile from them, so the site reads as one system. Replace default-looking Plotly output with purpose-made graphics; D3 with SVG or Canvas is the expected tool for the signature pieces. Keep sound chart practice: one y-axis per chart, team colour for identity with a second cue for team-mates, labels in text colours rather than series colours, hover detail on every mark, legends where there is more than one series, readable at phone width, and `prefers-reduced-motion` respected. Redesign the stat tiles, tables, timing tower and navigation as real components.

### 5. Website

Rebuild the site as a multi-page product: a home page led by the latest race, a page per completed round (an archive for the season), a season page, the lap duel, the video lab, and an about page covering the project and MCP server.

Separate data from presentation: have `build_site.py` write JSON under `docs/data/` and let hand-written HTML, CSS and JavaScript render it. Prefer plain ES modules with vendored libraries over a bundler, because the weekly Action is Python-only and a simpler pipeline has less to break; if you add a Node build step, update the workflow and prove it runs. Set and meet a weight budget for first load, and lazy-load heavy data.

### 6. Dashboard

Bring the Streamlit dashboard in line: same tokens, the track engine in the telemetry view, the new cluster in the video lab. Streamlit limits layout, so aim for consistency rather than a pixel match. The public site takes priority.

## Constraints

- Do not change what the analysis computes, and do not drop the existing accuracy caveats (4 Hz telemetry, corner-level numbers indicative, video reader verified only on rendered footage). Better visuals must not overstate precision.
- Stay within OpenF1's rate limit and keep using the disk cache.
- The site must remain static and work on GitHub Pages. The `Update website` workflow must still succeed, including its skip-when-unchanged behaviour.
- All 13 MCP tools and both test suites must keep working. Add tests for the track engine (closed loop, sensible length against the known lap distance, monotonic distance).
- Work on a branch and open a pull request. `main` deploys the live site and a bot commits to it weekly, so do not push to `main` until the owner approves.

## Order of work

1. Read the code, review the references, write a one-page design brief (palette, type, grid, motion principles) and build the approval hero. Stop for approval.
2. Track engine with tests.
3. Design tokens, components and the new instrument cluster, with the video round trip passing.
4. Signature visuals, starting with circuit data layers and lap duel, then race replay.
5. Multi-page site and JSON data pipeline, then the season view and archive.
6. Dashboard alignment, README update, workflow check.

## Verification and reporting

After each phase, preview locally, take screenshots at 1440 and 375 pixels wide, and check for console errors and horizontal overflow. Run both test suites. Before asking for the merge, run the workflow with `force` on the branch and confirm it builds. Report plainly what was done, what was verified and how, what is stylised rather than real, and anything left unfinished.
