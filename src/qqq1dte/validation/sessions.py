"""Session-level data-quality checks (docs/DATA_QUALITY.md) feeding gates 1-2."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.validation.records import standard_contract

NS = 1_000_000_000


def bar_coverage(
    cleaned_bars: pl.DataFrame, cal: TradingCalendar, sessions: list[date]
) -> pl.DataFrame:
    """Received vs expected start-labelled RTH bar labels per session, listing the gaps."""
    rth = cleaned_bars.filter(pl.col("is_rth"))
    have: dict[date, set[datetime]] = {}
    for d, ts in zip(rth["session_date"].to_list(), rth["ts"].to_list(), strict=True):
        have.setdefault(d, set()).add(ts)
    rows = []
    for d in sessions:
        open_, close = cal.open_close(d)
        n = int((close - open_).total_seconds() // 60)
        expected = [open_ + timedelta(minutes=i) for i in range(n)]
        got = have.get(d, set())
        missing = [t for t in expected if t not in got]
        rows.append(
            {
                "session_date": d,
                "expected": n,
                "received": n - len(missing),
                "coverage": (n - len(missing)) / n,
                "missing": missing,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "expected": pl.Int64,
            "received": pl.Int64,
            "coverage": pl.Float64,
            "missing": pl.List(pl.Datetime("us", "UTC")),
        },
    )


def one_dte_presence(
    defs: pl.DataFrame, cal: TradingCalendar, sessions: list[date]
) -> pl.DataFrame:
    """Spec §1.2: is the next-session expiration in the session's definitions?"""
    listed: dict[date, set[date]] = {}
    for d, e in zip(defs["session_date"].to_list(), defs["expiration"].to_list(), strict=True):
        listed.setdefault(d, set()).add(e)
    rows = []
    for d in sessions:
        nxt = cal.next_session(d)
        rows.append(
            {
                "session_date": d,
                "next_session": nxt,
                "listed": cal.resolve_1dte(d, listed.get(d, set())) is not None,
            }
        )
    return pl.DataFrame(
        rows, schema={"session_date": pl.Date, "next_session": pl.Date, "listed": pl.Boolean}
    )


def _valid_quote(bid: pl.Expr, ask: pl.Expr) -> pl.Expr:
    return bid.is_not_null() & ask.is_not_null() & (bid > 0) & (bid <= ask)


def _latest_records(opt_clean: pl.DataFrame, opt_rejected: pl.DataFrame) -> pl.DataFrame:
    """All option records (cleaned and rejected) with a validity flag. A rejected record is a
    real minute without a usable quote, so it must not let an older quote stand in."""
    good = opt_clean.select(
        symbol=pl.col("symbol"),
        available_at=pl.col("available_at"),
        bid=pl.col("bid"),
        ask=pl.col("ask"),
        bid_sz=pl.col("bid_sz").cast(pl.Int64),
        ask_sz=pl.col("ask_sz").cast(pl.Int64),
        valid=_valid_quote(pl.col("bid"), pl.col("ask")),
    )
    bad = opt_rejected.select(
        symbol=pl.col("symbol"),
        available_at=pl.col("ts"),
        bid=pl.lit(None, pl.Float64),
        ask=pl.lit(None, pl.Float64),
        bid_sz=pl.lit(None, pl.Int64),
        ask_sz=pl.lit(None, pl.Int64),
        valid=pl.lit(False),
    )
    return pl.concat([good, bad]).sort(["symbol", "available_at"])


def frozen_rule_table(
    opt_clean: pl.DataFrame,
    opt_rejected: pl.DataFrame,
    und_quotes: pl.DataFrame,
    defs: pl.DataFrame,
    cal: TradingCalendar,
    cfg: Phase1Config,
    sessions: list[date],
) -> pl.DataFrame:
    """One row per (session, prediction timestamp T) with the spec §5 contracts and the quote in
    force for each. Spot = latest valid underlying mid with available_at <= T (age-limited);
    call = lowest D+1 strike >= spot, put = highest D+1 strike <= spot; quote = latest record
    with available_at <= T. `<side>_ok`: two-sided, 0 < bid <= ask, age <= max_quote_age_s,
    and the latest record was not rejected. Only information available at T is used."""
    max_age = timedelta(seconds=cfg.liquidity.max_quote_age_s)
    spot_q = (
        und_quotes.filter(_valid_quote(pl.col("bid"), pl.col("ask")))
        .select(spot_at=pl.col("available_at"), spot=(pl.col("bid") + pl.col("ask")) / 2)
        .sort("spot_at")
    )
    records = _latest_records(opt_clean, opt_rejected)
    valid_defs = defs.filter(standard_contract(cfg))
    frames = []
    for d in sessions:
        nxt = cal.next_session(d)
        chain = valid_defs.filter((pl.col("session_date") == d) & (pl.col("expiration") == nxt))
        sides = {}
        for right in ("C", "P"):
            sub = chain.filter(pl.col("right") == right)
            sides[right] = sorted(
                zip(sub["strike"].to_list(), sub["raw_symbol"].to_list(), strict=True)
            )
        call_k = [c[0] for c in sides["C"]]
        put_k = [p[0] for p in sides["P"]]
        ts_df = pl.DataFrame(
            {"T": cal.prediction_timestamps(d)}, schema={"T": pl.Datetime("ns", "UTC")}
        ).join_asof(spot_q, left_on="T", right_on="spot_at", strategy="backward")
        rows = []
        for t, s, at in zip(ts_df["T"], ts_df["spot"], ts_df["spot_at"], strict=True):
            fresh = s is not None and at is not None and t - at <= max_age
            ci = bisect_left(call_k, s) if fresh else len(call_k)
            pi = bisect_right(put_k, s) - 1 if fresh else -1
            rows.append(
                {
                    "session_date": d,
                    "T": t,
                    "spot": s if fresh else None,
                    "call": sides["C"][ci][1] if ci < len(call_k) else None,
                    "put": sides["P"][pi][1] if pi >= 0 else None,
                }
            )
        w = pl.DataFrame(
            rows,
            schema={
                "session_date": pl.Date,
                "T": pl.Datetime("ns", "UTC"),
                "spot": pl.Float64,
                "call": pl.String,
                "put": pl.String,
            },
        )
        for side in ("call", "put"):
            j = (
                w.select("T", pl.col(side).alias("symbol"))
                .with_row_index("_i")
                .sort("T")
                # `records` is sorted by (symbol, available_at) in _latest_records and `T` is
                # sorted here; polars cannot verify per-group order itself.
                .join_asof(
                    records,
                    left_on="T",
                    right_on="available_at",
                    by="symbol",
                    strategy="backward",
                    check_sortedness=False,
                )
                .sort("_i")
            )
            age = (j["T"] - j["available_at"]).dt.total_seconds()
            ok = (
                j["valid"].fill_null(False)
                & (age <= cfg.liquidity.max_quote_age_s).fill_null(False)
                & j["symbol"].is_not_null()
            )
            w = w.with_columns(
                pl.Series(f"{side}_bid", j["bid"]),
                pl.Series(f"{side}_ask", j["ask"]),
                pl.Series(f"{side}_bid_sz", j["bid_sz"]),
                pl.Series(f"{side}_ask_sz", j["ask_sz"]),
                pl.Series(f"{side}_age_s", age),
                pl.Series(f"{side}_ok", ok),
            )
        frames.append(w)
    return pl.concat(frames) if frames else pl.DataFrame()


