"""M23 Step 0 (ADR-0014 D0, R1-R9): SPX data-coverage report. Data only.

It uses entry-time quotes and exit-quote availability, with no exit price, P&L or outcome, and
registers no trial. Development sessions only: the loader refuses any session after
`last_session` minus `holdout_months`.

Per development session and cell (L1-L4, D4) at T_e = 10:00 ET + latency:
- W from the previous Cboe close (R2) and the expiry closest to the target DTE (D2), among
  standard contracts known at T_e.
- The frozen credit rule (`execution_sim.spreads.credit_pick`); a condor needs both sides.
- The §4.9 gates per leg (R1, min-bid on short legs only), at the Phase 1 thresholds.
- Exit-quote availability on the session before expiry at 15:45 (12:45 on early closes) +
  latency.

Also reported:
- the chosen-expiry DTE by year;
- picked-leg spreads;
- the strike step at the pick;
- rejection rates;
- the R5 minimum detectable effect (outcome-free upper bound).

When SPX and SPXW list the same expiry date (monthly expiries), SPXW is used. That root choice
is an open Step-1 question for the owner.

    uv run python scripts/m23_coverage.py
"""

from __future__ import annotations

import math
import statistics
import subprocess
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from qqq1dte.core.calendar import TradingCalendar, add_months
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.execution_sim.longdated import (
    choose_expiry,
    exit_session,
    mde_upper_bound,
    width_from_close,
)
from qqq1dte.execution_sim.selection import Quote, liquidity_failures
from qqq1dte.execution_sim.spreads import AT_BAND_EDGE, NO_QUALIFYING, OK, LegQuote, credit_pick
from qqq1dte.features.inputs import chain_table
from qqq1dte.labels.option import option_records
from qqq1dte.labels.spread import quote_at

ROOT = Path(__file__).resolve().parents[1]
S0: dict[str, Any] = yaml.safe_load((ROOT / "configs" / "m23_step0.yaml").read_text("utf-8"))
CLEAN = ROOT / "data" / "clean" / "m23"
REPORT = ROOT / "reports" / "research" / "m23_data_coverage.md"
START = date.fromisoformat(S0["start"])
DEV_END = add_months(date.fromisoformat(S0["last_session"]), -int(S0["holdout_months"]))
CELLS = {  # ADR-0014 D4
    "L1": (30, "put", 0.20),
    "L2": (30, "condor", 0.15),
    "L3": (7, "put", 0.20),
    "L4": (7, "condor", 0.15),
}
W_SHARE, W_GRID, W_MIN = 0.005, 5.0, 10.0  # R2
ENTRY = time(10, 0)
EXIT = time(15, 45)
EARLY_EXIT_OFFSET = timedelta(minutes=15)
POWER, ALPHA = 0.8, 0.05


def spx_config(cfg: Phase1Config, root: str) -> Phase1Config:
    dq = cfg.dq.model_copy(update={"option_root": root, "strike_adjustments": []})
    hist = cfg.history.model_copy(update={"excluded_sessions": []})
    return cfg.model_copy(update={"dq": dq, "history": hist})


@cache
def records(d: date) -> pl.DataFrame:
    if d > DEV_END:
        raise RuntimeError(f"holdout session {d} requested: refused (ADR-0014 D3)")
    c, r = CLEAN / "cleaned" / f"{d}.parquet", CLEAN / "rejected" / f"{d}.parquet"
    if not c.exists():
        return pl.DataFrame()
    rej = pl.read_parquet(r) if r.exists() else pl.DataFrame(
        schema={"symbol": pl.String, "ts": pl.Datetime("ns", "UTC")}
    )  # fmt: skip
    return option_records(pl.read_parquet(c), rej)


def spx_closes() -> dict[date, float]:
    df = pl.read_csv(ROOT / S0["spx_close_csv"]).select(
        d=pl.col("DATE").str.strptime(pl.Date, "%m/%d/%Y"), c=pl.col("SPX").cast(pl.Float64)
    )
    return dict(zip(df["d"].to_list(), df["c"].to_list(), strict=True))


def exit_time(cal: TradingCalendar, d: date) -> datetime:
    _, close = cal.open_close(d)
    if cal.is_early_close(d):
        return close - EARLY_EXIT_OFFSET
    return datetime.combine(d, EXIT, ET).astimezone(UTC)


