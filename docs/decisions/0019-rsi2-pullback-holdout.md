# ADR-0019: Holdout confirmation of the RSI(2) pullback rule on SPY (M27, gate 2)

- Status: **ACCEPTED** 2026-10-13 by the owner ("approve, go ahead"), including the H4
  interpretation. Follows the M27 development ADVANCE (ADR-0018 D5; run
  `screen_pullback-287844c815ca`, code 8f2bedf).
- Gate: ADR-0015 D4 gate 2, "one holdout confirmation on untouched data".
- Budget: **no new test.** This is the second gate of the same test (3 of 10). The registry
  will still record it as a run, and n_trials on the 2016–2026 window rises from 40 to 41.
- **State before access (verified 2026-10-13):**
  - `final_test_access_log` is empty;
  - no code has read SPY rows after 2015-12-31;
  - the rows are on disk (Tiingo, fetched 2026-10-13 to 2026-09-30) behind `dev_only`.

## What is being tested
The ADR-0018 rule, **unchanged**: code 8f2bedf `strategies/pullback.py`, `strategies/tom.py`
and the `study_pullback` config. The rule:
- **Buy:** RSI(2) < 10 and close > SMA(200) on the adjusted close;
- **Sell:** close > SMA(5);
- **Orders:** at the next open;
- **Size:** $5,000 per trade in whole shares, 3 bps plus IBKR Fixed per side;
- **Cash:** T-bills.

Nothing about the rule, costs or statistic may change between this ADR's approval and the
run.

## Decision
### H1. Trades in the holdout
- **The rule runs continuously** over 1993 → 2026-09-30, as it would in reality. Indicators
  warm up on earlier data, which is information from the past and allowed.
- **Assignment:** each trade belongs to the period of its **entry signal close**.
- **Holdout trades:** entry signal close ≥ 2016-01-04 (the first 2016 session) and sale open ≤
  2026-09-30.
  - A trade crossing 2015/2016 belongs to neither period.
  - A trade still open at 2026-09-30 is excluded.
  - Because the state machine is continuous, a position from late 2015 can block early-2016
    signals, exactly as in reality.
- **Expected:** about 85 trades (8 a year × 10.75 years).

### H2. Data checks first, in the same access
On holdout rows only, with the same thresholds as before (ADR-0016 A1, ADR-0017 D2, ADR-0018
D2):
- (a) completeness vs XNYS;
- (b) adjustment consistency (closes);
- (c) jumps over 15%;
- (d) 4 dividends per full year, 2016–2025;
- (e) SPY vs Shiller (prices; trailing dividends where Shiller has data);
- open-ratio and open-gap checks.

**Any failure stops the run before any strategy statistic is computed.** The holdout still
counts as opened. The failure goes to the owner, and **no exception may be granted afterwards
without a new ADR that says the holdout result is then descriptive only.**

**Amendment A1 (2026-10-13, before any access; owner to confirm with the commit):** the Yale
Shiller file (`ie_data.xls`, fetched 2026-10-13) ends in 2023: prices at 2023-09 and dividends
at 2023-06. Only the file's month labels and missing values were inspected; no SPY holdout row
was read.
- Check (e) covers prices **2016-01 → 2023-09** and trailing dividends **2016-01 → 2023-06**.
- **2023-10 → 2026-09** gets checks (a)–(d) and the open checks only.
- No threshold changes.

### H3. Statistic and outcome (frozen; ADR-0018 D5)
- **Statistic:** the mean net excess return per trade, with a circular moving-block bootstrap
  over trades in time order (block 12, 2,000 reps, the fixed seed).
- **Outcome:**
  - **PASS:** one-sided 95% lower bound > 0 **and** ≥ **60** holdout trades;
  - **KILL:** two-sided 95% upper bound < 0;
  - **NOT CONFIRMED:** anything else, including fewer than 60 trades.
- **Only PASS opens gate 3.** KILL and NOT CONFIRMED both stop the idea for good, with no
  variants, re-runs or extensions of the holdout.
- **Power (estimated before access, from development trade variability, sd ≈ 1.7% per
  trade):** with about 86 trades, a true mean equal to the development +0.54% passes about
  90% of the time. At +0.40% it passes about 72%, at +0.27% about 42%, and with no effect
  about 5%. **If the edge has halved since publication, a fail is more likely than not.**

### H4. Multiple testing (ADR-0015 D3)
ADR-0015 D3 says results overlapping 2020–2026 are "judged against the combined count" (40
earlier trials, plus this one). **Proposed interpretation, owner to confirm:**
- The **selection** multiplicity was handled at development. The M27 lower bound stays above 0
  even with a Bonferroni correction for all 43 trials (+0.14%).
- The holdout is then **one pre-specified hypothesis on fresh data**, so its own one-sided 95%
  threshold has a 5% false-pass rate. Correcting it again for 41 trials would double-count and
  cut its power to near zero.
- **The report will also show the holdout lower bound at the combined-count level** (one-sided
  1 − 0.05/41), as a descriptive row labelled as such.

### H5. Access mechanics (code, tests first, before the run)
- **A new `scripts/m27_holdout.py`:**
  - refuses to run if any `screen_pullback_holdout` run already exists in the registry, so it
    can run only once;
  - registers the run with `touches_final_holdout = true` **before reading**;
  - logs the access through `HoldoutGuard` with `adr_ref = "ADR-0019"` and a justification;
  - only then reads rows after 2015-12-31.
- **A holdout loader** (`etf_data.holdout_rows`) that requires an ADR reference.
  - `dev_only` stays unchanged.
- **The script is committed (owner OK) and tested only on synthetic data first.**
  - The real run happens from that commit, then the M27 hand check: an independent rebuild of
    every holdout trade.
- **Report:** `reports/research/m27_holdout.md`, with the same descriptive rows as development
  plus a development-vs-holdout comparison.

### H6. After the outcome
- **PASS:**
  - a **paper-only ADR** (ADR-0015 D4 gate 3): 60+ sessions, paper orders only, with no live
    orders and no live-order code (hard rule 1);
  - the paper ADR also settles **position size**, which ADR-0015 D3's 3%-a-day limit makes
    necessary (full size breached it on 6 development trades), and IBKR's settlement rule for
    the cash account.
- **NOT CONFIRMED or KILL:** M27 closes. ADR-0015 ledger: 3 of 10 tests used. The owner
  decides whether the mission continues.

## Consequences
- **One-way door.** After this run, no clean SPY data is left for any SPY daily-price idea in
  this mission. Later SPY ideas would need data after 2026-09-30, meaning paper or forward
  data only.
- The result is reported as evidence with uncertainty, not as a claim of profitability (hard
  rule 12).
