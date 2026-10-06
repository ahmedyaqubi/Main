"""Record-level cleaning: raw layer -> cleaned (OK/FLAGGED) + rejected, with reasons.

Conservation holds by construction: every raw row lands in exactly one output. Cleaned rows get
`ts`, `available_at` (spec §7 / DATA_QUALITY.md), `session_date` (ET), float prices with the
vendor's undefined sentinel as null, `dq_status` and `dq_flags`. Rejected rows keep every raw
column unchanged plus `session_date`, `ts` and `dq_reasons`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config

UNDEF = 2**63 - 1
UNDEF_TS = 2**64 - 1  # Databento UNDEF_TIMESTAMP
UNDEF_INT32 = 2**31 - 1  # Databento's undefined int32 (e.g. OPRA contract_multiplier)
NS = 1_000_000_000
NY = "America/New_York"
PROVENANCE = ("source", "vendor_dataset", "schema", "raw_file_id", "ingested_at")
MULTIPLIER = 100
STRIKE_GRID_TOL = 1e-6  # strikes are exact to 1e-9; anything further off the grid is real


@dataclass(frozen=True)
class CleanResult:
    cleaned: pl.DataFrame
    rejected: pl.DataFrame


# shared helpers --------------------------------------------------------------------------
def _dt(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Int64).cast(pl.Datetime("ns", "UTC"))


def _px(col: str) -> pl.Expr:
    """Fixed-point 1e-9 -> float; undefined sentinel -> null.

    Rounded to 9 decimals, the vendor's exact precision, so 480_000_000_000 -> 480.0 (a bare
    float division can give 480.00000000000006). Representation only; no value changes.
    """
    return pl.when(pl.col(col) == UNDEF).then(None).otherwise((pl.col(col) / NS).round(9))


def _session_table(cal: TradingCalendar, dates: list[date]) -> pl.DataFrame:
    """Per calendar date: whether it is a session, and its UTC open/close."""
    rows = []
    for d in sorted(set(dates)):
        if cal.is_session(d):
            o, c = cal.open_close(d)
            rows.append(
                {
                    "session_date": d,
                    "is_session": True,
                    "_open": o,
                    "_close": c,
                    "is_early_close": cal.is_early_close(d),
                }
            )
        else:
            rows.append(
                {
                    "session_date": d,
                    "is_session": False,
                    "_open": None,
                    "_close": None,
                    "is_early_close": False,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "is_session": pl.Boolean,
            "_open": pl.Datetime("ns", "UTC"),
            "_close": pl.Datetime("ns", "UTC"),
            "is_early_close": pl.Boolean,
        },
    )


def _with_session(df: pl.DataFrame, cal: TradingCalendar, label: str) -> pl.DataFrame:
    """Add session_date, is_session, is_rth. label='start': RTH if open <= ts < close (bars);
    label='end': RTH if open < ts <= close (interval-end quote stamps)."""
    df = df.with_columns(session_date=pl.col("ts").dt.convert_time_zone(NY).dt.date())
    sessions = _session_table(cal, df["session_date"].to_list())
    df = df.join(sessions, on="session_date", how="left")
    if label == "start":
        in_rth = (pl.col("ts") >= pl.col("_open")) & (pl.col("ts") < pl.col("_close"))
    else:
        in_rth = (pl.col("ts") > pl.col("_open")) & (pl.col("ts") <= pl.col("_close"))
    return df.with_columns(is_rth=pl.col("is_session") & in_rth.fill_null(False)).drop(
        ["_open", "_close"]
    )


def _reasons(checks: list[tuple[str, pl.Expr]]) -> pl.Expr:
    """List of check names whose condition is true (in catalogue order)."""
    parts = [pl.when(cond).then(pl.lit(name)).otherwise(None) for name, cond in checks]
    return pl.concat_list(parts).list.drop_nulls()


def _session_flags() -> list[tuple[str, pl.Expr]]:
    return [
        ("NON_SESSION", ~pl.col("is_session")),
        ("OUTSIDE_RTH", pl.col("is_session") & ~pl.col("is_rth")),
    ]


def _duplicate_reasons(df: pl.DataFrame, key: list[str], value_cols: list[str]) -> pl.DataFrame:
    """Add `_dup` reason: DUP_CONFLICT for every row of a key with differing values;
    DUP_EXACT for repeated identical rows after the first."""
    df = df.with_row_index("_row")
    n_distinct = df.group_by(key).agg(pl.struct(value_cols).n_unique().alias("_n_distinct"))
    df = df.join(n_distinct, on=key, how="left")
    first_copy = pl.col("_row") == pl.col("_row").min().over(value_cols)
    return df.with_columns(
        _dup=pl.when(pl.col("_n_distinct") > 1)
        .then(pl.lit("DUP_CONFLICT"))
        .when(~first_copy)
        .then(pl.lit("DUP_EXACT"))
        .otherwise(None)
    ).drop("_n_distinct")


def _split(df: pl.DataFrame, raw_cols: list[str], cleaned_cols: list[str]) -> CleanResult:
    reasons = pl.concat_list([pl.col("_reasons"), pl.col("_dup")]).list.drop_nulls()
    df = df.with_columns(dq_reasons=reasons).sort("_row")
    bad = df["dq_reasons"].list.len() > 0
    rejected = df.filter(bad).select([*raw_cols, "session_date", "ts", "dq_reasons"])
    cleaned = (
        df.filter(~bad)
        .with_columns(
            dq_status=pl.when(pl.col("dq_flags").list.len() > 0)
            .then(pl.lit("FLAGGED"))
            .otherwise(pl.lit("OK"))
        )
        .select(cleaned_cols)
    )
    return CleanResult(cleaned=cleaned, rejected=rejected)


def _ingest_check(ts_col: str = "ts") -> tuple[str, pl.Expr]:
    return (
        "TS_AFTER_INGEST",
        pl.col(ts_col) > pl.col("ingested_at").cast(pl.Datetime("ns", "UTC")),
    )


# bars ------------------------------------------------------------------------------------
def clean_bars(raw: pl.DataFrame, cal: TradingCalendar, cfg: Phase1Config) -> CleanResult:
    """ohlcv-1m: start-labelled bars; available_at = label + 1 min + publication lag."""
    raw_cols = raw.columns
    value_cols = [c for c in raw_cols if c not in PROVENANCE]
    lag_ns = (60 + cfg.pit.bar_publication_lag_s) * NS
    df = raw.with_columns(ts=_dt("ts_event")).with_columns(
        available_at=pl.col("ts") + pl.duration(nanoseconds=lag_ns, time_unit="ns")
    )
    df = _with_session(df, cal, label="start")
    df = df.with_columns(**{f"_{c}": _px(c) for c in ("open", "high", "low", "close")})
    o, h, lo, c = pl.col("_open"), pl.col("_high"), pl.col("_low"), pl.col("_close")
    prices_ok = pl.all_horizontal([x.is_not_null() & (x > 0) for x in (o, h, lo, c)])
    inconsistent = (lo > h) | (h < pl.max_horizontal(o, c)) | (lo > pl.min_horizontal(o, c))
    df = df.with_columns(
        _reasons=_reasons(
            [
                _ingest_check(),
                ("PRICE_NONPOSITIVE", ~prices_ok),
                ("OHLC_INCONSISTENT", prices_ok & inconsistent),
            ]
        ),
        dq_flags=_reasons(_session_flags()),
    )
    df = _duplicate_reasons(df, ["instrument_id", "ts_event"], value_cols)
    df = df.with_columns(open=o, high=h, low=lo, close=c)
    cleaned_cols = [
        "session_date",
        "ts",
        "available_at",
        "instrument_id",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "is_rth",
        "is_early_close",
        "dq_status",
        "dq_flags",
        "raw_file_id",
        "ingested_at",
    ]
    return _split(df, raw_cols, cleaned_cols)


# quotes ----------------------------------------------------------------------------------
QUOTE_CLEAN_COLS = [
    "session_date",
    "ts",
    "available_at",
    "instrument_id",
    "symbol",
    "bid",
    "ask",
    "bid_sz",
    "ask_sz",
    "is_rth",
    "is_early_close",
    "dq_status",
    "dq_flags",
    "raw_file_id",
    "ingested_at",
]


def _quote_frame(raw: pl.DataFrame, cal: TradingCalendar, cfg: Phase1Config) -> pl.DataFrame:
    """bbo-1m / cbbo-1m: ts = ts_recv (interval end) = available_at."""
    value_cols = [c for c in raw.columns if c not in PROVENANCE]
    df = raw.with_columns(ts=_dt("ts_recv")).with_columns(available_at=pl.col("ts"))
    df = _with_session(df, cal, label="end")
    bid_def = pl.col("bid_px_00") != UNDEF
    ask_def = pl.col("ask_px_00") != UNDEF
    bid, ask = pl.col("bid_px_00"), pl.col("ask_px_00")
    event_def = pl.col("ts_event") != UNDEF_TS
    # Undefined ts_event (no update in the interval) -> null skew -> check not triggered.
    skew = pl.col("ts_event").cast(pl.Int64, strict=False) - pl.col("ts_recv").cast(pl.Int64)
    df = df.with_columns(
        _reasons=_reasons(
            [
                _ingest_check(),
                ("TS_EVENT_AFTER_RECV", skew > cfg.dq.max_event_recv_skew_s * NS),
                # 0/0 is "no market" (flagged below); ask 0 with a positive bid is invalid.
                (
                    "NONPOSITIVE_PRICE",
                    (bid_def & (bid < 0)) | (ask_def & (ask <= 0) & ~(bid_def & (bid == 0))),
                ),
                ("BID_GT_ASK", bid_def & ask_def & (bid > ask)),
            ]
        ),
        dq_flags=_reasons(
            [
                ("EMPTY_BOOK", ~bid_def & ~ask_def),
                ("NO_BID", ~bid_def & ask_def),
                ("NO_ASK", bid_def & ~ask_def),
                ("ZERO_QUOTE", bid_def & ask_def & (bid == 0) & (ask == 0)),
                ("ZERO_BID", bid_def & (bid == 0) & ~(ask_def & (ask == 0))),
                ("NO_EVENT_TS", ~event_def),
                *_session_flags(),
            ]
        ),
        bid=_px("bid_px_00"),
        ask=_px("ask_px_00"),
        bid_sz=pl.col("bid_sz_00"),
        ask_sz=pl.col("ask_sz_00"),
    )
    return _duplicate_reasons(df, ["instrument_id", "ts_recv"], value_cols)


def clean_quotes(raw: pl.DataFrame, cal: TradingCalendar, cfg: Phase1Config) -> CleanResult:
    return _split(_quote_frame(raw, cal, cfg), raw.columns, QUOTE_CLEAN_COLS)


# options ---------------------------------------------------------------------------------
def build_definitions(raw_defs: pl.DataFrame, cal: TradingCalendar) -> pl.DataFrame:
    """One row per (session_date, instrument_id): the last definition received that day, plus
    each contract's first appearance across all definitions (listing evidence)."""
    df = raw_defs.with_columns(
        ts=_dt("ts_recv"),
        expiration=_dt("expiration").dt.date(),
        strike=_px("strike_price"),
        right=pl.col("instrument_class"),
        # OPRA definitions from Databento leave the multiplier undefined (ADR-0005): null, not
        # a number, so it can never be mistaken for a real multiplier.
        multiplier=pl.when(pl.col("contract_multiplier") == UNDEF_INT32)
        .then(None)
        .otherwise(pl.col("contract_multiplier").cast(pl.Int64)),
    ).with_columns(session_date=pl.col("ts").dt.convert_time_zone(NY).dt.date())
    first_seen = df.group_by("raw_symbol").agg(first_seen=pl.col("session_date").min())
    latest = (
        df.sort("ts")
        .group_by(["session_date", "instrument_id"], maintain_order=True)
        .last()
        .select(
            [
                "session_date",
                "instrument_id",
                "raw_symbol",
                "expiration",
                "strike",
                "right",
                "multiplier",
            ]
        )
    )
    sessions = {d for d in latest["expiration"].unique().to_list() if d is not None}
    session_flag = pl.DataFrame(
        {
            "expiration": sorted(sessions),
            "expiration_is_session": [cal.is_session(d) for d in sorted(sessions)],
        },
        schema={"expiration": pl.Date, "expiration_is_session": pl.Boolean},
    )
    return latest.join(first_seen, on="raw_symbol", how="left").join(
        session_flag, on="expiration", how="left"
    )


