# ADR-0016: ETF trend following, one pre-registered rule (M25)

- Status: **ACCEPTED** 2026-10-10 by the owner ("approve"). Drafted from the owner's answers
  ETF-Q1–Q4 under ADR-0015.
- Milestone: M25.
- Mission and limits: ADR-0015, which this ADR uses as written.
  - **Budget charge: 1 of the 10 tests.**
  - Data: free sources only.
- **Disclosures:**
  - This rule was published in 2007 (Faber's 10-month moving-average timing rule) and is
    widely known. It was chosen from the literature, not from our data.
  - The assistant knows the broad market history of 2004–2026 (for example the 2008 crisis and
    the 2020 crash), and that cannot be undone. The protections are a fixed rule, a fixed
    statistic, and a holdout opened once.
  - The development period includes 2008, when trend rules are known to have helped.

## Reason first (ADR-0015 D1)
- **Who pays:**
  - investors who underreact to slow-moving information;
  - institutions that rebalance slowly;
  - hedgers and forced sellers in crises.

  Time-series momentum is documented across about a century and many asset classes.
- **Why it may persist:** behavioural biases and limits to arbitrage. The rule is
  uncomfortable to follow and lags in strong bull markets, so it is hard to arbitrage away.
- **Why it may fail here:**
  - it has been well known since 2007;
  - V-shaped crashes (2020) whipsaw monthly rules;
  - four ETFs is a small universe.

## Decision
### D1. The rule (frozen)
- **Universe:** SPY, QQQ, TLT, GLD at **25% each**.
- **Signal:** on the last trading day of each month, for each ETF, the dividend-adjusted close
  is compared with the average of the last **10** month-end adjusted closes, the current one
  included.
  - Above → hold that ETF next month.
  - At or below → that 25% is held in T-bills.
- **Execution:** at the **next session's open**, using the opens implied by the adjusted
  series. Positions are not rebalanced within the month.
- **Benchmark:** the same four ETFs at 25% each, held and rebalanced monthly at the same opens,
  with the same cost model.

### D2. Data (ADR-0015 D2; rule 9)
- **Tiingo daily prices** (open, close, adjusted open, adjusted close, dividends, splits). The
  owner's free token is kept in `.env` and never committed. Raw JSON is stored with the source
  URL and fetch time.
- **FRED DTB3:** the 3-month T-bill secondary-market rate (free CSV). Each day's rate is
  applied to the next day's cash; it is published with a lag, and the latest published value
  is used.
- **Common history:** from 2004-11-18 (GLD's first day). The first signal is the first
  month-end with 10 month-ends of history (2005-08).
- **Verification, development period only:**
  - Tiingo unadjusted closes vs Stooq daily closes on 20 sampled development days.
  - Dividends vs published distributions for a sample.
  - A difference over 0.5% on any sampled day stops the study until explained (rule 11).

**Amendment A1 (owner, 2026-10-13): replaces the Stooq cross-check.**
- **Why:**
  - Stooq downloads are blocked: a bot check for scripts, and "Access denied" even in the
    owner's own browser.
  - Alpha Vantage's full history is premium only ($49.99/month subscription); the owner
    declined it.
- **Replacement checks.** Development period only (2004-11-18 → 2015-12-31). Thresholds were
  fixed before any data was examined, and **any failure stops the study (rule 11)**:
  - **(a) Completeness:** every XNYS session is present for every ticker, and there are no
    extra dates.
  - **(b) Adjustment consistency:** the ratio adj_close / close changes only on days with a
    dividend or a split. On each dividend day, the ratio change matches div_cash / previous
    close within 0.05 percentage points.
  - **(c) Jump scan:** every daily unadjusted move over 15% is listed and must be explained (a
    split, or a known market event). Any unexplained jump stops the study.
  - **(d) Dividend pattern:** dividends per full year must match each fund's schedule: SPY and
    QQQ quarterly (4), TLT monthly (12, or 13 when a payment shifts), GLD none.
  - **(e) Independent check, SPY:** Robert Shiller's free S&P 500 monthly data (Yale,
    `ie_data`):
    - the monthly-average S&P level P, divided by 10 × SPY's monthly-average unadjusted close,
      stays within ±1% of its median in every month;
    - SPY's trailing-12-month dividends × 10 are within ±10% of Shiller's annual dividend D.
- **Disclosed limit:** QQQ, TLT and GLD get internal checks only. Those catch broken or
  mis-adjusted data, but not a consistently wrong series. SPY gets an independent check.

**Exception E1 to check (d) (owner, 2026-10-13). Decided after seeing the check result, and
disclosed as such.**
- **What failed:** check (d) failed only for QQQ, which had 2 dividends in 2005 and 5 in 2014. All
  other checks passed, including SPY vs Shiller (0 violations in 132 months).
- **Why it is accepted:** official records confirm that the payments are real and that Tiingo
  has them right. The yearly pattern rule in (d) was too strict for QQQ: the fund paid little
  income in its early years and made one extra payment in 2014.
  - **2014:** the official Nasdaq dividend record lists the extra payment of $0.37313
    (ex-date 2014-02-27).
  - **2005:** the trust's SEC annual reports (N-30B-2, CIK 1067839) give per-share distributions
    from net investment income:
    - FY to 2005-09-30: $0.41. The report was filed 2006-04-25 (accession 0001047469-06-005571).
      Tiingo has Dec 2004 $0.37858 + Jun 2005 $0.03476 = $0.41334.
    - FY to 2006-09-30: $0.18. The report was filed 2007-01-18 (accession 0001104659-07-003177).
      Tiingo has Dec 2005 $0.1011 + Mar/Jun/Sep 2006 $0.0291 + $0.0257 + $0.0234 = $0.1793.
- **Scope:** the exception covers only these two QQQ years. Any other failure still stops the
  study, and no threshold is changed.

### D3. Split and holdout
- **Development:** returns 2005-09 → 2015-12.
- **Holdout:** 2016-01 → 2026-09, **locked before any data is examined**.
  - The data loader refuses dates after 2015-12-31 unless a holdout ADR passes, so the
    fetched holdout rows are stored but never read.
  - The holdout is opened **once**, only after an ADVANCE and only by owner ADR, with the
    same statistic and threshold.

### D4. Costs (ADR-0015 D2)
- **Commission (IBKR Canada Fixed, US ETFs; read 2026-10-10 from
  interactivebrokers.ca/en/pricing/commissions-stocks.php):**
  - $0.005 per share, **$1.00 minimum per order**, capped at 1% of trade value.
  - Whole shares are modelled. Fractional-share rules are rechecked before any paper ADR.
- **Spread and open slippage:** **3 bps per side**, conservative (these ETFs usually quote
  1-cent spreads, under 1 bp). Shown at 2× as a descriptive row.
- **Account:** $5,000 (owner Q2), so about $1,250 per position.
- **Cash account:** T+1 settlement does not bind monthly trades. FX conversion is excluded
  (USD funds assumed) and disclosed.

### D5. Statistic and outcomes (one registered run = 1 test)
- **Statistic:** Δ = Sharpe(strategy) − Sharpe(benchmark), from monthly net returns in excess
  of T-bills, annualised.
- **Uncertainty:** a moving-block bootstrap over months (block = 12 months, 2,000 reps, a fixed
  seed). Both series are resampled on the same months (paired).
- **Development outcome:**
  - **ADVANCE:** one-sided 95% lower bound of Δ > 0;
  - **KILL:** two-sided 95% upper bound of Δ < 0;
  - **AMBIGUOUS** otherwise.
- **Guard:** at least 120 development months (expected about 124).
- **Descriptive only:**
  - CAGR, maximum drawdown and worst 12 months for both;
  - time invested, trades per year, costs paid;
  - per-year rows;
  - Δ without 2008;
  - Δ at 2× costs.
- **After the outcome:**
  - **AMBIGUOUS or KILL:** the idea stops, with no variants (the budget allows them, but this
    ADR does not).
  - **ADVANCE:** a holdout ADR, then a paper-only ADR with 60+ sessions, then the owner
    decides (ADR-0015 D4).

## Consequences
- **New code, tests first:**
  - `ingestion/tiingo.py` and `fred.py`;
  - `strategies/trend.py`;
  - a `study_etf_trend` config block.
- **Reused:** the registry, holdout-guard pattern, moving-block bootstrap and report style.
- **ADR-0015 ledger:** after the registered run, 1 of 10 tests used; data spend $0 for this
  study.
