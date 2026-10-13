# ADR-0017: Turn-of-month effect on SPY, one pre-registered rule (M26)

- Status: **ACCEPTED** 2026-10-13 by the owner ("approve, go ahead"). Drafted from the
  owner's answers to TOM-Q1–Q5 under ADR-0015 (shortlist idea #2, `docs/ROADMAP.md`).
- Milestone: M26.
- Mission and limits: ADR-0015, used as written.
  - **Budget charge: 1 of the 10 tests** (after this, 2 of 10 used).
  - Data: free sources only ($0).
- **Disclosures:**
  - **The rule comes from the literature, not from our data.** The turn-of-month effect has
    been documented since the late 1980s (Ariel 1987; Lakonishok & Smidt 1988). The window
    used here is McConnell & Xu (2008): the last trading day plus the first three trading days
    of the next month.
  - **The published evidence overlaps our development period** (1993–2015). A development
    pass is therefore weak evidence on its own, and the holdout (2016–2026, after the
    publication) is the real test.
  - The assistant knows this literature and the broad market history of 1993–2026. That cannot
    be undone. The protections are a fixed rule, a fixed statistic, and a holdout opened once.
  - In M25, SPY's 2004–2015 development data was already examined: data checks, plus monthly
    returns between month-end opens. These were not turn-of-month windows, but they were the
    same prices.

## Reason first (ADR-0015 D1)
- **Who pays:** nobody loses directly. The effect is a price-pressure premium. Scheduled cash
  arrives around month-end and is invested within a few days, whatever the price:
  - salaries and automatic 401(k)/pension contributions;
  - fund inflows;
  - institutional month-end rebalancing and window dressing.
  Liquidity providers who sell into that demand earn the premium; holding just before the
  flow captures part of it.
- **Why it may persist:** the flows are institutional and calendar-driven, not
  price-sensitive. Arbitrage capital is limited, because the premium is small per event and
  carries full market risk.
- **Why it may fail here:**
  - It has been widely known since about 1990 and is easy to trade, so it may be competed
    away.
  - Several studies report it weaker after the 2000s.
  - Each trade holds the full market for 4 days. One bad week can erase a year of premium.
- **Costs vs expected edge (ADR-0015 D2):** published estimates are about 0.1% per day over
  4 days, roughly 0.4% per event. The modelled round trip on $5,000 is about 0.10% (below).
  So the expected gross edge is above the cost, and a trial is allowed.

## Decision
### D1. The rule (frozen)
- **Instrument:** SPY only (owner TOM-Q4/Q5).
- **Window:** for each calendar month, let L be its last trading day (XNYS).
  - **Entry:** buy at the **close of the trading day before L** (day −2), so the returns of
    day −1 (L) and days +1, +2, +3 are held.
  - **Exit:** sell at the **close of the 3rd trading day of the next month** (day +3).
  - Outside the window: T-bills.
- **Orders:** market-on-close (MOC), placed in advance (owner TOM-Q2). Fills are modelled at
  the official close (Tiingo close; total return from the adjusted close).
- **Size:** each trade is modelled on a fixed **$5,000** account (owner Q2). It buys
  floor($5,000 / close) whole shares; the remainder earns T-bills. There is no compounding,
  so every trade carries the same cost structure.