def code_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def pick_side(
    chain: pl.DataFrame, q: dict[str, Quote], right: str, x: float, w: float, t_e: datetime,
    cfg: Phase1Config,
) -> dict[str, Any]:  # fmt: skip
    sub = chain.filter(pl.col("right") == right).sort("root", descending=True)  # SPXW first
    book: dict[float, LegQuote] = {}
    sym: dict[float, str] = {}
    for r in sub.iter_rows(named=True):
        k = r["strike"]
        if k in book:
            continue  # same strike on SPX: SPXW kept (open Step-1 question)
        qq = q.get(r["raw_symbol"])
        usable = (
            qq is not None
            and not qq.rejected
            and t_e - qq.available_at <= timedelta(seconds=cfg.liquidity.max_quote_age_s)
        )
        book[k] = LegQuote(k, qq.bid if qq else None, qq.ask if qq else None, usable)
        sym[k] = r["raw_symbol"]
    p = credit_pick(book, right, x, w)
    out: dict[str, Any] = {"status": p.status, "beyond": p.beyond}
    if p.short is not None and p.long is not None:
        legs = {"short": sym[p.short], "long": sym[p.long]}
        fails = []
        spreads = []
        for role, s in legs.items():
            qq = q[s]
            gate = liquidity_failures(qq, t_e, cfg, check_min_bid=role == "short")
            fails += [f"{role}:{f}" for f in gate]
            if qq.bid is not None and qq.ask is not None:
                mid = (qq.bid + qq.ask) / 2
                spreads.append((qq.ask - qq.bid, (qq.ask - qq.bid) / mid if mid > 0 else math.nan))
        strikes = sorted(book)
        i = strikes.index(p.short)
        step = min(
            [abs(strikes[j] - p.short) for j in (i - 1, i + 1) if 0 <= j < len(strikes)]
            or [math.nan]
        )
        out |= {"legs": legs, "credit": p.credit, "fails": fails, "spreads": spreads, "step": step}
    return out


