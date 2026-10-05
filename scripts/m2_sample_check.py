"""Run the M2 sample-week checks C1-C8 on downloaded Databento files; write a markdown report.

Input:  data/raw/databento/m2_sample/ (from scripts/m2_fetch_sample.py)
Output: reports/m2/sample_week.md

Check logic lives in scripts/m2_checks.py (unit-tested). This file only adapts vendor data.
Prices are compared as Databento fixed-point integers (1e-9 units) to avoid float rounding.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import databento as db
import exchange_calendars as xcals
import numpy as np
import numpy.typing as npt
import pandas as pd

from m2_checks import (
    ET,
    Quote,
    bar_convention_by_alignment,
    interval_quote_semantics_np,
    listing_lead_sessions,
    missing_one_dte_sessions,
    quote_validity,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "databento" / "m2_sample"
REPORT = ROOT / "reports" / "m2" / "sample_week.md"

WEEK = [date(2025, 3, 10) + timedelta(days=i) for i in range(5)]
ATM_HALF_WIDTH = 5  # strikes either side of ATM used for C3/C6/C8
UNDEF_PRICE = np.iinfo(np.int64).max
STAT_OPEN_INTEREST = 9  # databento StatType.OPEN_INTEREST
NS = 1_000_000_000
RTH_OPEN, RTH_CLOSE = time(9, 30), time(16, 0)
# Spec §4.9 liquidity gates (configs/phase1.yaml liquidity.*); read from config in M4.
MAX_SPREAD_ABS, MAX_SPREAD_PCT, MIN_BID = 0.05, 0.05, 0.20


def load_df(schema: str, dataset: str, day: date, **kw: Any) -> pd.DataFrame:
    path = RAW / schema / f"{dataset}_{day.isoformat()}.dbn.zst"
    df: pd.DataFrame = db.DBNStore.from_file(path).to_df(**kw)
    return df


def to_et(index: pd.Index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index).tz_convert(ET)


def fixed_to_float(a: npt.NDArray[np.int64]) -> npt.NDArray[np.float64]:
    out = a.astype(np.float64)
    out[a == UNDEF_PRICE] = np.nan
    return out


def atm_contracts(day: date, expiry: date, defs: pd.DataFrame, spot: float) -> pd.DataFrame:
    """D+1 contracts within ATM ± ATM_HALF_WIDTH listed strikes, both rights."""
    d = defs[defs["expiration"].dt.date == expiry].drop_duplicates("raw_symbol")
    strikes = np.sort(d["strike_price"].unique())
    atm_i = int(np.argmin(np.abs(strikes - spot)))
    lo, hi = max(atm_i - ATM_HALF_WIDTH, 0), atm_i + ATM_HALF_WIDTH + 1
    chosen = set(strikes[lo:hi])
    out: pd.DataFrame = d[d["strike_price"].isin(chosen)][
        ["raw_symbol", "instrument_id", "strike_price"]
    ]
    return out


def rth_open_price(day: date) -> float:
    bars = load_df("ohlcv-1m", "EQUS.MINI", day)
    t = to_et(bars.index)
    first = bars[(t.date == day) & (t.time == RTH_OPEN)]
    return float(first["open"].iloc[0])


def tick_path(day: date) -> Path:
    """Full strike-band tick file if present, else the ATM-only file (M2 option A)."""
    full = RAW / "cmbp-1" / f"OPRA.PILLAR_{day.isoformat()}.dbn.zst"
    return full if full.exists() else RAW / "cmbp-1" / f"OPRA.PILLAR_{day.isoformat()}_atm.dbn.zst"


def c3_day(day: date, sessions: list[date]) -> dict[str, Any]:
    """C3 classification counts for one session's D+1 ATM contracts."""
    i = sessions.index(day)
    expiry = sessions[i + 1]
    spot = rth_open_price(day)
    chosen = atm_contracts(day, expiry, load_df("definition", "OPRA.PILLAR", day), spot)
    ids = np.array(sorted(chosen["instrument_id"]), dtype=np.uint32)

    parts: dict[str, list[npt.NDArray[Any]]] = defaultdict(list)
    scanned = 0
    for chunk in db.DBNStore.from_file(tick_path(day)).to_ndarray(count=5_000_000):
        scanned += len(chunk)
        sel = chunk[np.isin(chunk["instrument_id"], ids)]
        for field in ("ts_recv", "instrument_id", "bid_px_00", "ask_px_00"):
            parts[field].append(sel[field])
    tick = {k: np.concatenate(v) for k, v in parts.items()}

    cbf = load_df("cbbo-1m", "OPRA.PILLAR", day, pretty_ts=False, price_type="fixed")
    cb_ts = np.asarray(cbf.index, dtype=np.int64)
    t_et = pd.to_datetime(cb_ts, utc=True).tz_convert(ET)
    rth_mask = (t_et.time > RTH_OPEN) & (t_et.time <= RTH_CLOSE)
    cbf = cbf[rth_mask]
    cb_ts = cb_ts[rth_mask]

    out: dict[str, Any] = {"at_or_before": 0, "within_next_bucket": 0, "ambiguous": 0, "neither": 0}
    one_sided = 0
    for iid in ids:
        tm = tick["instrument_id"] == iid
        order = np.argsort(tick["ts_recv"][tm], kind="stable")
        t_ts = tick["ts_recv"][tm][order].astype(np.int64)
        t_bid = fixed_to_float(tick["bid_px_00"][tm][order].astype(np.int64))
        t_ask = fixed_to_float(tick["ask_px_00"][tm][order].astype(np.int64))
        bm = (cbf["instrument_id"] == iid).to_numpy()
        b_bid = fixed_to_float(cbf["bid_px_00"].to_numpy()[bm].astype(np.int64))
        b_ask = fixed_to_float(cbf["ask_px_00"].to_numpy()[bm].astype(np.int64))
        one_sided += int(np.sum(np.isnan(b_bid) | np.isnan(b_ask)))
        res = interval_quote_semantics_np(
            (t_ts, t_bid, t_ask), (cb_ts[bm], b_bid, b_ask), bucket_ns=60 * NS
        )
        for k, v in res.items():
            out[k] += v
    buckets = sum(out.values())
    out.update(
        expiry=expiry,
        spot=spot,
        contracts=len(ids),
        scanned=scanned,
        kept=len(tick["ts_recv"]),
        buckets=buckets,
        one_sided=one_sided,
    )
    return out