### D2. Data (ADR-0015 D2; rule 9)
- **Tiingo SPY daily prices from 1993-01-29** (SPY's first day), with the free key in `.env`,
  refetched with the earlier start. **FRED DTB3** for cash (already on disk).
- **Data checks, development rows only** (1993-01-29 → 2015-12-31). These are ADR-0016 A1
  checks (a)–(e), unchanged, with the same thresholds. **Any failure stops the study.**
  - (a) completeness vs XNYS;
  - (b) adjustment consistency;
  - (c) jumps over 15%;
  - (d) 4 dividends per full year, from 1994 (1993 is a partial year);
  - (e) SPY vs Shiller price and dividends.

**Exception E1 (owner, 2026-10-13). Decided after seeing the check result, and disclosed as
such.**
- **What failed:** all price checks passed, including 275 months of SPY vs Shiller prices with
  0 violations. Two dividend checks failed:
  - (d) 2004 had 5 dividends;
  - (e) 55 months had SPY trailing dividends more than 10% away from Shiller's.
- **Why it is accepted:** the causes are confirmed in SPY's SEC annual reports (CIK 884394).
  - **2004:** the N-30D filed 2005-12-01 records a special dividend declared because of
    Microsoft's special dividend, ex-date 2004-11-15, as in Tiingo. The 10 months whose
    trailing 12 months contain it are 10–13% *above* Shiller.
  - **1993–2000:** SPY pays its fees out of dividend income. The fees, as a share of gross
    income, were about 7% (1994) and 11–14% (1998–2000), from the N-30D reports filed
    1996-03-04, 1998-12-21, 1999-11-29 and 2000-11-21. This matches the 45 months that were
    7–14% *below* Shiller. The ±10% band (ADR-0016 A1) was set from 2005+ fee levels; that was
    a design error, not a data error.
- **Scope, coded exactly** in `scripts/m26_verify_data.py`:
  - the 2004 count of 5;
  - months up to 2000-12 that are 0–15% below Shiller;
  - months 2004-11 → 2005-10 that are above Shiller.
  Any other failure still stops the study, and no threshold is changed.
- **Relevance:** of 93 SPY ex-dividend dates in 1993–2015, **0** fall on a held day of any
  turn-of-month window. Dividends therefore cannot change any trade's return.

### D3. Split and holdout
- **Development:** trades whose exit is on or before 2015-12-31. That is about 274 trades,
  from February 1993 to November 2015.
  - The December 2015 trade exits in January 2016, in the holdout, so it is excluded.
- **Holdout:** 2016-01-01 → 2026-09-30, the same SPY holdout locked in ADR-0016. **No code has
  read it.**
  - The loader refuses it until a holdout ADR passes.
  - It is opened once, only after an ADVANCE, with the same statistic and threshold.

### D4. Costs (ADR-0015 D2)
- **Commission:** IBKR Canada Fixed, as in ADR-0016 D4: $0.005/share, $1.00 minimum, 1% cap.
  On $5,000 that is $1 per side.
- **Auction slippage and fees:** **3 bps per side**, conservative. MOC fills at the official
  close, so there is no spread. The 3 bps covers SEC and FINRA sale fees and any imbalance
  effect. Shown at 2× as a descriptive row.
- **Round trip:** about $2 + $3 = **$5, or 0.10%** per trade.
- **Cash account:** each trade uses cash from a sale three weeks earlier, so settlement never
  binds. FX is excluded (USD funds assumed) and disclosed.

### D5. Statistic and outcomes (one registered run = 1 test)
- **Unit:** one trade.
- **Statistic:** the mean **net excess return per trade**: (exit value − costs) / $5,000 − 1,
  minus the T-bill growth of $5,000 over the same calendar days (owner TOM-Q1).
- **Uncertainty:** a moving-block bootstrap over trades, in chronological order. Block = 12
  trades (one year), 2,000 reps, with the fixed seed. This allows for clustering in volatile
  years.
- **Development outcome:**
  - **ADVANCE:** one-sided 95% lower bound > 0, with ≥ 240 trades;
  - **KILL:** two-sided 95% upper bound < 0;
  - **AMBIGUOUS** otherwise.
- **Descriptive only:**
  - gross mean, costs per trade, win share, worst trade, worst day;
  - per year and per decade, plus 1993–2007 vs 2008–2015;
  - mean at 2× costs; mean without 2008;
  - mean daily return inside vs outside the window;
  - versus SPY buy-and-hold over the same period: CAGR, Sharpe and maximum drawdown of the
    TOM + T-bills account (compounded) and of buy-and-hold.
  - **Loss-limit check (ADR-0015 D3):** the number of trades containing a day below −3% of the
    account. A full-size SPY position can breach the 3%-per-day limit. Position size is decided
    before any paper ADR, not here, because the statistic is per dollar.
- **After the outcome:**
  - **AMBIGUOUS or KILL:** the idea stops, with no variants (other windows, other ETFs, filters).
  - **ADVANCE:** a holdout ADR, then a paper-only ADR with 60+ sessions, then the owner
    decides (ADR-0015 D4).

## Order of work
1. Owner approves this ADR.
2. Refetch SPY from 1993 (free). Run the data checks, development only → report. Stop on any
   failure.
3. Code, tests first: `strategies/tom.py` (windows, trade P&L), a `study_tom` config block, and
   `scripts/m26_screen.py` (registered run before computing; synthetic dry run).
4. Leakage review, full checks, commit (owner OK).
5. Registered run from the commit, hand check of 3 trades, CI, report.

## Consequences
- **Reused:** the ETF loaders and holdout lock, the data checks, the registry and the bootstrap
  from M25.
- **ADR-0015 ledger:** after the registered run, 2 of 10 tests used; spend stays $28.51.