def _occ_date(sym: pl.Expr) -> pl.Expr:
    return sym.str.slice(6, 6).str.strptime(pl.Date, "%y%m%d", strict=False)


def _strike_status(cfg: Phase1Config) -> tuple[pl.Expr, pl.Expr]:
    """(on_grid, adjusted). A strike is OCC-adjusted if, for a documented adjustment with
    ex_date <= session_date, some grid strike K satisfies round(K - reduction, 2) == strike
    (OCC: "reduced by the amount and rounded to the nearest penny")."""
    inc = cfg.dq.strike_increment
    s = pl.col("strike")
    on_grid = ((s / inc) - (s / inc).round(0)).abs() <= STRIKE_GRID_TOL
    adjusted = pl.lit(False)
    for a in cfg.dq.strike_adjustments:
        k = ((s + a.reduction) / inc).round(0) * inc
        matches = ((k - a.reduction).round(2) - s).abs() <= STRIKE_GRID_TOL
        adjusted = adjusted | ((pl.col("session_date") >= a.ex_date) & matches)
    return on_grid, adjusted & ~on_grid


def contract_reasons(cfg: Phase1Config) -> list[tuple[str, pl.Expr]]:
    """Definition-level rejections (columns: raw_symbol, strike, multiplier, expiration,
    expiration_is_session, session_date). Shared by cleaning and the chain used for selection."""
    on_grid, adjusted = _strike_status(cfg)
    root = pl.col("raw_symbol").str.slice(0, 6).str.strip_chars()
    return [
        ("NONSTANDARD_ROOT", root != cfg.dq.option_root),
        ("INVALID_MULTIPLIER", pl.col("multiplier").is_not_null()
         & (pl.col("multiplier") != MULTIPLIER)),
        ("NONSTANDARD_STRIKE", ~on_grid & ~adjusted),
        ("EXPIRATION_MISMATCH", _occ_date(pl.col("raw_symbol")) != pl.col("expiration")),
        ("EXPIRATION_NOT_SESSION", ~pl.col("expiration_is_session").fill_null(False)),
    ]  # fmt: skip