def main() -> int:  # noqa: PLR0915 (linear report script)
    cal = xcals.get_calendar("XNYS")
    sessions = [s.date() for s in cal.sessions_in_range("2025-02-24", "2025-03-21")]
    lines: list[str] = [
        "# M2 sample-week report (Databento)",
        "",
        f"Generated {datetime.now(ET):%Y-%m-%d %H:%M %Z} by `scripts/m2_sample_check.py`. "
        f"Week {WEEK[0]} → {WEEK[-1]}.",
        "",
    ]

    # ---- C1 / C2 -------------------------------------------------------------------
    lines += [
        "## C1 timestamps/timezone · C2 QQQ 1-min bars",
        "",
        "| session | tz | first RTH bar label (UTC) | RTH bars (start-labelled 09:30-15:59) "
        "| align err start | align err end | n |",
        "|---|---|---|---|---|---|---|",
    ]
    for day in WEEK:
        bars = load_df("ohlcv-1m", "EQUS.MINI", day)
        bbo = load_df("bbo-1m", "EQUS.MINI", day)
        t = to_et(bars.index)
        rth = bars[(t.date == day) & (t.time >= RTH_OPEN) & (t.time < RTH_CLOSE)]
        first_utc = pd.DatetimeIndex(rth.index).min()
        mids_df = bbo.dropna(subset=["bid_px_00", "ask_px_00"])
        mids = {
            ts.to_pydatetime(): (b + a) / 2
            for ts, b, a in zip(
                pd.DatetimeIndex(mids_df.index),
                mids_df["bid_px_00"],
                mids_df["ask_px_00"],
                strict=True,
            )
        }
        closes = {
            ts.to_pydatetime(): c
            for ts, c in zip(pd.DatetimeIndex(rth.index), rth["close"], strict=True)
        }
        err = bar_convention_by_alignment(closes, mids, bar=timedelta(minutes=1))
        lines.append(
            f"| {day} | {pd.DatetimeIndex(bars.index).tz} | {first_utc:%H:%M} | {len(rth)} "
            f"| {err['start']:.4f} | {err['end']:.4f} | {int(err['n'])} |"
        )
    lines += [
        "",
        "Reading: the hypothesis with the far smaller mean |close - quote mid| is the "
        "vendor's bar-label convention. `cbbo-1m`/`bbo-1m` `ts_recv` minute stamps are used "
        "as the quote time.",
        "",
    ]

    # cbbo-1m stamps on minute boundaries?
    stamps = np.concatenate(
        [
            np.asarray(load_df("cbbo-1m", "OPRA.PILLAR", d, pretty_ts=False).index, dtype=np.int64)
            for d in WEEK
        ]
    )
    on_minute = float(np.mean(stamps % (60 * NS) == 0))
    lines += [
        f"`cbbo-1m` records stamped exactly on a minute boundary (whole week): "
        f"{on_minute:.2%} of {len(stamps):,}.",
        "",
    ]

    # ---- C4 / C5 ---------------------------------------------------------------------
    listed: dict[date, set[date]] = {}
    for day in WEEK:
        defs = load_df("definition", "OPRA.PILLAR", day)
        listed[day] = set(defs["expiration"].dt.date)
    missing = missing_one_dte_sessions(WEEK, sessions, listed)
    lines += [
        "## C4 1DTE expiration present every session",
        "",
        f"Sessions checked: {len(WEEK)}. Missing next-session expiry: "
        f"{', '.join(map(str, missing)) or 'none'}.",
        "",
    ]

    first_seen: dict[date, date] = {}
    def_files = sorted((RAW / "definition").glob("OPRA.PILLAR_*.dbn.zst"))
    for f in def_files:
        file_day = date.fromisoformat(f.name.split("_")[1][:10])
        df = db.DBNStore.from_file(f).to_df()
        for exp in set(df["expiration"].dt.date):
            if exp not in first_seen or file_day < first_seen[exp]:
                first_seen[exp] = file_day
    lookback_start = min(date.fromisoformat(f.name.split("_")[1][:10]) for f in def_files)
    lines += [
        "## C5 listing lead time (first appearance in daily definitions)",
        "",
        "| expiration | weekday | first seen | lead (sessions) |",
        "|---|---|---|---|",
    ]
    for exp in sorted(first_seen):
        lead = listing_lead_sessions(first_seen[exp], exp, sessions)
        censored = "≥ " if first_seen[exp] == lookback_start else ""
        lines.append(f"| {exp} | {exp:%a} | {first_seen[exp]} | {censored}{lead} |")
    lines += [
        "",
        f"Lookback starts {lookback_start}; '≥' = already listed on the first lookback "
        "day (lead is censored). Databento OPRA definitions leave `activation` empty, so "
        "first appearance is the only listing evidence here.",
        "",
    ]

    # ---- C6 ------------------------------------------------------------------------
    lines += [
        "## C6 quote validity, D+1 ATM ± 5 strikes, RTH (`cbbo-1m`)",
        "",
        "| session | spot (09:30 open) | quotes | missing side | non-positive | crossed | valid "
        "| spread p50 | p90 | p99 | pass §4.9 gates |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for day in WEEK:
        i = sessions.index(day)
        expiry = sessions[i + 1]
        spot = rth_open_price(day)
        defs = load_df("definition", "OPRA.PILLAR", day)
        chosen = atm_contracts(day, expiry, defs, spot)
        cbd = load_df("cbbo-1m", "OPRA.PILLAR", day)
        t = to_et(cbd.index)
        rth = cbd[
            (t.time > RTH_OPEN)
            & (t.time <= RTH_CLOSE)
            & cbd["instrument_id"].isin(set(chosen["instrument_id"]))
        ]
        quotes = [
            Quote(ts.to_pydatetime(), float(b), float(a))
            for ts, b, a in zip(
                pd.DatetimeIndex(rth.index), rth["bid_px_00"], rth["ask_px_00"], strict=True
            )
        ]
        v = quote_validity(quotes)
        valid = rth.dropna(subset=["bid_px_00", "ask_px_00"])
        valid = valid[(valid["bid_px_00"] > 0) & (valid["ask_px_00"] >= valid["bid_px_00"])]
        spread = valid["ask_px_00"] - valid["bid_px_00"]
        mid = (valid["ask_px_00"] + valid["bid_px_00"]) / 2
        gate = (spread <= np.maximum(MAX_SPREAD_ABS, MAX_SPREAD_PCT * mid)) & (
            valid["bid_px_00"] >= MIN_BID
        )
        q = spread.quantile([0.5, 0.9, 0.99]) if len(spread) else pd.Series([np.nan] * 3)
        lines.append(
            f"| {day} | {spot:.2f} | {v.total} | {v.missing} | {v.nonpositive} | {v.crossed} "
            f"| {v.valid} | {q.iloc[0]:.3f} | {q.iloc[1]:.3f} | {q.iloc[2]:.3f} "
            f"| {gate.mean():.1%} |"
        )
    lines += ["", "Spec §4.9: spread ≤ max($0.05, 5% of mid) and bid ≥ $0.20.", ""]

    # ---- C7 ------------------------------------------------------------------------
    lines += [
        "## C7 open interest timing (`statistics`, stat_type 9)",
        "",
        "| session | OI records | first arrival (ET) | last arrival (ET) | arrivals after 09:30 ET "
        "| instruments with >1 distinct OI value |",
        "|---|---|---|---|---|---|",
    ]
    for day in WEEK:
        stt = load_df("statistics", "OPRA.PILLAR", day)
        oi = stt[stt["stat_type"] == STAT_OPEN_INTEREST]
        t = to_et(oi.index)
        late = int(np.sum(t.time > RTH_OPEN))
        changing = int((oi.groupby("instrument_id")["quantity"].nunique() > 1).sum())
        lines.append(
            f"| {day} | {len(oi)} | {t.min():%H:%M:%S} | {t.max():%H:%M:%S} | {late} | {changing} |"
        )
    lines += [""]

    # ---- C3 / C8 (every day with a complete cmbp-1 file) -----------------------------------
    tick_days = [d for d in WEEK if tick_path(d).exists()]
    classes = ("at_or_before", "within_next_bucket", "ambiguous", "neither")
    grand = dict.fromkeys(classes, 0)
    lines += [
        "## C3 `cbbo-1m` timestamp semantics vs `cmbp-1` ticks",
        "",
        f"Contracts per day: D+1 expiry, ATM ± {ATM_HALF_WIDTH} strikes around the 09:30 open, "
        "calls and puts. Buckets = RTH `cbbo-1m` records for those contracts.",
        "",
        "| session | D+1 | spot | contracts | tick records scanned | kept | buckets "
        "| at_or_before | within_next_bucket | ambiguous | neither | empty side |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for day in tick_days:
        r = c3_day(day, sessions)
        for k in classes:
            grand[k] += r[k]
        lines.append(
            f"| {day} | {r['expiry']} | {r['spot']:.2f} | {r['contracts']} | {r['scanned']:,} "
            f"| {r['kept']:,} | {r['buckets']:,} | {r['at_or_before']:,} "
            f"| {r['within_next_bucket']:,} | {r['ambiguous']:,} | {r['neither']:,} "
            f"| {r['one_sided']} |"
        )
    n_b = sum(grand.values())
    lines += ["", "| all tick days | buckets | share |", "|---|---|---|"]
    for k in classes:
        lines.append(f"| {k} | {grand[k]:,} | {grand[k] / n_b:.2%} |")
    lines += [
        "",
        "`at_or_before` = equals the last tick with ts_recv ≤ the record's ts_recv (point-in-time "
        "safe). `within_next_bucket` = equals the last tick before ts_recv + 1 min (would mean "
        "the record leaks up to one minute of future quotes). `ambiguous` = quote unchanged, "
        "both agree.",
        "",
        "## C8 NBBO consistency (internal: `cbbo-1m` vs minute-end state from `cmbp-1`)",
        "",
        f"Identical bid/ask at the record time: "
        f"{(grand['at_or_before'] + grand['ambiguous']) / n_b:.2%} of {n_b:,} contract-minutes "
        f"over {len(tick_days)} sessions. An independent second-vendor comparison is deferred to "
        "M20 (ADR-0002).",
        "",
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
