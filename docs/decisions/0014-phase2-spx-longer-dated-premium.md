# ADR-0014: Phase 2, longer-dated defined-risk index premium (SPX), model-free screen first

- Status: **ACCEPTED** 2026-10-08 by the owner ("agree to all, go ahead and proceed"), with
  resolutions R1–R9 below. Drafted 2026-10-08 at the owner's request, after Phase 1 was closed
  (`reports/research/phase1_synthesis.md`).
  - Purchases still need the owner's approval of the exact Step-0 quote (R8).
- Date: 2026-10-08
- Milestone: M23 (placeholder). It is a new project inside this repository. Phase 1 stays
  closed. M20–M22 stay blocked.
- Amends: nothing in PHASE_1_SPEC. This project gets its own spec section (`study_2a` in
  config) and reuses the engine where it applies.
- **Disclosures:**
  - Drafted after every Phase 1 family failed on QQQ 0–1DTE.
  - The motivation is the general literature: the variance risk premium is usually reported to
    be larger relative to costs at about one-month tenors. **This is not verified here.** It is
    the hypothesis being tested.
  - SPX and QQQ are highly correlated, and the Phase 1 window (2020–2026) has been looked at
    through QQQ by 39 trials. SPX data over the same dates is new data for this instrument,
    but **not independent evidence about the market**. See D7.
- Registry at drafting: 39 trials on the Phase 1 development window.
- Disclosure (R1–R9): the resolutions were chosen after Phase 1's results were known. No SPX
  data or SPX outcome had been looked at.

## Context
- **What Phase 1 found:** no edge in 0–1DTE QQQ premium, bought or sold.
  - Short structures lost more often than their credit allowed.
  - Costs of $2.80–$5.60 per round trip were large relative to $0.20–$0.33 credits on a $1 width.
- **The hypothesis:** at 7–45 days to expiry, the credit per unit of risk is larger, gamma is
  lower, and the round trip is a smaller fraction of the premium. If a variance premium exists
  and survives costs, it is more likely to show there than at 0–1DTE.
- **Why SPX:** SPX options are cash-settled and European. That removes early exercise and the
  ex-dividend handling (ADR-0013 D1.d).
  - It also brings new mechanics: SPX and SPXW roots, AM vs PM settlement, 5-point strikes and
    index-option fees.
  - These are **to be verified in Step 0**, not assumed (hard rule 9).

## Decision

### D0. Order of work (as ADR-0013)
- **Step 0 (no trial):**
  - verify data coverage and mechanics;
  - get a cost quote; purchase only with owner approval;
  - build and clean the data; write a coverage report.
- **Step 1 (1 registered screen):** a model-free screen of the frozen cells (D4).
- Filters and models come only after an ADVANCE, under their own ADR.
- Hard rules 1–12 apply unchanged: research only, no order code, point-in-time, no tuning on the
  holdout.

### D1. Instrument and data (Step 0 verifies each item; any failure → stop and report)
- **Instrument:**
  - SPX index options, roots SPX (monthly, AM-settled) and SPXW (weeklies and dailies,
    PM-settled), as listed in the vendor definitions.
  - XSP (mini, 1/10 the size) is the alternative if the owner prefers a smaller capital scale
    (Q1).
- **Vendor:** Databento OPRA cbbo-1m and definitions. To be verified:
  1. SPX/SPXW coverage and its start date in `OPRA.PILLAR`;
  2. the strike grid (expected 5 points near the money; Step 0 measures it);
  3. quote quality versus QQQ.
- **Underlying:** not needed for pricing or labels. Credit-fraction selection needs no spot
  (ADR-0013 D1.a).
  - The download band needs a daily SPX range. Its source is an open item: an index feed, or SPY
    as a proxy for storage scope only (Q6).
  - A proxy may never enter a label.
- **DQ:** the M4 rules apply, with `dq.option_root` extended to the SPX roots. The strike
  increment and the multiplier evidence (ADR-0005) are re-established for SPX in Step 0.

