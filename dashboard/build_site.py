"""Build the data behind the static website.

The site itself (docs/*.html, docs/css, docs/js) is hand-written. This script
only writes docs/data/: one folder per race weekend plus the season file.
GitHub Pages serves docs/ as it is.

    python dashboard/build_site.py                 latest weekend (+ season)
    python dashboard/build_site.py --if-new        do nothing if already built
    python dashboard/build_site.py --round 12      one specific weekend
    python dashboard/build_site.py --all           every finished weekend not built yet
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from f1ai import data, sitedata  # noqa: E402
from f1ai.config import ROOT  # noqa: E402

MARKER = "build.json"  # which race weekend the built site shows


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"  {path.relative_to(path.parents[2]) if len(path.parents) > 2 else path}  {path.stat().st_size // 1024} KB")


def round_dir(out: Path, rnd: int) -> Path:
    return out / "data" / f"r{rnd:02d}"


def is_current(out: Path) -> bool:
    """True when the built site already shows the latest finished race weekend."""
    try:
        built = json.loads((out / MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    year, rnd, _ = data.latest_completed_event()
    return (built.get("year"), built.get("round")) == (year, rnd) and (round_dir(out, rnd) / "race.json").exists()


def build_round(out: Path, year: int, rnd: int) -> dict:
    race = data.load_session(year, rnd, "R")
    print(f"{race.title}")
    folder = round_dir(out, race.round)
    write(folder / "race.json", sitedata.race_payload(race))
    try:
        quali = data.load_session(year, race.round, "Q")
        write(folder / "duel.json", sitedata.duel_payload(quali))
    except (data.DataError, ValueError, RuntimeError) as exc:
        print(f"  no lap duel for this weekend: {exc}")
    return sitedata.styles(race)


def build(out: Path, year: int | None, rounds: list[int] | None, everything: bool, repo_url: str) -> None:
    latest_year, latest_round, _ = data.latest_completed_event()
    year = year or latest_year
    done = sorted(int(x) for x in data.completed_events(year)["RoundNumber"])
    if everything:
        rounds = [x for x in done if not (round_dir(out, x) / "race.json").exists()]
    elif not rounds:
        rounds = [latest_round if year == latest_year else done[-1]]

    st: dict = {}
    for rnd in rounds:
        try:
            st = build_round(out, year, rnd)
        except (data.DataError, ValueError, RuntimeError) as exc:
            print(f"  round {rnd} skipped: {exc}")

    built = {x for x in done if (round_dir(out, x) / "race.json").exists()}
    if not st and built:
        st = sitedata.styles(data.load_session(year, max(built), "R"))
    print("season")
    season = sitedata.season_payload(year, built, {k: v["color"] for k, v in st.items()})
    season["latest"] = max(built) if built else None
    season["repo"] = repo_url
    season["generated"] = datetime.now(timezone.utc).strftime("%d %B %Y")
    write(out / "data" / "season.json", season)

    (out / ".nojekyll").write_text("", encoding="utf-8")
    if built:
        name = next(x["name"] for x in season["rounds"] if x["round"] == max(built))
        (out / MARKER).write_text(json.dumps({"year": year, "round": max(built), "event": name}), encoding="utf-8")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Build the website's data into docs/data/")
    p.add_argument("--year", type=int)
    p.add_argument("--round", type=int, action="append", help="build this round (repeatable)")
    p.add_argument("--all", action="store_true", help="build every finished weekend that has no data yet")
    p.add_argument("--if-new", action="store_true", help="do nothing if the latest weekend is already built")
    p.add_argument("--out", default=str(ROOT / "docs"))
    p.add_argument("--repo-url", default="https://github.com/muzzkh/f1-ai")
    args = p.parse_args()
    out = Path(args.out)
    if args.if_new and not (args.round or args.all) and is_current(out):
        print("site already shows the latest race weekend; nothing to do")
        return
    build(out, args.year, args.round, args.all, args.repo_url)


if __name__ == "__main__":
    main()
