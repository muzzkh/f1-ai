"""F1 timing data from the OpenF1 API (no account or key needed), cached on disk.

OpenF1 covers 2023 onwards. Circuit corner positions come from the MultiViewer
circuit API and championship standings from the Jolpica (Ergast) API.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

from .config import CACHE_DIR

OPENF1 = "https://api.openf1.org/v1/"
JOLPICA = "https://api.jolpi.ca/ergast/f1/"
FIRST_SEASON = 2023

_HTTP = requests.Session()
_HTTP.headers["User-Agent"] = "f1ai/0.1"
_LOCK = threading.RLock()
_last_request = 0.0
_MIN_INTERVAL = 0.45  # OpenF1 free tier: 3 requests/second, 30/minute

SESSION_ALIASES = {
    "r": "R", "race": "R", "grand prix": "R",
    "q": "Q", "quali": "Q", "qualifying": "Q",
    "s": "S", "sprint": "S",
    "sq": "SQ", "sprint qualifying": "SQ", "sprint shootout": "SQ", "ss": "SQ",
    "fp1": "FP1", "practice 1": "FP1",
    "fp2": "FP2", "practice 2": "FP2",
    "fp3": "FP3", "practice 3": "FP3",
}
SESSION_LABELS = {
    "R": "Race", "Q": "Qualifying", "S": "Sprint", "SQ": "Sprint Qualifying",
    "FP1": "Practice 1", "FP2": "Practice 2", "FP3": "Practice 3",
}
_NAME_TO_CODE = {
    "Race": "R", "Qualifying": "Q", "Sprint": "S", "Sprint Qualifying": "SQ",
    "Sprint Shootout": "SQ", "Practice 1": "FP1", "Practice 2": "FP2", "Practice 3": "FP3",
}
_SESSION_ORDER = ["FP1", "FP2", "FP3", "SQ", "S", "Q", "R"]


class DataError(RuntimeError):
    """Raised when the requested data does not exist or cannot be fetched."""


# ----------------------------------------------------------------------------
# HTTP + cache
# ----------------------------------------------------------------------------

def _utc(values, errors: str = "raise") -> pd.Series:
    """Parse ISO timestamps to UTC at nanosecond resolution. Pinning the
    resolution keeps pandas 2 and 3 (which default differently) in agreement
    when timestamps are compared or merged."""
    return pd.to_datetime(values, utc=True, errors=errors, format="ISO8601").astype("datetime64[ns, UTC]")


def _now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _fetch_json(url: str, ttl: float | None) -> Any:
    """GET with an on-disk cache. ttl=None caches forever."""
    global _last_request
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists():
        if ttl is None or (time.time() - path.stat().st_mtime) < ttl:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    with _LOCK:
        for attempt in range(6):
            wait = _MIN_INTERVAL - (time.time() - _last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = _HTTP.get(url, timeout=60)
            except requests.RequestException as exc:
                if attempt == 5:
                    if path.exists():  # stale cache beats no data
                        return json.loads(path.read_text(encoding="utf-8"))
                    raise DataError(f"Network error fetching F1 data: {exc}") from exc
                time.sleep(2 + attempt * 2)
                continue
            finally:
                _last_request = time.time()
            if resp.status_code == 200:
                data = resp.json()
                path.write_text(json.dumps(data), encoding="utf-8")
                return data
            if resp.status_code == 404:
                return []  # OpenF1 answers 404 for "no rows"
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(resp.headers.get("Retry-After", 3 + attempt * 4)))
                continue
            raise DataError(f"HTTP {resp.status_code} from {url.split('?')[0]}")
        raise DataError("F1 data API is rate limiting requests; try again in a minute.")


def _openf1(endpoint: str, ttl: float | None = None, **params: Any) -> list[dict]:
    # Built by hand: OpenF1 filters use operators inside the key (date>=...).
    query = "&".join(f"{k}{v}" if k[-1] in "<>=" else f"{k}={v}" for k, v in params.items())
    data = _fetch_json(f"{OPENF1}{endpoint}?{query}", ttl)
    return data if isinstance(data, list) else []


# ----------------------------------------------------------------------------
# calendar
# ----------------------------------------------------------------------------

def normalise_session(session: str) -> str:
    key = str(session).strip().lower()
    if key in SESSION_ALIASES:
        return SESSION_ALIASES[key]
    raise ValueError(f"Unknown session '{session}'. Use one of: R, Q, S, SQ, FP1, FP2, FP3.")


def _season_ttl(year: int) -> float | None:
    return None if year < _now().year else 3 * 3600


def schedule(year: int) -> pd.DataFrame:
    """Race weekends of a season with the sessions each one runs."""
    year = int(year)
    if year < FIRST_SEASON:
        raise DataError(f"Timing data starts in {FIRST_SEASON}; {year} is not available.")
    meetings = _openf1("meetings", ttl=_season_ttl(year), year=year)
    sessions = _openf1("sessions", ttl=_season_ttl(year), year=year)
    if not meetings:
        raise DataError(f"No calendar found for {year}.")
    by_meeting: dict[int, list[dict]] = {}
    for s in sessions:
        if not s.get("is_cancelled"):
            by_meeting.setdefault(s["meeting_key"], []).append(s)
    rows = []
    races = [m for m in meetings if "testing" not in str(m.get("meeting_name", "")).lower()]
    races.sort(key=lambda m: m["date_start"])
    i = 0
    for m in races:
        ses = by_meeting.get(m["meeting_key"], [])
        codes = {_NAME_TO_CODE[s["session_name"]]: s for s in ses if s["session_name"] in _NAME_TO_CODE}
        if "R" not in codes:
            continue  # cancelled weekend: listed in the calendar but never run
        i += 1
        end = max((pd.Timestamp(s["date_end"]) for s in ses), default=pd.Timestamp(m["date_start"]))
        rows.append(
            {
                "RoundNumber": i,
                "EventName": m["meeting_name"],
                "Country": m.get("country_name"),
                "Location": m.get("location"),
                "Circuit": m.get("circuit_short_name"),
                "EventDate": end,
                "Sessions": [c for c in _SESSION_ORDER if c in codes],
                "MeetingKey": m["meeting_key"],
                "CircuitKey": m.get("circuit_key"),
                "_sessions": codes,
            }
        )
    return pd.DataFrame(rows)


def completed_events(year: int) -> pd.DataFrame:
    sched = schedule(year)
    return sched[sched["EventDate"] + pd.Timedelta(hours=1) < _now()]


def latest_completed_event(year: int | None = None) -> tuple[int, int, str]:
    """(year, round, event name) of the most recent finished race weekend."""
    year = year or _now().year
    for y in (year, year - 1):
        try:
            done = completed_events(y)
        except DataError:
            continue
        if len(done):
            last = done.iloc[-1]
            return y, int(last["RoundNumber"]), str(last["EventName"])
    raise DataError("Could not find a completed event in the calendar.")


def _resolve_event(year: int, event: int | str) -> pd.Series:
    sched = schedule(year)
    if isinstance(event, str) and event.strip().isdigit():
        event = int(event.strip())
    if isinstance(event, (int, np.integer)):
        hit = sched[sched["RoundNumber"] == int(event)]
        if hit.empty:
            raise DataError(f"{year} has no round {event} (rounds 1-{len(sched)}).")
        return hit.iloc[0]
    q = str(event).strip().lower()
    for col in ("EventName", "Location", "Country", "Circuit"):
        hit = sched[sched[col].astype(str).str.lower().str.contains(q, regex=False)]
        if len(hit):
            return hit.iloc[0]
    names = sched["EventName"].tolist()
    close = difflib.get_close_matches(str(event), names, n=1, cutoff=0.5)
    if close:
        return sched[sched["EventName"] == close[0]].iloc[0]
    raise DataError(f"No {year} event matches '{event}'. Events: {', '.join(names)}")


# ----------------------------------------------------------------------------
# session
# ----------------------------------------------------------------------------

@dataclass
class Session:
    year: int
    round: int
    event_name: str
    name: str            # "Race", "Qualifying", ...
    code: str            # "R", "Q", ...
    session_key: int
    meeting_key: int
    circuit_key: int | None
    circuit: str
    country: str
    date_start: pd.Timestamp
    date_end: pd.Timestamp
    drivers: pd.DataFrame
    laps: pd.DataFrame
    results: pd.DataFrame
    weather: pd.DataFrame
    race_control: pd.DataFrame
    total_laps: int
    _tel_cache: dict = field(default_factory=dict, repr=False)

    @property
    def is_race(self) -> bool:
        return self.code in ("R", "S")

    @property
    def title(self) -> str:
        return f"{self.year} {self.event_name} - {self.name}"


_SESSIONS: dict[tuple, Session] = {}


def _neutralised_intervals(rc: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    """Time windows under safety car, virtual safety car or red flag."""
    out = []
    if rc.empty:
        return out
    open_at: dict[str, pd.Timestamp] = {}
    for _, m in rc.sort_values("date").iterrows():
        msg = str(m.get("message", "")).upper()
        t = m["date"]
        if "VIRTUAL SAFETY CAR DEPLOYED" in msg:
            open_at.setdefault("VSC", t)
        elif "VIRTUAL SAFETY CAR ENDING" in msg and "VSC" in open_at:
            out.append((open_at.pop("VSC"), t + pd.Timedelta(seconds=20), "VSC"))
        elif "SAFETY CAR DEPLOYED" in msg:
            open_at.setdefault("SC", t)
        elif "SAFETY CAR IN THIS LAP" in msg and "SC" in open_at:
            out.append((open_at.pop("SC"), t + pd.Timedelta(seconds=100), "SC"))
        elif str(m.get("flag", "")).upper() == "RED":
            open_at.setdefault("RED", t)
        elif "RED" in open_at and (str(m.get("flag", "")).upper() == "GREEN" or "RESUME" in msg):
            out.append((open_at.pop("RED"), t + pd.Timedelta(seconds=120), "RED"))
    far = pd.Timestamp("2100-01-01", tz="UTC")
    out += [(t, far, k) for k, t in open_at.items()]
    return out


def _build_laps(raw: dict, drivers: pd.DataFrame, is_race: bool) -> pd.DataFrame:
    laps = pd.DataFrame(raw["laps"])
    if laps.empty:
        return laps
    for col in ("lap_duration", "duration_sector_1", "duration_sector_2", "duration_sector_3", "st_speed"):
        if col not in laps:
            laps[col] = np.nan
    info = drivers.set_index("DriverNumber")
    df = pd.DataFrame(
        {
            "DriverNumber": laps["driver_number"].astype(int),
            "LapNumber": laps["lap_number"].astype(int),
            "LapTime": pd.to_numeric(laps["lap_duration"], errors="coerce"),
            "Sector1": pd.to_numeric(laps["duration_sector_1"], errors="coerce"),
            "Sector2": pd.to_numeric(laps["duration_sector_2"], errors="coerce"),
            "Sector3": pd.to_numeric(laps["duration_sector_3"], errors="coerce"),
            "SpeedTrap": pd.to_numeric(laps["st_speed"], errors="coerce"),
            "PitOut": laps.get("is_pit_out_lap", False).fillna(False).astype(bool),
            "LapStart": _utc(laps["date_start"], errors="coerce"),
        }
    )
    df["Driver"] = df["DriverNumber"].map(info["Driver"])
    df["Team"] = df["DriverNumber"].map(info["Team"])
    df = df.dropna(subset=["Driver"]).sort_values(["DriverNumber", "LapNumber"]).reset_index(drop=True)

    # tyres: join stints by lap range
    df["Compound"], df["Stint"], df["TyreLife"], df["FreshTyre"] = "UNKNOWN", np.nan, np.nan, None
    for s in raw["stints"]:
        if s.get("lap_start") is None or s.get("lap_end") is None:
            continue
        m = (
            (df["DriverNumber"] == s["driver_number"])
            & (df["LapNumber"] >= s["lap_start"])
            & (df["LapNumber"] <= s["lap_end"])
        )
        age0 = s.get("tyre_age_at_start") or 0
        df.loc[m, "Compound"] = str(s.get("compound") or "UNKNOWN").upper()
        df.loc[m, "Stint"] = s.get("stint_number")
        df.loc[m, "TyreLife"] = age0 + (df.loc[m, "LapNumber"] - s["lap_start"]) + 1
        df.loc[m, "FreshTyre"] = age0 == 0

    # pit in laps
    pits = {(p["driver_number"], p["lap_number"]) for p in raw["pit"] if p.get("lap_number") is not None}
    df["PitIn"] = [(d, l) in pits for d, l in zip(df["DriverNumber"], df["LapNumber"])]

    # track status per lap
    df["TrackStatus"] = "GREEN"
    lap_end = df["LapStart"] + pd.to_timedelta(df["LapTime"].fillna(0), unit="s")
    rc = pd.DataFrame(raw["race_control"])
    if not rc.empty:
        rc["date"] = _utc(rc["date"])
        for t0, t1, kind in _neutralised_intervals(rc):
            m = df["LapStart"].notna() & (df["LapStart"] < t1) & (lap_end > t0)
            df.loc[m, "TrackStatus"] = kind

    # position at the end of each lap
    df["Position"] = np.nan
    pos = pd.DataFrame(raw["position"])
    if is_race and not pos.empty:
        pos["date"] = _utc(pos["date"])
        pos = pos.sort_values("date")
        timed = df[df["LapStart"].notna()].assign(_end=lap_end).sort_values("_end")
        merged = pd.merge_asof(
            timed[["DriverNumber", "LapNumber", "_end"]],
            pos[["date", "driver_number", "position"]],
            left_on="_end", right_on="date",
            left_by="DriverNumber", right_by="driver_number",
        )
        key = dict(zip(zip(merged["DriverNumber"], merged["LapNumber"]), merged["position"]))
        df["Position"] = [key.get(k, np.nan) for k in zip(df["DriverNumber"], df["LapNumber"])]

    df["IsAccurate"] = df["LapTime"].notna() & ~df["PitOut"]
    if is_race:
        df.loc[df["LapNumber"] == 1, "IsAccurate"] = False  # standing start
    return df


def _build_results(raw: dict, drivers: pd.DataFrame, laps: pd.DataFrame, code: str) -> pd.DataFrame:
    info = drivers.set_index("DriverNumber")
    best = laps.groupby("DriverNumber")["LapTime"].min() if len(laps) else pd.Series(dtype=float)
    rows = []
    res = sorted(raw["session_result"], key=lambda r: (r.get("position") is None, r.get("position") or 99))
    grid = {g["driver_number"]: g["position"] for g in raw.get("starting_grid", [])}
    for r in res:
        n = r["driver_number"]
        if n not in info.index:
            continue
        row = {
            "Pos": r.get("position"),
            "Driver": info.at[n, "Driver"],
            "Name": info.at[n, "FullName"],
            "Team": info.at[n, "Team"],
        }
        if code in ("R", "S"):
            gap = r.get("gap_to_leader")
            status = "DSQ" if r.get("dsq") else "DNS" if r.get("dns") else "DNF" if r.get("dnf") else (
                gap if isinstance(gap, str) else "Finished")
            row.update(
                {
                    "Grid": grid.get(n),
                    "Laps": r.get("number_of_laps"),
                    "Status": status,
                    "Gap_s": float(gap) if isinstance(gap, (int, float)) else np.nan,
                    "Points": r.get("points"),
                }
            )
        elif code in ("Q", "SQ"):
            dur = r.get("duration")
            dur = dur if isinstance(dur, list) else [dur]
            for i, q in enumerate(("Q1", "Q2", "Q3")):
                v = dur[i] if i < len(dur) else None
                row[q + "_s"] = float(v) if isinstance(v, (int, float)) else np.nan
        row["BestLap_s"] = float(best.get(n, np.nan))
        rows.append(row)
    if not rows and len(laps):  # no official classification published: order by best lap
        order = best.sort_values().index
        for i, n in enumerate(order, start=1):
            if n in info.index:
                rows.append({"Pos": i, "Driver": info.at[n, "Driver"], "Name": info.at[n, "FullName"],
                             "Team": info.at[n, "Team"], "BestLap_s": float(best[n])})
    return pd.DataFrame(rows)


def load_session(year: int, event: int | str, session: str = "R") -> Session:
    """Load a session (laps, tyres, results, weather). Cached in memory and on disk."""
    code = normalise_session(session)
    ev = _resolve_event(int(year), event)
    key = (int(year), int(ev["RoundNumber"]), code)
    with _LOCK:
        if key in _SESSIONS:
            return _SESSIONS[key]
        meta = ev["_sessions"].get(code)
        if meta is None:
            avail = ", ".join(ev["Sessions"])
            raise DataError(f"{year} {ev['EventName']} has no {SESSION_LABELS[code]} session (has: {avail}).")
        end = pd.Timestamp(meta["date_end"])
        if pd.Timestamp(meta["date_start"]) > _now():
            raise DataError(f"{year} {ev['EventName']} {SESSION_LABELS[code]} has not started yet.")
        # data for a session that finished a day ago never changes again
        ttl = None if end + pd.Timedelta(hours=24) < _now() else 600
        sk = meta["session_key"]
        raw = {ep: _openf1(ep, ttl=ttl, session_key=sk)
               for ep in ("drivers", "laps", "stints", "pit", "race_control", "weather", "session_result")}
        raw["position"] = _openf1("position", ttl=ttl, session_key=sk) if code in ("R", "S") else []
        if code in ("R", "S"):
            qual = ev["_sessions"].get("Q" if code == "R" else "SQ")
            grid = _openf1("starting_grid", ttl=ttl, meeting_key=meta["meeting_key"])
            raw["starting_grid"] = [g for g in grid if qual and g.get("session_key") == qual["session_key"]]
        if not raw["drivers"] or not raw["laps"]:
            raise DataError(f"No timing data available for {year} {ev['EventName']} {SESSION_LABELS[code]}.")

        drivers = pd.DataFrame(
            [
                {
                    "DriverNumber": int(d["driver_number"]),
                    "Driver": d.get("name_acronym") or str(d["driver_number"]),
                    "FullName": (d.get("full_name") or "").title(),
                    "Team": d.get("team_name") or "",
                    "TeamColor": "#" + str(d.get("team_colour") or "888888").lstrip("#"),
                }
                for d in raw["drivers"]
            ]
        ).drop_duplicates("DriverNumber")
        laps = _build_laps(raw, drivers, code in ("R", "S"))
        results = _build_results(raw, drivers, laps, code)
        weather = pd.DataFrame(raw["weather"])
        rc = pd.DataFrame(raw["race_control"])
        total = int(max((r.get("number_of_laps") or 0 for r in raw["session_result"]), default=0)) or int(
            laps["LapNumber"].max())
        ses = Session(
            year=int(year), round=int(ev["RoundNumber"]), event_name=str(ev["EventName"]),
            name=SESSION_LABELS[code], code=code, session_key=sk, meeting_key=meta["meeting_key"],
            circuit_key=meta.get("circuit_key"), circuit=str(meta.get("circuit_short_name") or ""),
            country=str(meta.get("country_name") or ""),
            date_start=pd.Timestamp(meta["date_start"]), date_end=end,
            drivers=drivers, laps=laps, results=results, weather=weather, race_control=rc, total_laps=total,
        )
        _SESSIONS[key] = ses
        return ses


def session_title(ses: Session) -> str:
    return ses.title


def driver_list(ses: Session) -> list[str]:
    """Driver abbreviations in classification order."""
    if len(ses.results):
        return ses.results["Driver"].tolist()
    return sorted(ses.laps["Driver"].unique().tolist())


def resolve_driver(ses: Session, driver: str | int) -> str:
    """Accept an abbreviation, car number or (part of) a name."""
    d = str(driver).strip()
    drivers = ses.drivers
    hit = drivers[drivers["Driver"].str.upper() == d.upper()]
    if hit.empty and d.isdigit():
        hit = drivers[drivers["DriverNumber"] == int(d)]
    if hit.empty and d:
        hit = drivers[drivers["FullName"].str.lower().str.contains(d.lower(), regex=False)]
    if hit.empty:
        raise DataError(f"Driver '{driver}' not found. Available: {', '.join(driver_list(ses))}")
    return str(hit.iloc[0]["Driver"])


# ----------------------------------------------------------------------------
# telemetry
# ----------------------------------------------------------------------------

def _fmt(t: pd.Timestamp) -> str:
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.%f")


def lap_telemetry(ses: Session, driver: str | int, lap_number: int | None = None) -> pd.DataFrame:
    """Car telemetry for one lap (the driver's fastest by default).

    Columns: Time (s from lap start), Distance (m, integrated from speed),
    Speed (km/h), Throttle (%), Brake (0/100), nGear, RPM, DRS (0/1, NaN from
    2026 when DRS no longer exists), X, Y (m).
    """
    drv = resolve_driver(ses, driver)
    laps = ses.laps[(ses.laps["Driver"] == drv) & ses.laps["LapStart"].notna() & ses.laps["LapTime"].notna()]
    if lap_number is None:
        cand = laps[laps["IsAccurate"]] if laps["IsAccurate"].any() else laps
        if cand.empty:
            raise DataError(f"{drv} has no timed lap in this session.")
        lap = cand.loc[cand["LapTime"].idxmin()]
    else:
        sel = laps[laps["LapNumber"] == int(lap_number)]
        if sel.empty:
            raise DataError(f"{drv} has no timed lap {lap_number} in this session.")
        lap = sel.iloc[0]
    key = (drv, int(lap["LapNumber"]))
    if key in ses._tel_cache:
        return ses._tel_cache[key].copy()

    t0 = lap["LapStart"]
    t1 = t0 + pd.Timedelta(seconds=float(lap["LapTime"]))
    num = int(lap["DriverNumber"])
    window = {"session_key": ses.session_key, "driver_number": num, "date>=": _fmt(t0), "date<": _fmt(t1)}
    car = pd.DataFrame(_openf1("car_data", **window))
    if car.empty or len(car) < 20:
        raise DataError(f"No car telemetry available for {drv} lap {int(lap['LapNumber'])}.")
    car["date"] = _utc(car["date"])
    car = car.sort_values("date").drop_duplicates("date")
    t = (car["date"] - t0).dt.total_seconds().values
    speed = pd.to_numeric(car["speed"], errors="coerce").ffill().bfill().values.astype(float)
    drs_raw = pd.to_numeric(car.get("drs"), errors="coerce")
    drs = np.where(drs_raw.isna(), np.nan, drs_raw.isin([10, 12, 14]).astype(float))
    tel = pd.DataFrame(
        {
            "Time": t,
            "Speed": speed,
            "Throttle": pd.to_numeric(car["throttle"], errors="coerce").clip(0, 100).ffill().bfill().values,
            "Brake": (pd.to_numeric(car["brake"], errors="coerce").fillna(0) > 0).astype(float).values * 100.0,
            "nGear": pd.to_numeric(car["n_gear"], errors="coerce").ffill().bfill().values,
            "RPM": pd.to_numeric(car["rpm"], errors="coerce").ffill().bfill().values,
            "DRS": drs,
        }
    )
    v = speed / 3.6
    dist = np.concatenate([[v[0] * t[0]], v[0] * t[0] + np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(t))])
    tel.insert(1, "Distance", dist)

    tel["X"], tel["Y"] = np.nan, np.nan
    loc = pd.DataFrame(_openf1("location", **window))
    if len(loc) > 20:
        loc["date"] = _utc(loc["date"])
        loc = loc.sort_values("date").drop_duplicates("date")
        loc = loc[(loc["x"] != 0) | (loc["y"] != 0)]
        lt = (loc["date"] - t0).dt.total_seconds().values
        if len(lt) > 20:
            tel["X"] = np.interp(t, lt, loc["x"].values / 10.0)
            tel["Y"] = np.interp(t, lt, loc["y"].values / 10.0)

    tel.attrs.update(
        driver=drv,
        lap_number=int(lap["LapNumber"]),
        lap_time=float(lap["LapTime"]),
        compound=str(lap["Compound"]),
        tyre_life=None if pd.isna(lap["TyreLife"]) else int(lap["TyreLife"]),
    )
    ses._tel_cache[key] = tel
    return tel.copy()


def circuit_corners(ses: Session) -> pd.DataFrame:
    """Official corner numbers with track coordinates in metres (may be empty)."""
    cols = ["Corner", "X", "Y"]
    if not ses.circuit_key:
        return pd.DataFrame(columns=cols)
    try:
        info = _fetch_json(f"https://api.multiviewer.app/api/v1/circuits/{ses.circuit_key}/{ses.year}", None)
    except DataError:
        return pd.DataFrame(columns=cols)
    rows = [
        {
            "Corner": f"T{c['number']}{c.get('letter') or ''}",
            "X": c["trackPosition"]["x"] / 10.0,
            "Y": c["trackPosition"]["y"] / 10.0,
        }
        for c in (info.get("corners", []) if isinstance(info, dict) else [])
    ]
    return pd.DataFrame(rows, columns=cols)


# ----------------------------------------------------------------------------
# championship
# ----------------------------------------------------------------------------

def standings(year: int) -> dict:
    """Driver and constructor championship standings (Jolpica / Ergast)."""
    ttl = _season_ttl(int(year))
    out: dict[str, Any] = {"year": int(year), "round": None, "drivers": [], "constructors": []}
    d = _fetch_json(f"{JOLPICA}{int(year)}/driverstandings.json?limit=100", ttl)
    lists = d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", []) if isinstance(d, dict) else []
    if lists:
        out["round"] = int(lists[0].get("round", 0))
        for s in lists[0].get("DriverStandings", []):
            out["drivers"].append(
                {
                    "position": int(s.get("position", 0) or 0),
                    "driver": f"{s['Driver']['givenName']} {s['Driver']['familyName']}",
                    "code": s["Driver"].get("code"),
                    "team": s["Constructors"][-1]["name"] if s.get("Constructors") else None,
                    "points": float(s["points"]),
                    "wins": int(s["wins"]),
                }
            )
    c = _fetch_json(f"{JOLPICA}{int(year)}/constructorstandings.json?limit=100", ttl)
    lists = c.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", []) if isinstance(c, dict) else []
    if lists:
        for s in lists[0].get("ConstructorStandings", []):
            out["constructors"].append(
                {
                    "position": int(s.get("position", 0) or 0),
                    "team": s["Constructor"]["name"],
                    "points": float(s["points"]),
                    "wins": int(s["wins"]),
                }
            )
    return out