### D2. Trade definition (common to all cells)
- **Structure:** a defined-risk credit spread of width W index points (Q2), on one expiry chosen
  by rule.
  - Short strike: the furthest out-of-the-money strike whose conservative credit (short bid −
    long ask) is ≥ X × W.
  - Long strike: short ∓ W.
  - No qualifying pair, or a pick at the edge of the stored band → NO_TRADE (logged), as in
    ADR-0013 R1/R2 and the M19T leakage fix.
- **Expiry:** the listed expiry whose calendar days to expiry is closest to the target
  (7 or 30); ties go to the earlier one. Chosen from definitions known at T_e.
  - Both roots are eligible.
  - An expiry with no listed contracts at T_e cannot be chosen.
- **Entry:** once per session at 10:00 ET (T_e = T + `fills.latency_s`).
  - R1 gates apply after selection; the min-bid gate applies to short legs only.
  - Conservative, moderate (α = 0.5) and mid fills, 1 contract.
- **Exit:**
  - No stop and no target.
  - Every leg is closed at **15:45 ET on the last session before the expiry session**
    (close − 15 min on early-close days). The position is never held into settlement, so AM
    vs PM settlement and the settlement value never enter a label.
  - Conservative fill: buy back the short legs at the ask, sell the long legs at the bid.
  - A missing bid counts as 0. A missing ask, a stale exit quote, or an RTH quote gap longer than
    the configured maximum gives UNRESOLVED_DATA.
- **Costs:** per contract per leg on open and on close: commission, plus exchange and regulatory
  fees for index options.
  - The values come from the owner's broker schedule, set in config before Step 1 (Q3).
  - Index-option fees are believed to be higher than equity-option fees; this is not verified.
- **Overlap:** 30-DTE positions entered daily overlap about 20-fold.
  - The unit of analysis is the entry session's trade.
  - Uncertainty comes from a moving-block bootstrap over sessions, with block length ≥ 2 × the
    cell's holding period (D5).
  - Any later model step purges labels whose holding periods overlap a fold boundary.

### D3. Data roles and holdout
- **Development:** from the verified data start (D1) to the session before the project
  holdout.
- **Project holdout:** the last 12 months of the data on disk at acceptance. It is locked
  under ADR-0011 rules: one access, for a configuration that passes every development gate, by
  owner ADR.
- **Phase 1 holdout:** it covers 2026-04-03 → 2026-10-02 and was never read. That doesn't make
  those dates independent of the overlapping SPX dates. The project holdout is chosen by date,
  not by which product was looked at.
- **Forward data** is collected only after a cell ADVANCES, after owner approval of a monthly
  cost.

### D4. Candidate cells (frozen at acceptance; nothing added after any result)
| cell | target DTE | structure | X | entry | exit |
|---|---|---|---|---|---|
| L1 | 30 | put credit spread | 0.20 | daily 10:00 | 15:45 on the session before expiry |
| L2 | 30 | iron condor | 0.15 per side | daily 10:00 | same |
| L3 | 7 | put credit spread | 0.20 | daily 10:00 | same |
| L4 | 7 | iron condor | 0.15 per side | daily 10:00 | same |

