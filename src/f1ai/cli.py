"""Command line entry point: `f1ai <command>`."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from .config import ROOT, TELEMETRY_DIR, VIDEO_DIR


def _dashboard(args) -> int:
    app = ROOT / "dashboard" / "app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(args.port)])


def _mcp(args) -> int:
    from .mcp_server import main

    main()
    return 0


def _results(args) -> int:
    from . import analysis as an
    from . import data

    ses = data.load_session(args.year, args.event, args.session)
    print(ses.title)
    print(an.results_frame(ses).to_string(index=False))
    return 0


def _render(args) -> int:
    from . import analysis as an
    from . import data
    from .video import render

    if args.synthetic:
        from .synth import synthetic_lap

        tel, name, view = synthetic_lap(), f"synthetic-{args.profile}.mp4", None
    else:
        from .video import scene

        ses = data.load_session(args.year, args.event, args.session)
        tel = an.lap_telemetry(ses, args.driver, args.lap)
        name = f"{ses.year}-r{ses.round:02d}-{ses.code}-{tel.attrs['driver']}-lap{tel.attrs['lap_number']}-{args.profile}.mp4"
        view = scene.for_lap(ses, tel)
    out = args.out or str(VIDEO_DIR / name)
    print(json.dumps(render.render_onboard(tel, out, args.profile, max_seconds=args.seconds, scene=view), indent=2))
    return 0


def _extract(args) -> int:
    from . import video

    tel = video.extract_telemetry(args.video, args.profile, args.start, args.end)
    from pathlib import Path

    out = args.out or str(TELEMETRY_DIR / (Path(args.video).stem + ".csv"))
    tel.to_csv(out, index=False, float_format="%.3f")
    print(f"{len(tel)} frames -> {out}")
    print(f"speed read rate: {tel.attrs['speed_read_rate'] * 100:.1f}%  "
          f"top speed: {tel['Speed'].max():.0f} km/h  distance: {tel['Distance'].iloc[-1]:.0f} m")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # event names contain accents
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="f1ai", description="Formula 1 AI toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dashboard", help="open the dashboard")
    d.add_argument("--port", type=int, default=8501)
    d.set_defaults(fn=_dashboard)

    sub.add_parser("mcp", help="run the MCP server on stdio").set_defaults(fn=_mcp)

    r = sub.add_parser("results", help="print a session classification")
    r.add_argument("year", type=int)
    r.add_argument("event")
    r.add_argument("session", nargs="?", default="R")
    r.set_defaults(fn=_results)

    v = sub.add_parser("render", help="render a lap as an onboard video with HUD")
    v.add_argument("--year", type=int)
    v.add_argument("--event")
    v.add_argument("--session", default="Q")
    v.add_argument("--driver")
    v.add_argument("--lap", type=int)
    v.add_argument("--synthetic", action="store_true", help="use an invented lap (works offline)")
    v.add_argument("--profile", default="cluster")
    v.add_argument("--seconds", type=float, help="only render the first N seconds")
    v.add_argument("--out")
    v.set_defaults(fn=_render)

    e = sub.add_parser("extract", help="read telemetry out of a video")
    e.add_argument("video")
    e.add_argument("--profile", default="cluster")
    e.add_argument("--start", type=float, default=0.0)
    e.add_argument("--end", type=float)
    e.add_argument("--out")
    e.set_defaults(fn=_extract)

    args = p.parse_args(argv)
    if args.cmd == "render" and not args.synthetic and not (args.year and args.event and args.driver):
        p.error("render needs --year, --event and --driver (or --synthetic)")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
