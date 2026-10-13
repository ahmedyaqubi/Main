# ADR-0018: Short-term pullback buying on SPY (Connors RSI(2)), one pre-registered rule (M27)

- Status: **ACCEPTED** 2026-10-13 by the owner ("approve, go ahead"). Drafted from the
  owner's answers to PB-Q1–Q4 under ADR-0015 (shortlist idea #3, `docs/ROADMAP.md`).
- Milestone: M27.
- Mission and limits: ADR-0015, used as written.
  - **Budget charge: 1 of the 10 tests** (after this, 3 of 10 used).
  - Data: free; the SPY data and checks from M26 are reused ($0).
- **Disclosures:**
  - **The rule comes from the literature, not from our data:** Connors & Alvarez (2009),
    *Short Term Trading Strategies That Work*. It is one of the most widely traded and
    data-mined retail rules. Its published tests overlap our development period (1993–2015),
    so a development pass is weak evidence on its own. The holdout is the real test.
  - Before drafting this ADR, the assistant advised pausing rather than continuing down the
    shortlist. The owner chose to proceed.
  - The assistant knows this literature and the broad market history of 1993–2026. The
    protections are a fixed rule, a fixed statistic, and a holdout opened once.
  - In M25 and M26 the same SPY prices were examined: data checks, monthly and turn-of-month
    returns. They were never examined with this rule's signals.

## Reason first (ADR-0015 D1)
- **Who pays:** sellers who need liquidity quickly (forced, leveraged, or panicking), and the
  liquidity providers and arbitrageurs who absorb that selling and want paying for it. After
  a sharp short-term drop, prices tend to partly rebound.
- **Why it may persist:** short-horizon overreaction and inventory risk. Absorbing selling in
  a falling market is uncomfortable, and capital is scarce exactly then.
- **Why it may fail here:**
  - It is heavily traded, so it may be competed away.
  - **Next-open execution:** the published tests buy at the signal day's close. Part of the
    rebound typically happens overnight, before our fill.
  - The 200-day filter keeps it out of bear markets, but a pullback in a bull market can keep
    falling (for example, Aug 1998 and Aug 2011).
- **Costs vs expected edge (ADR-0015 D2):** published average gains are well above our
  modelled round trip of about 0.10% on $5,000, so a trial is allowed. The next-open delay is
  an unknown share of that gain.

## Decision
### D1. The rule (frozen)
- **Instrument:** SPY only (owner PB-Q4).
- **Indicators on the dividend-adjusted close,** so ex-dividend drops cannot trigger signals:
  - **RSI(2)** with Wilder smoothing (α = 1/2), seeded with the first two daily changes;
  - **SMA(200)** and **SMA(5)** of the adjusted close, the current day included.
- **Entry signal at the close of day t:** RSI(2) < **10** and close > SMA(200), while not in a
  position.
  - The first possible signal comes after 200 sessions of history.
- **Exit signal at the close of any held day** (the entry day included): close > SMA(5).
- **Execution (owner PB-Q2):** every order is a market order at the **next session's open**,
  placed in the evening after the signal close.
  - A buy on day t+1 always follows a signal at close t. While in a position, new entry
    signals are ignored.
  - Any open position is always exited on the next exit signal; there is no maximum hold.
- **Size:** a fixed **$5,000** per trade. It buys floor($5,000 / open) whole shares at the
  unadjusted open, the rest earns T-bills, and cash may not go negative (as ADR-0017 D1).
  There is no compounding.
- **Cash account:** settlement is T+1 today. A sale at an open settles the next session, and
  the next possible buy is at the open after a later signal close, so settled cash is always
  available. *Uncertainty flagged:* IBKR's exact rule for buying on the settlement day is to
  be confirmed before any paper ADR.

### D2. Data (ADR-0015 D2; rule 9)
- **Tiingo SPY 1993-01-29 →** (`data/raw/tom`, fetched in M26) and **FRED DTB3**.
- **The M26 data check applies unchanged:** PASS with ADR-0017 E1. It covered completeness,
  closes, dividend adjustments, jumps in the close, and Shiller.
- **Opens:** this rule trades at the open, which the M26 checks did not test. An open-price
  check is added before computing:
  - every session's adj_open / open ratio must equal adj_close / close on the same day;
  - |open / previous close − 1| > 15% is listed and must be explained.
  Any failure stops the study.

### D3. Split and holdout
- **Development:** trades whose exit open is on or before 2015-12-31. Signals start after 200
  sessions of history, so about late 1993.
  - A position still open at the end of 2015 is excluded, because its exit would be in the
    holdout.
- **Holdout:** 2016-01-01 → 2026-09-30, the same SPY holdout as ADR-0016 and ADR-0017. **No
  code has read it.** It is opened once, only after an ADVANCE, with the same statistic.

### D4. Costs (ADR-0015 D2)
- **Commission:** IBKR Canada Fixed, as in ADR-0016 D4.
- **Spread and opening-auction slippage:** **3 bps per side** (SPY usually quotes 1 cent,
  under 1 bp). Shown at 2× as a descriptive row.
- **Round trip:** about $5, or 0.10%, per trade on $5,000.

### D5. Statistic and outcomes (one registered run = 1 test)
- **Unit:** one trade.
- **Statistic:** the mean **net excess return per trade**, as in ADR-0017 D5: net of costs, minus
  the T-bill growth of $5,000 over the trade's calendar days (owner PB-Q3).
- **Uncertainty:** a circular moving-block bootstrap over trades in time order, block 12,
  2,000 reps, with the fixed seed.
- **Development outcome:**
  - **ADVANCE:** one-sided 95% lower bound > 0, with ≥ **150** trades;
  - **KILL:** two-sided 95% upper bound < 0;
  - **AMBIGUOUS** otherwise.
  - Published frequencies suggest roughly 8–12 trades a year, so about 180–250 trades are
    expected. If fewer than 150 occur, the result cannot ADVANCE.
- **Descriptive only:**
  - gross mean, costs, win share, worst trade, worst day, holding days;
  - per year; 1993–2007 vs 2008–2015; without 2008; at 2× costs;
  - the loss-limit count (ADR-0015 D3);
  - the **same signals traded at the signal close** (the published timing, not tradable for
    the owner), to measure what next-open execution gives up;
  - versus SPY buy-and-hold: CAGR, Sharpe and maximum drawdown (approximate).
- **After the outcome:**
  - **AMBIGUOUS or KILL:** the idea stops, with no variants (thresholds, filters, exits, ETFs).
  - **ADVANCE:** a holdout ADR, then a paper-only ADR with 60+ sessions, then the owner
    decides (ADR-0015 D4).

## Order of work
1. Owner approves this ADR.
2. The open-price check (D2) → report. Stop on any failure.
3. Code, tests first: `strategies/pullback.py` (RSI(2), SMAs, signals, trade list), a
   `study_pullback` config block, and `scripts/m27_screen.py` (registered run before
   computing; synthetic dry run).
4. Leakage review, full checks, commit (owner OK).
5. Registered run from the commit, hand check of 3 trades, CI, report.

## Consequences
- **Reused:** the ETF loaders, holdout lock, registry, bootstrap and per-trade accounting
  (`strategies/tom.tom_trade`) from M25/M26.
- **ADR-0015 ledger:** after the registered run, 3 of 10 tests used; spend stays $28.51.