def chain_coverage(
    opt_clean: pl.DataFrame,
    opt_rejected: pl.DataFrame,
    und_quotes: pl.DataFrame,
    defs: pl.DataFrame,
    cal: TradingCalendar,
    cfg: Phase1Config,
    sessions: list[date],
) -> pl.DataFrame:
    """Share of prediction timestamps with a valid spec §5 call AND put quote (gate 1)."""
    t = frozen_rule_table(opt_clean, opt_rejected, und_quotes, defs, cal, cfg, sessions)
    has_spot = pl.col("spot").is_not_null()
    return (
        t.group_by("session_date", maintain_order=True)
        .agg(
            n_timestamps=pl.len(),
            n_valid=(has_spot & pl.col("call_ok") & pl.col("put_ok")).sum(),
            no_spot=(~has_spot).sum(),
            call_invalid=(has_spot & ~pl.col("call_ok")).sum(),
            put_invalid=(has_spot & ~pl.col("put_ok")).sum(),
        )
        .with_columns(share=pl.col("n_valid") / pl.col("n_timestamps"))
    )


def _occ_parts(sym: pl.Expr) -> list[pl.Expr]:
    return [
        sym.str.slice(6, 6).str.strptime(pl.Date, "%y%m%d", strict=False).alias("_exp"),
        (sym.str.slice(13, 8).cast(pl.Int64, strict=False) / 1000).alias("_strike"),
    ]


def invalid_quote_rate(
    opt_clean: pl.DataFrame,
    opt_rejected: pl.DataFrame,
    und_quotes: pl.DataFrame,
    cal: TradingCalendar,
    cfg: Phase1Config,
    sessions: list[date],
) -> pl.DataFrame:
    """Rejected share among RTH records of D+1 contracts within ATM +- dq.atm_half_width strikes
    of the session's first valid RTH underlying mid (gate 2). Contract identity comes from the
    OCC symbol, so rejected rows (which may lack definitions) are included."""
    first_mid = (
        und_quotes.filter(pl.col("is_rth") & _valid_quote(pl.col("bid"), pl.col("ask")))
        .sort("ts")
        .group_by("session_date", maintain_order=True)
        .first()
        .select("session_date", mid=(pl.col("bid") + pl.col("ask")) / 2)
    )
    mids = dict(zip(first_mid["session_date"].to_list(), first_mid["mid"].to_list(), strict=True))
    clean = opt_clean.filter(pl.col("is_rth")).select(
        "session_date", "symbol", rejected=pl.lit(False)
    )
    rej = opt_rejected.select("session_date", "symbol", "ts", rejected=pl.lit(True))
    rows = []
    for d in sessions:
        open_, close = cal.open_close(d)
        nxt = cal.next_session(d)
        mid = mids.get(d)
        r = rej.filter(
            (pl.col("session_date") == d) & (pl.col("ts") > open_) & (pl.col("ts") <= close)
        ).drop("ts")
        both = pl.concat([clean.filter(pl.col("session_date") == d), r]).with_columns(
            _occ_parts(pl.col("symbol"))
        )
        if mid is None:
            rows.append({"session_date": d, "n_total": 0, "n_rejected": 0, "rate": None})
            continue
        strikes = sorted(set(both.filter(pl.col("_exp") == nxt)["_strike"].drop_nulls().to_list()))
        if not strikes:
            rows.append({"session_date": d, "n_total": 0, "n_rejected": 0, "rate": None})
            continue
        i = min(range(len(strikes)), key=lambda k: abs(strikes[k] - mid))
        h = cfg.dq.atm_half_width
        band = set(strikes[max(i - h, 0) : i + h + 1])
        pop = both.filter((pl.col("_exp") == nxt) & pl.col("_strike").is_in(list(band)))
        n, nr = pop.height, int(pop["rejected"].sum())
        rows.append(
            {"session_date": d, "n_total": n, "n_rejected": nr, "rate": nr / n if n else None}
        )
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "n_total": pl.Int64,
            "n_rejected": pl.Int64,
            "rate": pl.Float64,
        },
    )