def main() -> int:  # noqa: PLR0912, PLR0915 (linear report)
    base = load_config()
    cfg = spx_config(base, "SPXW")
    cal = TradingCalendar(cfg)
    defs = pl.read_parquet(CLEAN / "definitions.parquet").filter(pl.col("session_date") <= DEV_END)
    chain_all = pl.concat(
        [
            chain_table(defs, spx_config(base, r)).with_columns(root=pl.lit(r))
            for r in ("SPX", "SPXW")
        ]
    )
    sessions = cal.sessions(START, DEV_END)
    sset = set(cal.sessions(START, DEV_END + timedelta(days=60)))
    all_sessions = cal.sessions(START, DEV_END + timedelta(days=60))
    closes = spx_closes()
    latency = timedelta(seconds=cfg.fills.latency_s)
    max_gap = timedelta(minutes=cfg.labels.option.max_path_gap_minutes)
    rows: list[dict[str, Any]] = []
    for n, d in enumerate(sessions, 1):
        prev = max(x for x in closes if x < d)
        w = width_from_close(closes[prev], W_SHARE, W_GRID, W_MIN)
        t_e = datetime.combine(d, ENTRY, ET).astimezone(UTC) + latency
        known = chain_all.filter((pl.col("session_date") == d) & (pl.col("available_at") <= t_e))
        recs = records(d)
        q = quote_at(recs, t_e) if recs.height else {}
        for cell, (tgt, struct, x) in CELLS.items():
            exp = choose_expiry(set(known["expiration"].to_list()), d, tgt, sset)
            row: dict[str, Any] = {
                "session": d,
                "year": d.year,
                "cell": cell,
                "W": w,
                "expiry": exp,
                "dte": (exp - d).days if exp else None,
            }
            if exp is None:
                rows.append({**row, "status": "NO_EXPIRY"})
                continue
            ch = known.filter(pl.col("expiration") == exp)
            row["both_roots"] = ch["root"].n_unique() > 1
            sides = ["P"] if struct == "put" else ["P", "C"]
            picks = {s: pick_side(ch, q, s, x, w, t_e, cfg) for s in sides}
            st = [p["status"] for p in picks.values()]
            status = (
                NO_QUALIFYING if NO_QUALIFYING in st else AT_BAND_EDGE if AT_BAND_EDGE in st else OK
            )
            row |= {"status": status, "beyond": min(p["beyond"] for p in picks.values())}
            if status != OK:
                rows.append(row)
                continue
            fails = [f for p in picks.values() for f in p["fails"]]
            spreads = [s for p in picks.values() for s in p["spreads"]]
            ex = exit_session(exp, all_sessions)
            row |= {
                "gate_fails": ";".join(fails),
                "spread_abs": statistics.median(a for a, _ in spreads),
                "spread_pct": statistics.median(b for _, b in spreads),
                "step": min(p["step"] for p in picks.values()),
                "credit": sum(p["credit"] for p in picks.values()),
                "hold": len([s for s in all_sessions if d < s <= ex]) if ex else None,
                "exit": ex,
            }
            if ex is None or ex > DEV_END:
                row["exit_status"] = "CROSSES_HOLDOUT"
            else:
                xr = records(ex)
                t_x = exit_time(cal, ex) + latency
                qx = quote_at(xr, t_x) if xr.height else {}
                legs = [s for p in picks.values() for s in p["legs"].values()]
                bad = []
                for s in legs:
                    qq = qx.get(s)
                    if qq is None:
                        bad.append("NOT_STORED")
                    elif qq.rejected or qq.ask is None or qq.ask <= 0:
                        bad.append("NO_ASK")
                    elif t_x - qq.available_at > max_gap:
                        bad.append("STALE")
                row["exit_status"] = "OK" if not bad else sorted(set(bad))[0]
            rows.append(row)
        if n % 250 == 0:
            print(f"sessions {n}/{len(sessions)}", flush=True)
            records.cache_clear()
    df = pl.DataFrame(rows, infer_schema_length=None)
    df.write_parquet(CLEAN / "coverage_rows.parquet")
    if df["session"].max() > DEV_END:  # type: ignore[operator]
        raise RuntimeError("holdout session in report data")
    log = pl.read_parquet(CLEAN / "dq_log.parquet").filter(pl.col("session_date") <= DEV_END)

    out = [
        "# M23 Step 0: SPX data coverage (ADR-0014)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m23_coverage.py`, code "
        f"{code_commit()[:12]}. Development sessions {sessions[0]} → {sessions[-1]} "
        f"({len(sessions)}); the holdout (after {DEV_END}) was cleaned but not read.",
        "",
        "**Data only:** entry-time quotes and exit-quote availability. No exit price, P&L or "
        "outcome; no trial registered.",
        "",
        "## 1. Cells at entry (10:00 ET + latency)",
        "",
        "- **OK**: a qualifying pair exists, with stored strikes beyond it.",
        "- **AT_BAND_EDGE**: the pair sits at the edge of the downloaded strikes (a NO_TRADE in "
        "Step 1).",
        "- **NO_QUALIFYING**: no pair reaches X x W.",
        "- **NO_EXPIRY**: no listed expiry.",
        "- *Gates pass*: every leg passes §4.9 at the **Phase 1 thresholds** (spread ≤ "
        f"max(${cfg.liquidity.max_spread_abs:.2f}, {cfg.liquidity.max_spread_pct:.0%} of mid); "
        "min bid on short legs only).",
        "- *Exit OK*: every leg has a usable ask at the exit, no older than "
        f"{cfg.labels.option.max_path_gap_minutes} min.",
        "",
        "| cell | target DTE | structure | X | sessions | OK | AT_BAND_EDGE | NO_QUALIFYING "
        "| NO_EXPIRY | gates pass (of OK) | exit OK (of OK) | crosses holdout |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip

    def pct(a: float, b: float) -> str:
        return f"{a / b:.1%}" if b else "-"

    for cell, (tgt, struct, x) in CELLS.items():
        g = df.filter(pl.col("cell") == cell)
        okg = g.filter(pl.col("status") == OK)
        c = Counter(g["status"].to_list())
        gates = okg.filter(pl.col("gate_fails") == "").height
        exit_ok = okg.filter(pl.col("exit_status") == "OK").height
        cross = okg.filter(pl.col("exit_status") == "CROSSES_HOLDOUT").height
        out.append(
            f"| {cell} | {tgt} | {struct} | {x:.2f} | {g.height} | {pct(c[OK], g.height)} "
            f"| {pct(c[AT_BAND_EDGE], g.height)} | {pct(c[NO_QUALIFYING], g.height)} "
            f"| {pct(c['NO_EXPIRY'], g.height)} | {pct(gates, okg.height)} "
            f"| {pct(exit_ok, okg.height - cross)} | {cross} |"
        )
    fail_counts: Counter[str] = Counter()
    for v in df.filter(pl.col("status") == OK)["gate_fails"].to_list():
        for f in filter(None, (v or "").split(";")):
            fail_counts[f.split(":")[0] + ":" + f.split(":")[1]] += 1
    n_ok = df.filter(pl.col("status") == OK).height
    out += [
        "",
        "§4.9 failures across OK entries (all cells; one entry can fail several):",
        "",
        *[f"- {k}: {v} ({pct(v, n_ok)})" for k, v in fail_counts.most_common()],
        "",
        "Exit problems (OK entries whose exit is in development data): "
        + ", ".join(
            f"{k} {v}"
            for k, v in Counter(
                df.filter((pl.col("status") == OK) & (pl.col("exit_status") != "CROSSES_HOLDOUT"))[
                    "exit_status"
                ].to_list()
            ).most_common()
        )
        + ".",
        "",
        "## 2. Picked-leg spreads (all OK entries; median by year), SPX points",
        "",
        "| year | cell | entries | median spread | median spread / mid | median W | median "
        "strike step at pick | median DTE | entries with both roots |",
        "|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    t2 = (
        df.filter(pl.col("status") == OK)
        .group_by("year", "cell")
        .agg(
            n=pl.len(),
            sa=pl.col("spread_abs").median(),
            sp=pl.col("spread_pct").median(),
            w=pl.col("W").median(),
            step=pl.col("step").median(),
            dte=pl.col("dte").median(),
            both=pl.col("both_roots").sum(),
        )
        .sort("year", "cell")
    )
    for r in t2.iter_rows(named=True):
        out.append(
            f"| {r['year']} | {r['cell']} | {r['n']} | {r['sa']:.2f} | {r['sp']:.1%} | {r['w']:g} "
            f"| {r['step']:g} | {r['dte']:g} | {r['both']} |"
        )
    # R5: minimum detectable effect, outcome-free (range = W x 100 per spread)
    out += [
        "",
        "## 3. Minimum detectable effect (R5; outcome-free)",
        "",
        f"A one-sided test at alpha = {ALPHA} with power {POWER:.0%}, on the mean net P&L per "
        "trade. "
        "The P&L range per spread is at most W x 100 (credit to -(W - credit)), so sigma <= W x 50 "
        "(Popoviciu). n_eff = development sessions ÷ median holding period (sessions), the "
        "number of independent holding periods.",
        "",
        "These are **upper bounds**: the true MDE is smaller if P&L is less dispersed than the "
        "worst case. In units of the median conservative credit, an MDE above 1 means the screen "
        "cannot detect an effect as large as the whole credit.",
        "",
        "| cell | median W | median hold (sessions) | n_eff | MDE $/trade (≤) | median credit $ "
        "| MDE / credit |",
        "|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for cell in CELLS:
        okg = df.filter((pl.col("cell") == cell) & (pl.col("status") == OK))
        if okg.height == 0:
            continue
        w = float(okg["W"].median())  # type: ignore[arg-type]
        hold = float(okg["hold"].drop_nulls().median())  # type: ignore[arg-type]
        n_eff = len(sessions) / hold if hold else 0.0
        mde = mde_upper_bound(w * 100, n_eff, ALPHA, POWER)
        cr = float(okg["credit"].median()) * 100  # type: ignore[arg-type]
        out.append(
            f"| {cell} | {w:g} | {hold:g} | {n_eff:.0f} | {mde:,.0f} | {cr:,.0f} | {mde / cr:.2f} |"
        )
    ry = (
        log.group_by(year=pl.col("session_date").dt.year())
        .agg(raw=pl.col("n_raw").sum(), rej=pl.col("n_rejected").sum())
        .sort("year")
    )
    reasons: Counter[str] = Counter()
    for s in log["reasons"].to_list():
        for part in filter(None, (s or "").split(";")):
            k, v = part.split("=")
            reasons[k] += int(v)
    out += [
        "",
        "## 4. Cleaning (M4 rules, SPX config copy per root)",
        "",
        "| year | raw quotes | rejected | rate |",
        "|---|---|---|---|",
        *[f"| {r['year']} | {r['raw']:,} | {r['rej']:,} | {pct(r['rej'], r['raw'])} |"
          for r in ry.iter_rows(named=True)],
        "",
        "Rejection reasons: "
        + (", ".join(f"{k} {v:,}" for k, v in reasons.most_common()) or "none")
        + ".",
        "",
        "## 5. Open items for Step 1 (owner decides; no definition changed here)",
        "",
        "- **Liquidity gates for SPX:** see §1-§2. The Phase 1 thresholds were calibrated on QQQ "
        "(M4); SPX thresholds need an ADR before Step 1.",
        "- **Root on shared expiry dates:** this report used SPXW when SPX and SPXW list the same "
        "date (see 'entries with both roots').",
        "- **Power:** see §3.",
        "",
    ]  # fmt: skip
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
