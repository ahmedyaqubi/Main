"""Spec §4.9 liquidity gates checked against frozen-rule quotes (M4 criterion 5).

Input: `sessions.frozen_rule_table`. Only quotes that are valid at T (two-sided, fresh, not
rejected) are studied; the gates decide tradability, not data validity.
"""

from __future__ import annotations

import polars as pl

from qqq1dte.core.config import Phase1Config


def _long(table: pl.DataFrame) -> pl.DataFrame:
    parts = []
    for side in ("call", "put"):
        parts.append(
            table.filter(pl.col(f"{side}_ok")).select(
                year=pl.col("session_date").dt.year().cast(pl.String),
                side=pl.lit(side),
                bid=pl.col(f"{side}_bid"),
                ask=pl.col(f"{side}_ask"),
                ask_sz=pl.col(f"{side}_ask_sz"),
            )
        )
    return pl.concat(parts).with_columns(
        spread=(pl.col("ask") - pl.col("bid")).round(9),
        mid=(pl.col("ask") + pl.col("bid")) / 2,
    )


def liquidity_study(table: pl.DataFrame, cfg: Phase1Config) -> pl.DataFrame:
    liq = cfg.liquidity
    df = (
        _long(table)
        .with_columns(
            g_spread=pl.col("spread")
            <= pl.max_horizontal(pl.lit(liq.max_spread_abs), liq.max_spread_pct * pl.col("mid")),
            g_bid=pl.col("bid") >= liq.min_bid,
            # Buying 1 contract needs ask size >= contracts (spec §4.9 displayed size).
            g_size=pl.col("ask_sz") >= cfg.trade.contracts,
        )
        .with_columns(g_all=pl.col("g_spread") & pl.col("g_bid") & pl.col("g_size"))
    )

    def agg(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
        return frame.group_by(keys).agg(
            n=pl.len(),
            spread_p50=pl.col("spread").quantile(0.5, "linear"),
            spread_p90=pl.col("spread").quantile(0.9, "linear"),
            spread_p99=pl.col("spread").quantile(0.99, "linear"),
            mid_p50=pl.col("mid").quantile(0.5, "linear"),
            pass_spread=pl.col("g_spread").mean(),
            pass_min_bid=pl.col("g_bid").mean(),
            pass_size=pl.col("g_size").mean(),
            pass_all=pl.col("g_all").mean(),
        )

    by_year_side = agg(df, ["year", "side"])
    by_year = agg(df, ["year"]).with_columns(side=pl.lit("both"))
    overall = agg(df.with_columns(year=pl.lit("all")), ["year"]).with_columns(side=pl.lit("both"))
    cols = by_year_side.columns
    return pl.concat([by_year_side, by_year.select(cols), overall.select(cols)]).sort(
        ["year", "side"]
    )
