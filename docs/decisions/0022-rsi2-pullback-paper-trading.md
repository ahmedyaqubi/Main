# ADR-0022: Paper trading of the RSI(2) pullback rule on SPY (ADR-0015 gate 3; milestone M32)

- Status: **ACCEPTED** 2026-11-15 by the owner ("Accept all recommendations, M32, $2,500";
  then, after the assistant clarified that this ADR trades SPY shares, not options: "Yes
  $2,500, record the answers and mark it accepted"), at revision 2 with OQ1–OQ7 answered as
  recorded below. Revision 1 was the owner's draft of 2026-10-13.
- It follows the M27 holdout **PASS (borderline)**: ADR-0019 with the ADR-0020 exception, run
  `screen_pullback_holdout-7e393c248e95` (`reports/research/m27_holdout.md`).
- Gate: ADR-0015 D4 gate 3, "paper trading for 60+ sessions under a separate paper-only ADR".
  ADR-0019 H6 names this ADR and says it must also settle position size and the cash
  account's settlement rule.
- **Milestone: M32 (owner, OQ1).** Revision 1 called this "M28".
  M28–M30 have since been used by ADR-0021, and ADR-0021 D11 names M31 for that mission's
  holdout ADR and access.
- **Budget: no test is used, no data is bought.** Tiingo daily prices and FRED are free.
  ADR-0015 ledger, derived from the records: 5 of 10 tests used (3 before ADR-0021, plus
  M29 and M30), and $36.17 of $100 spent ($28.51 to M27, plus $7.66 approved in M28 step 5).
- **Hard rule 1 stands in full:**
  - this project places **no orders of any kind**, real or paper;
  - it opens **no connection of any kind to a broker API**: not for orders, not for market
    data, not for account data, live or paper;
  - it contains **no order-routing code**.
  The **owner** enters every paper order by hand in an IBKR **paper** account. The software
  only writes instructions and keeps the journal.

## Where this ADR sits (state on 2026-11-15)
- **ADR-0021** (accepted 2026-11-14) replaced ADR-0015's mission statement for work after M27.
  ADR-0015's gates, loss limits and budget stay in force except where ADR-0021 says so.
  - Its outcome so far: **S1 AMBIGUOUS** (M29), **S2 KILL** (M30). **1 of its 3 tests is
    unused**, reserved for S3, which needs an amendment before any data is examined for it.
  - ADR-0021's Consequences say: "The M27 pullback result is unaffected. Its paper-only ADR
    remains available to the owner and is the cheaper path to a first paper executor."
    This is that ADR.
- **How this ADR relates to ADR-0021:**
  - It uses **none** of ADR-0021's tests, data, tickers or setups, and changes nothing in it.
  - It is **not** ADR-0021's D9 stage 2. That stage is an options executor that runs
    **unattended** and needs its own paper-only ADR. Here the owner places every order by
    hand, on SPY shares, about 8 times a year.
  - What it can give ADR-0021 later: a tested journal, a tested evening routine, and
    measured paper fills and commissions at IBKR. Reusing any of it for options needs that
    later ADR.
  - P5's forward record is in the spirit of ADR-0021 D10's shadow book, but D10 covers
    ADR-0021's setups. A forward record of this rule is decided here (OQ6), not under D10.
- **Trial count:** 44 registered trials are recorded in the registry after M30 (M30: n_trials
  43 → 44). The M27 holdout was judged at its own pre-registered level (ADR-0019 H4); its
  lower bound at the combined count of 42 was **−0.184%** (descriptive). At 44 it would be
  lower still (not computed). Paper trading registers **no trial**: no statistic from it
  decides anything about the edge.

## What paper trading can and cannot show (read first)
- **It cannot confirm the edge.** The rule trades about 8 times a year, so 60 sessions (about
  3 months) gives only **about 2 trades**. Even 10 trades would leave an uncertainty of about
  ±1.1% on the mean, far wider than the +0.27% being tested. The paper P&L is reported, but it
  **is never a pass/fail criterion**.
- **The evidence it rests on is thin and is stated again here:**
  - holdout mean +0.271% per trade, one-sided 95% lower bound **+0.010%** over 91 trades;
  - across 100 other bootstrap seeds that bound is above 0 for **51%** of them: a
    coin-flip-level pass at the 95% line (`docs/MILESTONES.md`, M27);
  - the pass relies on the disclosed ADR-0020 exception;
  - the holdout edge is about half the development figure (+0.541%).
- **It can test the parts of the backtest that are assumptions:**
  - that the owner, with no market-hours time, can act on every evening signal;
  - that market-on-open orders fill near the official open (in IBKR's simulation; see below);
  - that commissions match the modelled IBKR Fixed share commission;
  - that the cash account's settlement never blocks a trade;
  - that the live signal pipeline reproduces the frozen rule exactly.
- **Paper fills are IBKR's simulation**, not real auction fills, and that is disclosed. How
  IBKR's paper account simulates a market-on-open fill is **not verified**. Real fill quality
  is only known with real orders, which is outside this project (gate 4).

## Decision
### P0. What is tested (frozen; unchanged)
The ADR-0018 D1 rule exactly as run in M27: `strategies/pullback.py` and the `study_pullback`
config at the M27 holdout code (c5f65ca). RSI(2) < 10 and close > SMA(200) to buy; close >
SMA(5) to sell; every order at the next session's open. **This ADR adds no trading rule and
changes none.** Only the dollar amount per trade is set here (P2), as ADR-0019 H6 requires.

### P1. Prerequisites (before the first session; ADR-0015 Consequences)
**What M28 and earlier milestones verified on IBKR's own pages, and what is still open.**
"Verified" means read on the page named in the cited report; nothing here was re-read today.

| item | status | source |
|---|---|---|
| The owner's account is Canadian | **owner-stated** 2026-11-14 | ADR-0021 amendment A1 |
| Account type is a cash account | **owner-stated** (ADR-0015 Q5); not re-confirmed since 2026-10 | ADR-0015 |
| A paper account needs the live account approved and funded | **verified** 2026-11-14 | `reports/research/m28_steps1_3.md` |
| "Read-Only API" is on by default and blocks all API orders | **verified** 2026-11-14 | same |
| Paper ports TWS 7497 / IB Gateway 4002 | **verified**; **not used**: this project opens no broker connection | same |
| US ETF share commission, IBKR Canada **Fixed**: $0.005 a share, $1.00 minimum per order, capped at 1% of trade value | **verified 2026-10-10**, not re-read since | ADR-0016 D4 (interactivebrokers.ca commissions-stocks page) |
| The $1.00 a side M28 found is for **one option contract**. For SPY shares the figure is the share commission above: under 200 shares the $1.00 minimum applies, so $1.00 a side | derived from the two rows above | — |
| Whether the owner's account is on the Fixed or Tiered share plan | **not verified** | OQ3 |
| Regulatory and pass-through fees on share sales under Fixed (SEC fee, FINRA TAF) | **not verified**; expected to be cents | OQ3 |
| Cash account: "full payment is required" for purchases; option sale proceeds available one business day after trade date | **verified for options only** | `reports/research/m28_steps1_3.md` |
| Settlement of **ETF share** sales in a Canadian cash account (expected T+1) and when the cash can be reused | **not verified** at IBKR. ADR-0018 D1 flagged it | OQ4 |
| Market-on-open orders (IBKR "MKT" with time in force "OPG") for SPY, placed the evening before, in the paper account | **not verified** | owner checks in the paper account before session 1 |
| Whether the paper account models cash-account settlement, or behaves as margin | **not verified** | OQ4 |
| Whether the paper account's balance can be set to $5,000 | **not verified** | OQ5 |
| Account currency: USD funding; FX excluded as in ADR-0018 | **owner to confirm** | — |

- **The rule never needs same-day reuse of sale proceeds.** A sale at an open is never followed
  by a buy before the next session's open (ADR-0018 D1). So an unverified settlement detail
  can block a trade only if settlement is slower than T+1.
- **Rule 9:** before the first session the owner confirms each "not verified" row, without
  sharing credentials, account numbers or screenshots that show them. The answers are recorded
  in the milestone report. If any answer contradicts ADR-0018's assumptions, paper trading does
  not start until an ADR addresses it.
- **Read-Only API:** the owner is asked to leave it on (its default). This project never needs
  it off, because it never connects.

### P2. Position size (owner, OQ2: option A, $2,500 per trade)
ADR-0015 D3 sets a limit of 3% of the account per day. ADR-0021 D2 replaced that figure for
**options entries only**; for this rule it still applies. At full size ($5,000), the rule broke
it on 6 development trades (worst day −6.5%) and 3 holdout trades (worst −4.4%).
- **Option A: half size ($2,500 per trade). Chosen by the owner, 2026-11-15.**
  - The holdout worst day would have been −2.2% of the account, and the development worst
    −3.2%.
  - Costs are about $3.50 per round trip (0.14%), against 0.10% at full size.
  - In the holdout data, the expected net edge falls from about +0.27% to about +0.23% per
    trade.
- Option B: full size ($5,000), with the 3% limit as a stop-and-review trigger.
- Option C: a smaller size ($1,500). Costs rise to about 0.19% per round trip and eat most of
  the edge.

Whole shares only (ADR-0018 D1): with SPY at about $715–830 in 2026 (6 shares per $5,000 in the holdout table), $2,500 buys 3 shares and $1,500 buys 1 or 2,
so the money invested is often well under the target. The figures above are revision 1's
arithmetic and were not recomputed for this revision.

The rule itself is unchanged (ADR-0018 D1); only the dollar amount changes.

### P3. Daily procedure (no market-hours time)
1. **Each evening after the US close**, the owner runs `scripts/m32_evening.py`, which:
   - fetches SPY daily prices from Tiingo (free key in `.env`, as M25–M27; the key is sent in a
     header and never printed or logged) and checks that today's bar is final;
     - *not verified:* how soon after the close Tiingo's end-of-day bar is final. The script
       refuses rather than guesses (rule 9);
   - **refuses** if today's session is missing or the new rows fail the M26/M27 checks;
   - computes RSI(2), SMA(200) and SMA(5) with the **frozen code** (P0);
   - writes a one-line instruction: **"BUY n SPY market-on-open"**, **"SELL n SPY
     market-on-open"** or **"NO ACTION"**;
   - writes a journal row with the data timestamp, the signal values and `available_at`.
2. **The owner places the order by hand** in the IBKR paper account (market-on-open, the next
   open) that evening, or before the open.
3. **After the fill,** the owner records it with `scripts/m32_record_fill.py`: fill price,
   quantity, commission and time, typed in or from an IBKR paper CSV export that **the owner
   downloads**. The script keeps only those fields and never stores an account number.
4. **The software compares** each fill with the official open (Tiingo, next evening) and with
   the modelled cost.

A missed evening is recorded as missed, never backfilled. If a missed signal means a position
is not entered, it stays not entered (rule 8).

### P4. Duration and pre-registered operational criteria
- **Duration:** at least **60 sessions** from the first session after the prerequisites are
  confirmed, **and** at least **5 completed round trips (10 orders)**, so the fill and cost
  checks have data.
  - **At about 8 trades a year, that probably means 7–9 months**, not 3. The 60 sessions are
    ADR-0015's minimum; the round-trip count is what lets the operational checks mean
    anything.
- **Pass criteria, all required; operational only:**
  1. **Signal fidelity:** every journal signal equals an independent recomputation from the
     same data, with 0 mismatches.
  2. **Execution discipline:** ≥ 95% of signals placed for the intended open. Every miss is
     logged with its reason.
  3. **Fill quality:** the mean |paper fill − official open| ≤ 5 bps, and no single fill more
     than 25 bps away.
  4. **Costs:** commission per order within $0.10 of the IBKR Fixed model.
  5. **Settlement:** zero rejected orders or settlement or good-faith violations.
     *If the paper account does not model cash settlement (P1, OQ4), this criterion cannot
     fail in paper and says nothing; OQ4 asks how to treat it.*
- **Loss limits (ADR-0015 D3) apply to the paper account:** 3% of the account in a day, or 20%
  in total, stops paper trading for review. Any restart needs a new ADR. Percentages are of
  $5,000 (ADR-0021 OQ1), whatever balance the paper account shows (OQ5).
- **Reported, never a criterion:** paper P&L per trade and in total, compared with the
  backtest's distribution (the holdout trades) as context.

### P5. After paper trading
- **All criteria met:** the milestone report goes to the owner. **Gate 4 (small live trading)
  is the owner's decision alone**, outside this project (ADR-0015 D4). The project still writes
  no live-order code, and hard rule 1 is unchanged unless a later ADR changes it.
- **Any criterion failed:** the cause is reported. Fixing it, for example by changing the
  order type, needs a new ADR and a fresh 60-session paper period.
- **Forward record (OQ6):** after the paper period, the evening script can keep running in
  **shadow mode**, signals and modelled results only, with no orders. That builds a growing
  out-of-sample record. At about 8 trades a year, a meaningful statistical re-check takes
  years, and that is disclosed.

### P6. Code (tests first; reviewed before use)
- **`scripts/m32_evening.py`:**
  - signals and instructions;
  - journal rows in PostgreSQL with `available_at`;
  - Tiingo fetch with the token in a header.
- **`scripts/m32_record_fill.py`:** owner-entered fills, validated with logged reasons
  (rule 8).
- **`scripts/m32_review.py`:** the criteria above → `reports/research/m32_paper.md`.
- **Tests:**
  - the live signal path equals the backtest functions on a replayed history;
  - instruction text for each state;
  - refusal on missing or late data;
  - criteria computation on synthetic journals;
  - the fill parser keeps no field beyond those listed in P3.
- **Static check:** no broker SDK imports (for example `ibapi`, `ib_insync`, `ib_async`), no
  broker order or account endpoints, and no reference to IBKR API ports 7496, 7497, 4001 or
  4002 anywhere in the code (a test, as the Phase 1 rule-1 guard).
- Script names use M32 (OQ1).

## Owner's answers (2026-11-15: every recommendation accepted)
- **OQ1. Milestone number. ANSWERED (owner, 2026-11-15): as recommended.** M28–M30 are used. ADR-0021 D11 names M31 for its holdout ADR
  and access "if a setup advances". S1 and S2 did not; M31 could still be used only if S3 is
  specified by amendment, screened and advanced.
  - **Recommended: M32**, leaving M31 to ADR-0021 as written, so no accepted text has to be
    reinterpreted.
  - Alternative: M31, with ADR-0021's holdout work renumbered if it is ever needed.
- **OQ2. Position size. ANSWERED (owner, 2026-11-15): $2,500 per trade, confirmed after the clarification that the trade is in SPY shares.** **Recommended: option A, $2,500 per trade** (P2), the only option that
  keeps both the development and holdout worst days inside ADR-0015's 3%.
- **OQ3. IBKR share pricing plan. ANSWERED (owner, 2026-11-15): as recommended.** The cost model is the Fixed plan (ADR-0016 D4, read
  2026-10-10). **Recommended:** the owner confirms which plan the account is on, and the
  commission page is re-read and recorded before session 1. If the account is on Tiered, the
  modelled cost and criterion 4 are restated by amendment **before** session 1, not after.
- **OQ4. Settlement in the paper account. ANSWERED (owner, 2026-11-15): as recommended.** It is not verified whether IBKR's paper account
  enforces cash-account settlement. **Recommended:** the owner checks the paper account's type
  in its settings. If it does not model cash settlement, criterion 5 is marked "not testable
  in paper" in the report, and the software also keeps its own settled-cash ledger from the
  journal and reports any trade that would have used unsettled cash. Neither may count as a
  pass by itself.
- **OQ5. Paper account balance. ANSWERED (owner, 2026-11-15): as recommended.** IBKR paper accounts may not start at $5,000 (not verified).
  **Recommended:** the owner sets it to $5,000 if IBKR allows it; if not, the software
  computes every limit and P&L share on a notional $5,000 and the report says so.
- **OQ6. Forward record after the paper period. ANSWERED (owner, 2026-11-15): as recommended.** **Recommended: yes**, shadow mode from the
  last paper session, no orders, reported yearly with its sample size. It costs nothing and is
  the only new out-of-sample evidence this rule can get, since ADR-0019's Consequences note no
  clean SPY daily data is left.
- **OQ7. Running it beside ADR-0021. ANSWERED (owner, 2026-11-15): as recommended.** ADR-0021 has one test left (S3). **Recommended:** run
  this paper period regardless of S3; the two share no data, tests or account (this is a paper
  account; ADR-0021 trades nothing yet). The owner's evening time is the only shared cost, at
  about 5 minutes on signal evenings.

## Consequences
- **M20–M22** (Phase 1 live/paper/dashboard, options) stay closed. This is a new, ETF-only
  milestone.
- **Owner's time:** about 5 minutes on evenings with a signal or an open position. On other
  evenings, a quick check that the instruction says NO ACTION.
- **ADR-0015 ledger unchanged by this ADR:** 5 of 10 tests, $36.17 of $100.
- **ADR-0021 unchanged:** its stage 1b recorder and any stage 2 executor still need their own
  conditions and ADRs. Nothing here builds a broker connection for them.

## Changes from revision 1 (2026-10-13)
- Milestone "M28, gate 3" → gate 3 with **M32 proposed** (OQ1); script and report names
  follow it.
- Added "Where this ADR sits": ADR-0021, its S1 AMBIGUOUS / S2 KILL outcome with 1 of 3 tests
  unused, the relation to D9 stage 2 and D10, and the trial count of **44**.
- Budget line: 3 of 10 → **5 of 10** tests and $28.51 → **$36.17** (derived; unchanged by this
  ADR).
- Hard rule 1: "no connection to any broker order API" widened to **no connection of any kind
  to a broker API** (no market-data or account connection either), with a static check on
  IBKR's API ports.
- P1 rewritten as a table: each IBKR fact marked verified (with its source and date),
  owner-stated, or **not verified**. The M28 "$1.00 a side" is for one option contract; SPY
  shares use the share commission, which hits the same $1.00 minimum at this size.
- Restated the M27 fragility (51% of seeds) next to the power statement, which is kept.
- P2: noted whole-share granularity; numbers left as revision 1 computed them.
- P3: Tiingo bar timing marked not verified; fill CSV keeps no account number.
- P4 criterion 5: flagged that it may be untestable in paper (OQ4); loss limits tied to a
  notional $5,000 (OQ5).
- Added P0 (the frozen rule, unchanged) and the open questions OQ1–OQ7.
- **Not changed:** the ADR-0018 rule, its costs model, the 60-session and 5-round-trip
  duration, the five operational criteria and their thresholds, and the statement that paper
  P&L is never pass/fail.

## Revision 2 → accepted (2026-11-15)
- Status set to ACCEPTED; OQ1–OQ7 answered as recommended; P2 records option A ($2,500).
- No other text changed.
