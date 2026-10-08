"""M19T Step 0 (ADR-0013 D0): data-coverage report for the short-premium family. Data only:
entry-time quotes and exit-quote availability. No P&L is computed and no trial is registered.

Development sessions only (<= `dev_end`). `records()` refuses any later session, so the locked
holdout is never read. Inputs: scripts/m19t_build_data.py outputs (0dte, ext) plus the M4 cleaned
1DTE store (entries from 2023-03-28 on).

Sections: sessions per era / weekday; expiry-day quotes at the forced exit; credit-fraction
strike coverage (X = put_x, call_x; $width) with per-leg §4.9 gate rates and exit / path-gap
coverage of the picked legs; rejection rates; strike grid; the three degraded days.

    uv run python scripts/m19t_coverage.py
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.selection import Quote, liquidity_failures
from qqq1dte.features.inputs import chain_table
from qqq1dte.ingestion.databento_fetch import strike_band
from qqq1dte.labels.option import option_records
from qqq1dte.validation.records import build_definitions
from qqq1dte.validation.spread_coverage import (
    AT_BAND_EDGE,
    NO_QUALIFYING,
    OK,
    LegQuote,
    credit_pick,
    grid_holes,
    longest_gap_minutes,
)

ROOT = Path(__file__).resolve().parents[1]
S0: dict[str, Any] = yaml.safe_load(
    (ROOT / "configs" / "m19t_step0.yaml").read_text(encoding="utf-8")
)
CFG = load_config()
CAL = TradingCalendar(CFG)
EXT_START = date.fromisoformat(S0["ext_start"])
DEV_END = date.fromisoformat(S0["dev_end"])
ZERO_START = date(2023, 3, 28)  # first 0dte-file session = M4 option era start (ADR-0003)
CLEAN = ROOT / S0["clean_dir"]
M4 = ROOT / "data" / "clean"
REPORT = ROOT / "reports" / "research" / "m19t_data_coverage.md"
BAND_PAD = 0.05  # scripts/m19t_price_gap.py (download scope only)
LATENCY = timedelta(seconds=CFG.fills.latency_s)
MAX_AGE = timedelta(seconds=CFG.liquidity.max_quote_age_s)
MAX_GAP_MIN = float(CFG.labels.option.max_path_gap_minutes)
GRID_TOL = 1e-9
LOW_SHARE = 0.95  # report threshold for section 2
LIST_MAX = 25
NEAR = 3  # strikes either side of a picked pair checked for $1 grid holes
WD = ["Mon", "Tue", "Wed", "Thu", "Fri"]

if CAL.final_holdout_start(date.fromisoformat(S0["last_session"])) != DEV_END:
    raise SystemExit("dev_end disagrees with the ADR-0011 holdout boundary")


# inputs ----------------------------------------------------------------------------------
def source_of(d: date) -> str:
    """Store holding the expiry-day (0DTE) contracts of session d."""
    return "ext" if d < ZERO_START else "0dte"


@cache
def records(src: str, d: date) -> pl.DataFrame:
    """Quote records (cleaned + rejected) of session d. src: 0dte | ext | m4."""
    if d > DEV_END:
        raise RuntimeError(f"holdout session {d} requested: refused (ADR-0011)")
    if src == "m4":
        c = M4 / "cleaned" / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
        r = M4 / "rejected" / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
    else:
        c, r = CLEAN / "cleaned" / src / f"{d}.parquet", CLEAN / "rejected" / src / f"{d}.parquet"
    if not c.exists():
        return option_records(
            pl.DataFrame(schema={"symbol": pl.String, "available_at": pl.Datetime("ns", "UTC"),
                                 "bid": pl.Float64, "ask": pl.Float64, "bid_sz": pl.Int64,
                                 "ask_sz": pl.Int64}),
            pl.DataFrame(schema={"symbol": pl.String, "ts": pl.Datetime("ns", "UTC")}),
        )  # fmt: skip
    return option_records(pl.read_parquet(c), pl.read_parquet(r))


def load_chains() -> dict[str, pl.DataFrame]:
    out = {}
    for src in ("0dte", "ext"):
        defs = pl.read_parquet(CLEAN / "definitions" / f"{src}.parquet")
        out[src] = chain_table(defs, CFG).filter(pl.col("session_date") <= DEV_END)
    m4_defs = pl.concat(
        [
            pl.read_parquet(p)
            for p in (ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                "*.parquet"
            )
        ],
        how="diagonal_relaxed",
    )
    out["m4"] = chain_table(build_definitions(m4_defs, CAL), CFG).filter(
        pl.col("session_date") <= DEV_END
    )
    return out


CHAINS: dict[str, pl.DataFrame] = {}


def chain(src: str, d: date, exp: date) -> pl.DataFrame:
    return CHAINS[src].filter((pl.col("session_date") == d) & (pl.col("expiration") == exp))


def all_sessions() -> list[date]:
    return CAL.sessions(EXT_START, DEV_END)


# eras ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Eras:
    mwf_start: date
    daily_start: date

    def of(self, d: date) -> str:
        if d < self.mwf_start:
            return "1 Friday-only"
        return "2 Mon/Wed/Fri" if d < self.daily_start else "3 daily"


def first_continuous(flags: list[tuple[date, bool]]) -> tuple[date, list[date]]:
    """First date from which the flags stay True, ignoring isolated misses (a False between two
    Trues of the same weekday). Returns (start, the isolated misses after start)."""
    misses = [
        i
        for i, (_, ok) in enumerate(flags)
        if not ok and not (0 < i < len(flags) - 1 and flags[i - 1][1] and flags[i + 1][1])
    ]
    first = (misses[-1] + 1) if misses else 0
    if first >= len(flags):
        raise RuntimeError("no continuous run")
    return flags[first][0], [d for d, ok in flags[first:] if not ok]


# section 1 ---------------------------------------------------------------------------------
def listing_table(sessions: list[date]) -> pl.DataFrame:
    rows = []
    for d in sessions:
        nxt = CAL.next_session(d)
        src0 = source_of(d)
        src1 = "ext" if d < ZERO_START else "m4"
        rows.append(
            {
                "session_date": d,
                "weekday": d.weekday(),
                "excluded": CAL.exclusion_reason(d) is not None,
                "has_0dte": chain(src0, d, d).height > 0,
                "has_1dte": chain(src1, d, nxt).height > 0,
                "next_session": nxt,
            }
        )
    return pl.DataFrame(rows)


# entry-time quotes -----------------------------------------------------------------------------
def window_times(d: date, tenor: str) -> list[datetime]:
    lo, hi = (time.fromisoformat(x) for x in S0["windows"][tenor])
    step = timedelta(minutes=CFG.schedule.cadence_minutes)
    t = ensure_utc(datetime.combine(d, lo, tzinfo=ET))
    end = min(ensure_utc(datetime.combine(d, hi, tzinfo=ET)), CAL.last_new_entry(d))
    out = []
    while t <= end:
        out.append(t)
        t += step
    return out


def quotes_at(recs: pl.DataFrame, symbols: list[str], times: list[datetime]) -> pl.DataFrame:
    grid = pl.DataFrame(
        {
            "symbol": [s for _ in times for s in symbols],
            "t_e": [t + LATENCY for t in times for _ in symbols],
        },
        schema={"symbol": pl.String, "t_e": pl.Datetime("ns", "UTC")},
    ).sort("symbol", "t_e")
    return grid.join_asof(
        recs.rename({"available_at": "rec_at"}),
        left_on="t_e",
        right_on="rec_at",
        by="symbol",
        strategy="backward",
        check_sortedness=False,
    )


def leg_failures(q: dict[str, Any] | None, t_e: datetime) -> list[str]:
    if q is None or q["rec_at"] is None:
        return ["NO_QUOTE"]
    return liquidity_failures(
        Quote(q["bid"], q["ask"], q["bid_sz"], q["ask_sz"], q["rec_at"], q["rejected"]), t_e, CFG
    )


@dataclass(frozen=True)
class ExitInfo:
    stored: bool
    usable: bool
    gap: float | None  # longest minutes without a usable record during the hold


@cache
def usable_times(src: str, d: date, symbol: str) -> tuple[datetime, ...]:
    r = records(src, d).filter(
        (pl.col("symbol") == symbol) & ~pl.col("rejected") & (pl.col("ask") > 0)
    )
    return tuple(r["available_at"].to_list())


def exit_info(symbol: str, entry_src: str, d: date, t_e: datetime, exp: date) -> ExitInfo:
    src = source_of(exp)
    t_x = CAL.forced_exit_time(exp) + LATENCY
    recs = records(src, exp).filter(pl.col("symbol") == symbol)
    if recs.height == 0:
        return ExitInfo(False, False, None)
    last = recs.filter(pl.col("available_at") <= t_x).tail(1)
    usable = bool(
        last.height
        and not last["rejected"][0]
        and (last["ask"][0] or 0) > 0
        and (t_x - last["available_at"][0]) <= timedelta(minutes=MAX_GAP_MIN)
    )
    if exp == d:
        gap = longest_gap_minutes(usable_times(src, d, symbol), t_e, t_x)
    else:
        _, close_d = CAL.open_close(d)
        open_e, _ = CAL.open_close(exp)
        gap = max(
            longest_gap_minutes(usable_times(entry_src, d, symbol), t_e, close_d),
            longest_gap_minutes(usable_times(src, exp, symbol), open_e, t_x),
        )
    return ExitInfo(True, usable, gap)


def picks_for_session(d: date, tenor: str) -> list[dict[str, Any]]:
    if tenor == "0dte":
        src, exp = source_of(d), d
    else:
        src, exp = ("ext" if d < ZERO_START else "m4"), CAL.next_session(d)
    ch = chain(src, d, exp)
    if ch.height == 0:
        return []
    times = window_times(d, tenor)
    if not times:
        return [{"session_date": d, "tenor": tenor, "status": "NO_WINDOW"}]
    if exp > DEV_END:
        return [{"session_date": d, "tenor": tenor, "status": "LABEL_CROSSES_BLOCK"}]
    if CAL.exclusion_reason(exp) is not None:
        return [{"session_date": d, "tenor": tenor, "status": "EXIT_SESSION_EXCLUDED"}]
    q = quotes_at(records(src, d), ch["raw_symbol"].to_list(), times)
    meta = {r["raw_symbol"]: r for r in ch.iter_rows(named=True)}
    out = []
    for (t_e,), grp in q.group_by(["t_e"], maintain_order=True):
        by_right: dict[str, dict[float, LegQuote]] = {"C": {}, "P": {}}
        raw: dict[tuple[str, float], dict[str, Any]] = {}
        for row in grp.iter_rows(named=True):
            m = meta[row["symbol"]]
            if m["available_at"] > t_e:
                continue  # not yet known at T_e
            ok = (
                row["rec_at"] is not None and not row["rejected"] and t_e - row["rec_at"] <= MAX_AGE
            )
            by_right[m["right"]][m["strike"]] = LegQuote(m["strike"], row["bid"], row["ask"], ok)
            raw[(m["right"], m["strike"])] = {**row, "symbol": row["symbol"]}
        holes = {
            r: grid_holes([k for k in by_right[r] if abs(k - round(k)) < GRID_TOL]) for r in "CP"
        }
        rules = [("P", x) for x in S0["put_x"]] + [("C", x) for x in S0["call_x"]]
        for right, x in rules:
            p = credit_pick(by_right[right], right, x, S0["width"])
            row_out: dict[str, Any] = {
                "session_date": d,
                "tenor": tenor,
                "t_e": t_e,
                "right": right,
                "x": x,
                "status": p.status,
                "beyond": p.beyond,
                "pairs": p.pairs,
                "short": p.short,
                "long": p.long,
                "hole_near": p.short is not None
                and any(
                    min(p.short, p.long or p.short) - NEAR
                    <= h
                    <= max(p.short, p.long or p.short) + NEAR
                    for h in holes[right]
                ),
                "n_strikes": len(by_right[right]),
            }
            if p.short is not None and p.long is not None:
                s_q, l_q = raw[(right, p.short)], raw[(right, p.long)]
                sf, lf = leg_failures(s_q, t_e), leg_failures(l_q, t_e)
                se = exit_info(s_q["symbol"], src, d, t_e, exp)
                le = exit_info(l_q["symbol"], src, d, t_e, exp)
                row_out |= {
                    "short_fail": ",".join(sf),
                    "long_fail": ",".join(lf),
                    "exit_stored": se.stored and le.stored,
                    "exit_usable": se.usable and le.usable,
                    "max_gap": None if se.gap is None or le.gap is None else max(se.gap, le.gap),
                }
            out.append(row_out)
    return out


# section 2 ---------------------------------------------------------------------------------
def expiry_quotes(d: date) -> dict[str, Any] | None:
    src = source_of(d)
    ch = chain(src, d, d)
    if ch.height == 0 or CAL.exclusion_reason(d) is not None:
        return None
    recs = records(src, d).filter(pl.col("symbol").is_in(ch["raw_symbol"].to_list()))
    t_x = CAL.forced_exit_time(d) + LATENCY
    q = quotes_at(recs, ch["raw_symbol"].to_list(), [CAL.forced_exit_time(d)])
    fresh = (t_x - pl.col("rec_at")) <= timedelta(minutes=MAX_GAP_MIN)
    usable = q.select(
        n=pl.len(),
        ask_ok=(pl.col("rec_at").is_not_null() & ~pl.col("rejected") & (pl.col("ask") > 0)
                & fresh).sum(),
        bid_pos=(pl.col("rec_at").is_not_null() & ~pl.col("rejected") & (pl.col("bid") > 0)
                 & fresh).sum(),
    ).row(0, named=True)  # fmt: skip
    _, close = CAL.open_close(d)
    last = recs.filter(pl.col("available_at") <= close)["available_at"].max()
    return {
        "session_date": d,
        "early_close": CAL.is_early_close(d),
        "n": usable["n"],
        "ask_ok": usable["ask_ok"],
        "bid_pos": usable["bid_pos"],
        "last_rth_record": last,  # datetime or None
        "reaches_exit": isinstance(last, datetime) and last >= t_x - LATENCY,
    }


# grid ------------------------------------------------------------------------------------------
def ext_bands() -> dict[date, list[int]]:
    man = pl.read_parquet(CLEAN / "ingest_manifest.parquet").filter(pl.col("folder") == "ohlcv-1d")
    bars = pl.read_parquet(ROOT / man["parquet_path"][0])
    out = {}
    for ts, lo, hi in zip(bars["ts_event"], bars["low"], bars["high"], strict=True):
        d = datetime.fromtimestamp(int(ts) / 1e9, tz=UTC).date()
        out[d] = strike_band(lo / 1e9, hi / 1e9, BAND_PAD)
    return out


def grid_rows(sessions: Iterable[date]) -> list[dict[str, Any]]:
    bands = ext_bands()
    rows = []
    for d in sessions:
        src = source_of(d)
        for exp in sorted({d, CAL.next_session(d)} if src == "ext" else {d}):
            ch = chain(src, d, exp)
            if ch.height == 0:
                continue
            for right in "CP":
                ks = sorted(ch.filter(pl.col("right") == right)["strike"].to_list())
                whole = [k for k in ks if abs(k - round(k)) < GRID_TOL]
                band = bands.get(d)
                rows.append(
                    {
                        "session_date": d,
                        "tenor": "0dte" if exp == d else "1dte",
                        "right": right,
                        "n_listed": len(ks),
                        "n_off_dollar": len(ks) - len(whole),
                        "n_holes": len(grid_holes(whole)),
                        "n_band": len(band) if band and src == "ext" else None,
                    }
                )
    return rows


# degraded days ----------------------------------------------------------------------------------
def minute_profile(d: date) -> dict[str, Any]:
    src = source_of(d)
    recs = records(src, d)
    open_, close = CAL.open_close(d)
    rth = recs.filter((pl.col("available_at") > open_) & (pl.col("available_at") <= close))
    per_min = rth.group_by("available_at").agg(n=pl.len(), n_ok=(~pl.col("rejected")).sum())
    n_min = int((close - open_).total_seconds() // 60)
    contracts = rth["symbol"].n_unique()
    full = per_min.filter(pl.col("n_ok") >= 0.9 * contracts) if contracts else per_min.head(0)
    stamps = sorted(per_min["available_at"].to_list())
    gaps = []
    prev = open_
    for t in [*stamps, close + timedelta(minutes=1)]:
        if (t - prev) > timedelta(minutes=1, seconds=30):
            gaps.append((prev, t))
        prev = t
    log = pl.read_parquet(CLEAN / "dq_log.parquet").filter(
        (pl.col("source") == src) & (pl.col("session_date") == d)
    )
    return {
        "session_date": d,
        "contracts_defined": chain(src, d, d).height
        + (chain(src, d, CAL.next_session(d)).height if src == "ext" else 0),
        "contracts_quoted": contracts,
        "rth_minutes": n_min,
        "minutes_with_records": per_min.height,
        "minutes_90pct": full.height,
        "n_raw": int(log["n_raw"].sum()) if log.height else 0,
        "n_rejected": int(log["n_rejected"].sum()) if log.height else 0,
        "gaps": gaps,
        "spread_p50": rth.filter(~pl.col("rejected") & (pl.col("bid") >= CFG.liquidity.min_bid))
        .select((pl.col("ask") - pl.col("bid")).median())
        .item(),
    }


# report helpers ----------------------------------------------------------------------------------
def pct(a: float, b: float) -> str:
    return f"{a / b:.2%}" if b else "n/a"


def et(t: datetime | None) -> str:
    return "-" if t is None else t.astimezone(ET).strftime("%H:%M")


def code_commit() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "src", "scripts", "configs"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:  # noqa: PLR0912, PLR0915 (linear report)
    CHAINS.update(load_chains())
    sessions = all_sessions()
    lst = listing_table(sessions)
    wd_flags: dict[int, list[tuple[date, bool]]] = defaultdict(list)
    for r in lst.iter_rows(named=True):
        wd_flags[r["weekday"]].append((r["session_date"], r["has_0dte"]))
    starts = {wd: first_continuous(wd_flags[wd]) for wd in range(5)}
    mwf = max(starts[0][0], starts[2][0])
    daily = max(starts[1][0], starts[3][0])
    isolated = sorted({d for wd in (0, 1, 2, 3) for d in starts[wd][1]})
    eras = Eras(mwf, daily)
    lst = lst.with_columns(era=pl.col("session_date").map_elements(eras.of, return_dtype=pl.String))
    print(f"eras: MWF from {mwf}, daily from {daily}", flush=True)

    # picks
    picks: list[dict[str, Any]] = []
    for i, r in enumerate(lst.iter_rows(named=True), 1):
        d = r["session_date"]
        if r["excluded"]:
            continue
        if r["has_0dte"]:
            picks += picks_for_session(d, "0dte")
        if r["has_1dte"]:
            picks += picks_for_session(d, "1dte")
        if i % 100 == 0:
            print(f"picks {i}/{lst.height}", flush=True)
            records.cache_clear()
            usable_times.cache_clear()
    pk = pl.DataFrame(picks, infer_schema_length=None).with_columns(
        era=pl.col("session_date").map_elements(eras.of, return_dtype=pl.String)
    )
    pk.write_parquet(CLEAN / "coverage_picks.parquet")
    exq = pl.DataFrame(
        [x for d in sessions if (x := expiry_quotes(d)) is not None], infer_schema_length=None
    ).with_columns(era=pl.col("session_date").map_elements(eras.of, return_dtype=pl.String))
    records.cache_clear()
    grid = pl.DataFrame(grid_rows(sessions), infer_schema_length=None).with_columns(
        era=pl.col("session_date").map_elements(eras.of, return_dtype=pl.String),
        month=pl.col("session_date").dt.strftime("%Y-%m"),
    )
    log = pl.read_parquet(CLEAN / "dq_log.parquet").filter(pl.col("session_date") <= DEV_END)
    if pk["session_date"].max() > DEV_END or exq["session_date"].max() > DEV_END:  # type: ignore[operator]
        raise RuntimeError("holdout session in report data")

    out: list[str] = [
        "# M19T Step 0: data coverage (ADR-0013, PROPOSED)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m19t_coverage.py`, code "
        f"{code_commit()[:12]}. Development sessions {sessions[0]} → {sessions[-1]} only. "
        f"Sessions after {DEV_END} (ADR-0011 holdout) were stored and cleaned "
        "(`scripts/m19t_build_data.py`) and are not read here (the loader refuses them).",
        "",
        "**Data only.** Entry-time quotes and quote availability. No exit price, P&L or "
        "outcome is computed. No trial is registered (n_trials stays 38).",
        "",
        "Sources: `0dte` = Step-0 expiry-day contracts (sessions from 2023-03-28); `ext` = Step-0 "
        "D2 extension (contracts expiring D and D+1, 2020-01-02 → 2023-03-27); `m4` = the M4 "
        "1DTE store (contracts expiring D+1, used for 1DTE entries from 2023-03-28).",
        "",
    ]

    # 1. sessions per era / weekday
    out += [
        "## 1. Sessions per era and weekday",
        "",
        f"Eras are inferred from the listings: Mon and Wed expirations are continuous from "
        f"**{mwf}**, Tue and Thu from **{daily}**. Isolated sessions inside a run with no listed "
        f"whole-dollar contract expiring that day: {', '.join(map(str, isolated)) or 'none'} "
        "(see §5). A session counts for 0DTE if a standard "
        "contract expiring that day is listed, and for 1DTE if one expiring on the next session "
        "is listed. Excluded sessions (ADR-0006) are counted separately.",
        "",
        "| era | weekday | sessions | excluded | with 0DTE expiry | with next-session expiry |",
        "|---|---|---|---|---|---|",
    ]
    t1 = (
        lst.group_by("era", "weekday")
        .agg(
            n=pl.len(),
            ex=pl.col("excluded").sum(),
            z=(pl.col("has_0dte") & ~pl.col("excluded")).sum(),
            o=(pl.col("has_1dte") & ~pl.col("excluded")).sum(),
        )
        .sort("era", "weekday")
    )
    for r in t1.iter_rows(named=True):
        out.append(
            f"| {r['era']} | {WD[r['weekday']]} | {r['n']} | {r['ex']} | {r['z']} | {r['o']} |"
        )
    tot = lst.group_by("era").agg(
        n=pl.len(), z=(pl.col("has_0dte") & ~pl.col("excluded")).sum(),
        o=(pl.col("has_1dte") & ~pl.col("excluded")).sum(),
    ).sort("era")  # fmt: skip
    out += ["", "| era | sessions | 0DTE sessions | 1DTE entry sessions |", "|---|---|---|---|"]
    for r in tot.iter_rows(named=True):
        out.append(f"| {r['era']} | {r['n']} | {r['z']} | {r['o']} |")
    n_since = lst.filter((pl.col("session_date") >= date(2023, 1, 1)) & ~pl.col("excluded"))
    out += [
        f"| all | {lst.height} | {int(tot['z'].sum())} | {int(tot['o'].sum())} |",
        "",
        f"Sessions from 2023 on with a 0DTE expiry: {int(n_since['has_0dte'].sum())}; with a "
        f"next-session expiry: {int(n_since['has_1dte'].sum())} (D4 guard: ≥ 150). "
        "Friday→Monday and pre-holiday 1DTE entries are counted in the 1DTE column; D4 reports "
        "them as descriptive rows only.",
        "",
    ]

    # 2. expiry-day quotes at the forced exit
    out += [
        "## 2. Expiry-day quotes at the forced exit (15:50 ET; close - 10 min on early closes)",
        "",
        f"Every standard contract expiring that day in the stored band. *Ask usable*: the latest "
        f"record at exit + latency ({CFG.fills.latency_s} s) is not rejected, has ask > 0 and is "
        f"at most {MAX_GAP_MIN:.0f} min old (D1.c; a missing ask → UNRESOLVED_DATA). "
        "*Reaches exit*: the contract file has records at or after the exit time.",
        "",
        "| era | expiry sessions | early closes | contractsxsessions | ask usable | bid > 0 "
        "| sessions reaching exit | worst session (ask usable) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    exq = exq.with_columns(share=pl.col("ask_ok") / pl.col("n"))
    for (era,), g in exq.group_by(["era"], maintain_order=True):
        worst = g.sort("share").row(0, named=True)
        out.append(
            f"| {era} | {g.height} | {int(g['early_close'].sum())} | {int(g['n'].sum()):,} "
            f"| {pct(int(g['ask_ok'].sum()), int(g['n'].sum()))} "
            f"| {pct(int(g['bid_pos'].sum()), int(g['n'].sum()))} "
            f"| {int(g['reaches_exit'].sum())}/{g.height} | {worst['session_date']} "
            f"{worst['share']:.1%} |"
        )
    low = exq.filter(pl.col("share") < LOW_SHARE).sort("session_date")
    out += [
        "",
        f"Sessions with ask usable for < 95% of stored contracts: {low.height}"
        + (": " + ", ".join(f"{r['session_date']} ({r['share']:.0%})"
                            for r in low.head(LIST_MAX).iter_rows(named=True))
           if low.height else "")
        + ("…" if low.height > LIST_MAX else "")
        + ".",
        "",
    ]  # fmt: skip

    # 3. strike coverage for the credit-fraction rule
    sel = pk.filter(pl.col("status").is_in([OK, NO_QUALIFYING, AT_BAND_EDGE]))
    other = pk.filter(~pl.col("status").is_in([OK, NO_QUALIFYING, AT_BAND_EDGE]))
    out += [
        "## 3. Strike coverage for the credit-fraction rule (D1.a)",
        "",
        f"At every entry timestamp T in the cell windows (0DTE {'-'.join(S0['windows']['0dte'])}, "
        f"1DTE {'-'.join(S0['windows']['1dte'])} ET, every {CFG.schedule.cadence_minutes} min, "
        f"T_e = T + {CFG.fills.latency_s} s): short = furthest-OTM strike with short bid - long "
        f"ask ≥ X x ${S0['width']:.0f}, long = short ∓ ${S0['width']:.0f}, using only quotes in "
        f"force at T_e (not rejected, ≤ {CFG.liquidity.max_quote_age_s} s old). Puts at X = "
        f"{', '.join(map(str, S0['put_x']))}; calls at X = {', '.join(map(str, S0['call_x']))} "
        "(condor call side).",
        "",
        "- **OK**: a qualifying pair exists and stored strikes lie beyond its long leg.",
        "- **AT_BAND_EDGE**: the long leg is the outermost stored strike. A further pair outside "
        "the download band cannot be ruled out (coverage failure).",
        "- **NO_QUALIFYING**: no pair reaches X (D1.a NO_TRADE).",
        "- *beyond p5*: 5th percentile of stored strikes beyond the long leg (margin to the band "
        "edge).",
        "- *both legs pass §4.9*: `liquidity_failures` (spread, min bid "
        f"${CFG.liquidity.min_bid:.2f}, size, freshness) on both legs as ADR-0013 D1.b requires.",
        "- *exit usable*: both legs have a usable ask at the expiry-day exit (as §2). *gap > "
        f"{MAX_GAP_MIN:.0f} min*: a leg has no usable record for longer than that during the "
        "hold (RTH only; the overnight close is not a gap).",
        "",
        "| tenor | side | X | era | entries | OK | AT_BAND_EDGE | NO_QUALIFYING | beyond p5 "
        "| both legs pass §4.9 | exit legs stored | exit usable | gap > 5 min |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    t3 = (
        sel.group_by("tenor", "right", "x", "era")
        .agg(
            n=pl.len(),
            ok=(pl.col("status") == OK).sum(),
            edge=(pl.col("status") == AT_BAND_EDGE).sum(),
            noq=(pl.col("status") == NO_QUALIFYING).sum(),
            b5=pl.col("beyond").filter(pl.col("status") != NO_QUALIFYING).quantile(0.05),
            picked=(pl.col("status") != NO_QUALIFYING).sum(),
            gates=((pl.col("short_fail") == "") & (pl.col("long_fail") == "")).sum(),
            stored=pl.col("exit_stored").sum(),
            exit_ok=pl.col("exit_usable").sum(),
            gap=(pl.col("max_gap") > MAX_GAP_MIN).sum(),
        )
        .sort("tenor", "right", "x", "era")
    )
    for r in t3.iter_rows(named=True):
        out.append(
            f"| {r['tenor']} | {r['right']} | {r['x']:.2f} | {r['era']} | {r['n']:,} "
            f"| {pct(r['ok'], r['n'])} | {pct(r['edge'], r['n'])} | {pct(r['noq'], r['n'])} "
            f"| {r['b5'] if r['b5'] is not None else '-'} | {pct(r['gates'], r['picked'])} "
            f"| {pct(r['stored'], r['picked'])} | {pct(r['exit_ok'], r['picked'])} "
            f"| {pct(r['gap'], r['picked'])} |"
        )
    fails = (
        sel.filter(pl.col("status") != NO_QUALIFYING)
        .select("tenor", "right", "x", leg=pl.lit("short"), f=pl.col("short_fail"))
        .vstack(
            sel.filter(pl.col("status") != NO_QUALIFYING).select(
                "tenor", "right", "x", leg=pl.lit("long"), f=pl.col("long_fail")
            )
        )
        .with_columns(f=pl.col("f").str.split(","))
        .explode("f")
        .filter(pl.col("f") != "")
        .group_by("tenor", "right", "x", "leg", "f")
        .agg(n=pl.len())
        .sort("tenor", "right", "x", "leg", "n", descending=[False, False, False, False, True])
    )
    picked_n = (
        sel.filter(pl.col("status") != NO_QUALIFYING)
        .group_by("tenor", "right", "x")
        .agg(n=pl.len())
    )
    pn = {(r["tenor"], r["right"], r["x"]): r["n"] for r in picked_n.iter_rows(named=True)}
    out += [
        "",
        "§4.9 failures on the picked legs (share of picked entries; one entry can fail several "
        "checks):",
        "",
        "| tenor | side | X | leg | check | share |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r['tenor']} | {r['right']} | {r['x']:.2f} | {r['leg']} | {r['f']} "
            f"| {pct(r['n'], pn[(r['tenor'], r['right'], r['x'])])} |"
            for r in fails.iter_rows(named=True)
        ],
        "",
    ]
    sess = (
        sel.group_by("tenor", "right", "x", "era", "session_date")
        .agg(any_ok=(pl.col("status") == OK).any())
        .group_by("tenor", "right", "x", "era")
        .agg(n=pl.len(), ok=pl.col("any_ok").sum())
        .sort("tenor", "right", "x", "era")
    )
    out += [
        "Sessions with at least one OK pick in the window:",
        "",
        "| tenor | side | X | era | sessions | with an OK pick |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r['tenor']} | {r['right']} | {r['x']:.2f} | {r['era']} | {r['n']} "
            f"| {r['ok']} ({pct(r['ok'], r['n'])}) |"
            for r in sess.iter_rows(named=True)
        ],
        "",
        "Entries not evaluated (counted, never filled):",
        "",
        "| tenor | status | sessions |",
        "|---|---|---|",
        *[
            f"| {r['tenor']} | {r['status']} | {r['n']} |"
            for r in other.group_by("tenor", "status").agg(n=pl.len()).sort("tenor", "status")
            .iter_rows(named=True)
        ],
        "",
    ]  # fmt: skip

    picked = sel.filter(pl.col("status") != NO_QUALIFYING).with_columns(
        month=pl.col("session_date").dt.strftime("%Y-%m"),
        off_dollar=((pl.col("short") - pl.col("short").round(0)).abs() > GRID_TOL)
        | ((pl.col("long") - pl.col("long").round(0)).abs() > GRID_TOL),
    )
    miss = (
        picked.filter(~pl.col("exit_stored"))
        .group_by("tenor", "month", "off_dollar")
        .agg(n=pl.len(), sessions=pl.col("session_date").n_unique())
        .sort("tenor", "month", "off_dollar")
    )
    near = (
        picked.group_by("tenor", "era")
        .agg(n=pl.len(), h=pl.col("hole_near").sum())
        .sort("tenor", "era")
    )
    out += [
        "Picked entries whose legs are not stored on the expiry day (all rules pooled; "
        "*off-dollar* = a leg on an OCC-adjusted strike, which the Step-0 download did not "
        "request):",
        "",
        "| tenor | month | off-dollar leg | entries | sessions |",
        "|---|---|---|---|---|",
        *[
            f"| {r['tenor']} | {r['month']} | {r['off_dollar']} | {r['n']} | {r['sessions']} |"
            for r in miss.iter_rows(named=True)
        ],
        "",
        f"Picked entries with a $1 grid hole within {NEAR} strikes of the pair (the rule skips a "
        "pair whose long strike is not listed):",
        "",
        "| tenor | era | picked entries | hole near the pair |",
        "|---|---|---|---|",
        *[
            f"| {r['tenor']} | {r['era']} | {r['n']:,} | {r['h']} ({pct(r['h'], r['n'])}) |"
            for r in near.iter_rows(named=True)
        ],
        "",
    ]

    # 4. rejection rates
    out += [
        "## 4. Cleaning: rejection rates (M4 rules, DQ rules v2)",
        "",
        "Raw = cleaned + rejected held for every file, holdout included (asserted in "
        "`scripts/m19t_build_data.py`). Every rejected record is stored with its reasons in "
        f"`{S0['clean_dir']}/rejected/`.",
        "",
        "| source | year | sessions | raw records | rejected | rate |",
        "|---|---|---|---|---|---|",
    ]
    ry = (
        log.group_by("source", year=pl.col("session_date").dt.year())
        .agg(s=pl.len(), raw=pl.col("n_raw").sum(), rej=pl.col("n_rejected").sum())
        .sort("source", "year", descending=[True, False])
    )
    for r in ry.iter_rows(named=True):
        out.append(
            f"| {r['source']} | {r['year']} | {r['s']} | {r['raw']:,} | {r['rej']:,} "
            f"| {pct(r['rej'], r['raw'])} |"
        )

    def tally(col: str) -> dict[tuple[str, str], int]:
        out: dict[tuple[str, str], int] = defaultdict(int)
        for src, s in zip(log["source"], log[col], strict=True):
            for part in filter(None, (s or "").split(";")):
                k, v = part.split("=")
                out[(src, k)] += int(v)
        return out

    raw_by = {r["source"]: r["raw"] for r in log.group_by("source").agg(raw=pl.col("n_raw").sum())
              .iter_rows(named=True)}  # fmt: skip
    out += ["", "| source | rejection reason | records | share of raw |", "|---|---|---|---|"]
    for (src, k), v in sorted(tally("reasons").items(), key=lambda kv: (kv[0][0], -kv[1])):
        out.append(f"| {src} | {k} | {v:,} | {pct(v, raw_by[src])} |")
    out += ["", "| source | flag (kept) | records | share of raw |", "|---|---|---|---|"]
    for (src, k), v in sorted(tally("flags").items(), key=lambda kv: (kv[0][0], -kv[1])):
        out.append(f"| {src} | {k} | {v:,} | {pct(v, raw_by[src])} |")
    out.append("")

    # 5. strike grid
    g = grid.with_columns(has_hole=pl.col("n_holes") > 0)
    out += [
        "## 5. Strike grid",
        "",
        "Only whole-dollar strikes were requested (the M4 band rule), so half-dollar or OCC-"
        "adjusted strikes are visible only where they were listed under a requested symbol. "
        "*Holes*: whole-dollar strikes missing between the lowest and highest listed strike of an "
        "expiry. *Listed / requested*: share of the requested band that resolved to a listed "
        "contract (extension only; the band comes from the Nasdaq-venue daily range).",
        "",
        "| era | tenor | expiryxside rows | listed strikes (median) | rows with holes "
        "| holes (mean) | listed / requested |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in (
        g.group_by("era", "tenor")
        .agg(
            n=pl.len(),
            med=pl.col("n_listed").median(),
            h=pl.col("has_hole").sum(),
            hm=pl.col("n_holes").mean(),
            listed_b=pl.col("n_listed").filter(pl.col("n_band").is_not_null()).sum(),
            band=pl.col("n_band").sum(),
        )
        .sort("era", "tenor")
        .iter_rows(named=True)
    ):
        lr = pct(r["listed_b"], r["band"]) if r["band"] else "-"
        out.append(
            f"| {r['era']} | {r['tenor']} | {r['n']:,} | {r['med']:.0f} | {r['h']} "
            f"| {r['hm']:.2f} | {lr} |"
        )
    hole_months = g.filter(pl.col("has_hole")).group_by("month").agg(n=pl.len()).sort("month")
    out += [
        "",
        "Months with holes (expiryxside rows): "
        + (", ".join(f"{r['month']} ({r['n']})" for r in hole_months.iter_rows(named=True))
           or "none")
        + ".",
        "",
    ]  # fmt: skip

    # 6. degraded days
    out += [
        "## 6. Databento-degraded days",
        "",
        f"Each day vs {S0['degraded_neighbours']} sessions either side in the same store. "
        "*90% minutes*: RTH minutes in which ≥ 90% of the day's quoted contracts have a "
        "non-rejected record. Gaps are RTH stretches with no record for any contract.",
        "",
        "| session | role | contracts defined | quoted | minutes with records | 90% minutes "
        "| raw | rejected | median spread (bid >= min bid) | gaps (ET) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    ext_sessions = [d for d in sessions if d < ZERO_START]
    for dd in S0["degraded_days"]:
        day = date.fromisoformat(dd)
        i = ext_sessions.index(day)
        n = S0["degraded_neighbours"]
        for d in ext_sessions[max(i - n, 0) : i + n + 1]:
            p = minute_profile(d)
            gaps = "; ".join(f"{et(a)}→{et(b)}" for a, b in p["gaps"]) or "none"
            out.append(
                f"| {d} | {'**degraded**' if d == day else 'neighbour'} "
                f"| {p['contracts_defined']} | {p['contracts_quoted']} "
                f"| {p['minutes_with_records']}/{p['rth_minutes']} | {p['minutes_90pct']} "
                f"| {p['n_raw']:,} | {p['n_rejected']:,} | {p['spread_p50'] or 0:.3f} | {gaps} |"
            )
        dpk = pk.filter(pl.col("session_date") == day)
        if dpk.height:
            st = (
                dpk.group_by("tenor", "right", "x", "status")
                .agg(n=pl.len())
                .sort("tenor", "right", "x", "status")
            )
            out.append(
                f"| {day} picks | | "
                + ", ".join(f"{r['tenor']} {r['right']} {r['x']:.2f} {r['status']} {r['n']}"
                            for r in st.iter_rows(named=True))
                + " | | | | | | | |"
            )  # fmt: skip
        records.cache_clear()
        out.append("| | | | | | | | | | |")
    out.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