- A condor is both sides or NO_TRADE (as M19T).
- **Rationale:**
  - Tenor is the main fork (the literature's one-month premium versus a weekly).
  - Puts are primary because of skew. The condor tests whether the call side adds return per
    unit of risk.
  - X is the credit-fraction rule from M19T, so cells stay comparable. A lower per-side X keeps
    condor risk similar.
- Owner review of the cells is Q4.

### D5. Screen statistic and outcomes (as ADR-0013 D3, adapted for overlap)
- **Statistic:** mean net P&L per entered trade.
- **Uncertainty:** a moving-block bootstrap over sessions, 2,000 reps, block length ≥ 2 × the
  holding period, and one shared draw set across cells.
- **Cell outcomes:**
  - ADVANCE: one-sided 95% lower bound > 0 at the conservative fill, with the guards met;
  - KILL: two-sided 95% upper bound < 0 at the mid fill;
  - AMBIGUOUS otherwise.
- **Family outcome:**
  - ADVANCE: at most 1 cell, by the largest lower bound;
  - KILL: every cell is KILL;
  - AMBIGUOUS: one pre-registered re-screen after ≥ 250 new development sessions, then PARKED.
- **Guards:**
  - ≥ 300 entries;
  - ≥ 24 independent holding periods (non-overlapping hold lengths in the window);
  - ≥ 3 calendar years of development data.
  - The 30-DTE cells may have **low statistical power**: about 75 independent months in 6 years.
    The report must state the minimum detectable effect before the run (Q5).
- **Report columns:** as ADR-0013 D4, plus per-year rows, a drawdown in units of max risk, and
  the worst single holding period.

### D6. Budget
- Step 1: 1 screen plus at most 1 pre-registered re-screen.
- n_trials is counted on this project's data window and reported **next to the Phase 1 count
  (39)**. Any deflation (DSR/PBO) at a later step uses the larger of the two.

### D7. What this project cannot show
- A positive screen on 2020–2026 SPX would be **development evidence on a period already
  studied through QQQ**. It needs the project holdout or forward data before any claim.
- No result here supports live trading. M20–M22 stay blocked unless a later ADR says otherwise.

## Open questions (owner decides before acceptance)
- **Q1, instrument:** SPX (100× index; a 25-point spread risks up to $2,500) or XSP (1/10 the
  size; liquidity to be checked in Step 0).
- **Q2, width W:** for example SPX 25 points or XSP 5 points. This sets capital per trade and
  how coarse the credit rule is on the strike grid.
- **Q3, costs:** the broker commission and the index-option fee schedule to use, with the
  source.
- **Q4, cells:** keep L1–L4 as drafted, or change the tenors, X or structures before
  freezing.
- **Q5, power:** accept a screen that may come out AMBIGUOUS mainly from low power on the 30-DTE
  cells, or move to fewer, more powerful cells (for example 7 and 14 DTE).
- **Q6, band source:** the daily range used to choose which strikes to download (index data,
  or SPY as a storage-only proxy).
- **Q7, history start:** use the earliest verified SPX coverage, which may go back before 2020,
  if Step 0 shows it is affordable and clean. Earlier years would be the least-touched data.
- **Q8, Step-0 spend cap:** a dollar limit for the price quote → purchase step.

## Resolutions (owner, 2026-10-08; these amend D1–D5 as stated)
- **R1 (Q1), instrument: SPX** (roots SPX and SPXW).
  - Results are reported per contract and per $ of max risk.
  - Step 0 also prices XSP liquidity checks for free (quote metadata only, no purchase).
  - **Confirmed after the SPX vs SPY comparison (owner, 2026-10-09, "option 2"): SPX.**
    - Evidence (`reports/research/m23_spx_vs_spy.md`): 30 development sessions, entry quotes
      only, $0.0659 approved and spent.
    - On bid–ask alone, SPY is about 30% cheaper relative to the credit (7 DTE 8.1% vs 11.5%;
      30 DTE 13.7% vs 18.3%).
    - Per-contract commissions reverse that at equal dollar risk: about 1–2% of the credit for
      SPX versus about 10% for a $1 SPY spread, at illustrative rates. The SPX index fee is not
      yet verified (R3).
- **R2 (Q2), width W scales with the index:** W = 0.5% × the previous session's SPX close,
  rounded to the nearest listed strike step, minimum 10 points.
  - The previous close is known before entry, so W is point-in-time.
  - The close comes from the R6 source.
- **R3 (Q3), costs:**
  - **Commission:** the owner's broker SPX commission, supplied with its source.
  - **Fees:** Cboe's published SPX fees, fetched in Step 0 with their source.
  - Both go into config before Step 1. The screen decides at 1.0× costs; a descriptive row
    shows 1.5×.
  - **Broker set (owner, 2026-10-09): IBKR Canada.** Costs per SPX contract per side, USD:
    - **Commission:** IBKR tiered, ≤ 10,000 contracts a month: $0.65 at premium ≥ $0.10,
      $0.50 at $0.05–0.10, $0.25 below $0.05; minimum $1.00 per order (per leg of a combo).
    - **Exchange fee (Cboe SPX customer):** $0.45 at premium ≥ $1, $0.36 below $1 (schedule
      effective 2026-10-01).
    - **Regulatory fees (ORF/OCC/CAT):** cents per contract; included as a config allowance.
    - **Not verified:** whether the Cboe SPX index-license or execution surcharges apply to
      retail customers. Step 1 treats them as an explicit allowance in config, disclosed.
    - **Sources:**
      - interactivebrokers.ca/en/pricing/commissions-options.php (read 2026-10-09);
      - cboe.com/us/options/membership/fee_schedule/cboe/ and Cboe_FeeSchedule.pdf.
    - **Why SPX at IBKR:** at these rates SPX is cheaper all-in than SPY (M23 comparison). At
      a $0-equity-option broker (for example Questrade), SPY would have been cheaper.
- **R4 (Q4), cells:** L1–L4 as drafted.
- **R5 (Q5), power:**
  - The 30-DTE tenor is kept. Power comes from more history (R7), not from changing tenor.
  - Before the screen runs, the report states each cell's minimum detectable effect, so an
    AMBIGUOUS outcome reads as "insufficient data".
- **R6 (Q6), daily SPX range and close:** Cboe's free daily SPX history, verified in Step 0
  with its source.
  - Fallback: SPY × 10, for the download band only. It is never used in a label or in W.
- **R7 (Q7), history:** use the earliest clean SPX coverage within the R8 cap. Report results
  per era (expiration-listing changes) as in M19T.
- **R8 (Q8), Step-0 spend cap: $50.** Price first (free); buy only on the owner's approval of
  the exact amount; above the cap, ask again.
- **R9 (amendment to D2), no quote-gap check during the hold.**
  - These positions have no stop or target, so only the entry and exit quotes affect P&L.
  - A missing or stale entry or exit quote is still UNRESOLVED_DATA, logged and never filled.
  - Step 0 therefore needs only:
    - entry-session quotes for the target expiries;
    - exit-session quotes for the contracts that can be held.

## Step-0 resolutions (owner, 2026-10-09; after `reports/research/m23_data_coverage.md`)
Disclosure: chosen after seeing entry-time quote widths and coverage. No exit price, P&L or
outcome had been computed.

- **R10, SPX liquidity gate.** It replaces the §4.9 spread gate for this project only:
  - each leg's quoted spread must be ≤ 15% of its mid and ≤ 2.00 SPX points;
  - the other gates are unchanged: two-sided quote, quote age ≤ 60 s, size ≥ 1, and min-bid on
    short legs only (R1 of ADR-0013 carried over);
  - it is applied after selection, with no fallback.
  - **Why:** the conservative fill already charges the full spread, so the gate only has to
    exclude broken or unfillable quotes. At the Phase 1 thresholds (spread ≤ max($0.05, 5% of
    mid), calibrated on QQQ in M4), 19.5–81.5% of SPX entries failed on normal spreads
    (0.30–0.85 points, 1–9% of mid).
  - Pass rates under R10 are in the coverage report.
  - Values: `configs/m23_step0.yaml` → `spx_gate`; they move to the Step-1 config.
- **R11, root on a shared expiry date:** when SPX (AM) and SPXW (PM) list the same expiry date,
  the SPXW contracts are used. Positions close on the session before expiry, so settlement style
  never enters a label.
- **R12, power accepted.**
  - Outcome-free MDE upper bounds, per trade: about $149 (L1/L2; 0.50 / 0.31 of the median
    credit) and about $66 (L3/L4; 0.21 / 0.14).
  - **The 7-DTE cells are the primary test.** The 30-DTE cells are expected to be AMBIGUOUS
    unless the effect is large.
  - No cells are added or changed.
  - The Step-1 report adds the realised CI width per cell, so an AMBIGUOUS outcome reads as
    "insufficient data", not as "no effect".

## Consequences
- **New code:**
  - DQ support for SPX roots and the strike grid;
  - expiry selection by target DTE;
  - an exit on the session before expiry;
  - a moving-block bootstrap (tests first);
  - multi-session label spans with the purge rule;
  - W from the previous SPX close (R2).
- **Reused:** the credit-fraction rule and labels (`execution_sim/spreads.py`,
  `labels/spread.py`), the fills, the registry, the holdout guard and the screen logic
  (`backtesting/premium_screen.py`, extended).
- Any change to cells, rules, thresholds or budget after acceptance needs a new ADR.