def contract_flags(cfg: Phase1Config) -> list[tuple[str, pl.Expr]]:
    _, adjusted = _strike_status(cfg)
    return [
        ("MULTIPLIER_UNKNOWN", pl.col("multiplier").is_null()),
        ("ADJUSTED_STRIKE", adjusted),
    ]


def standard_contract(cfg: Phase1Config) -> pl.Expr:
    """True for definitions that pass every contract-level check."""
    return pl.all_horizontal([~cond.fill_null(True) for _, cond in contract_reasons(cfg)])


def clean_option_quotes(
    raw: pl.DataFrame, defs: pl.DataFrame, cal: TradingCalendar, cfg: Phase1Config
) -> CleanResult:
    """cbbo-1m plus contract checks against same-session definitions."""
    df = _quote_frame(raw, cal, cfg)
    df = df.join(defs.drop("first_seen"), on=["session_date", "instrument_id"], how="left")
    first_seen = (
        defs.group_by("raw_symbol")
        .agg(pl.col("first_seen").min())
        .rename({"raw_symbol": "symbol", "first_seen": "_first_seen"})
    )
    df = df.join(first_seen, on="symbol", how="left")
    has_def = pl.col("raw_symbol").is_not_null()
    contract = _reasons(
        [
            ("NOT_YET_LISTED", ~has_def & (pl.col("_first_seen") > pl.col("session_date"))),
            (
                "CONTRACT_UNKNOWN",
                ~has_def
                & (
                    pl.col("_first_seen").is_null()
                    | (pl.col("_first_seen") <= pl.col("session_date"))
                ),
            ),
            ("SYMBOL_MISMATCH", has_def & (pl.col("raw_symbol") != pl.col("symbol"))),
            *[(name, has_def & cond) for name, cond in contract_reasons(cfg)],
        ]
    )
    flags = _reasons([(name, has_def & cond) for name, cond in contract_flags(cfg)])
    df = df.with_columns(
        _reasons=pl.concat_list([pl.col("_reasons"), contract]),
        dq_flags=pl.concat_list([pl.col("dq_flags"), flags]),
    )
    cols = [
        *QUOTE_CLEAN_COLS[:5],
        "raw_symbol",
        "expiration",
        "strike",
        "right",
        *QUOTE_CLEAN_COLS[5:],
    ]
    return _split(df, raw.columns, cols)
