# ADR-0015: New mission: a reason-first, cost-first short-term trading strategy

- Status: **ACCEPTED** 2026-10-10 by the owner ("approve"). Drafted from the owner's eight answers
  (Q1–Q8, below).
- Supersedes: the Phase 1 mission statement (`docs/MASTER_PROMPT.md` "IMPORTANT PRINCIPLE";
  `CLAUDE.md` first paragraph), for all work after M23.
  - Every hard rule in `CLAUDE.md` stays in force. In particular: no orders and no order code
    (rule 1) until a separate paper-only ADR; no holdout access except by owner ADR.
- Disclosure: drafted after Phase 1 and Phase 2 found no validated edge (40 registered trials,
  `reports/research/phase1_synthesis.md`, `docs/LESSONS_LEARNED.md`). Its emphasis on costs and
  fills comes from those results.

## Mission
> Find a **short-term trading strategy** (holding from hours to a few weeks) with a **clear
> economic reason to work**, whose edge **survives measured retail costs and fills**, confirmed
> on **untouched data** and in **paper trading**, within a **fixed budget of tests and money**.
> Options are preferred; ETFs are allowed when the evidence after costs is better.

Wording note: the owner's draft said "day-trading strategy". It is widened to "short-term" for
two reasons:
- **Q2 + Q5:** a cash account under $5k, where settlement limits reuse of sale proceeds.
- **Day-trade limits:** IBKR Canada may still apply the old US rule (fewer than 4 day trades in
  5 days under $25k) until 2027-10-20 (FINRA Regulatory Notice 26-10).

Day trading remains allowed when a strategy fits these constraints.

## The owner's constraints (2026-10-10)
| # | question | answer | consequence |
|---|---|---|---|
| Q1 | goal | learn and build skill first, money second | "no edge" is a valid result; no pressure to trade |
| Q2 | account size | under $5,000 USD | ~1–2% per-trade risk is $50–100. SPX/XSP spreads and micro futures don't fit. Fixed per-order costs weigh heavily |
| Q3 | loss limits | 3% per day (~$150); 20% total (~$1,000) | hard caps. Hitting 20% = **stop and review, no top-ups**, new ADR before resuming |
| Q4 | market-hours time | none; fully rule-based | trades must work with orders placed in advance or at set times (open/close, limit, bracket). No discretion |
| Q5 | account type | cash account, basic options (margin possible later) | allowed: buying calls/puts, ETFs. Not allowed: spreads, selling options, futures. Settlement must be modelled. Upgrade only if a passed strategy needs it |
| Q6 | instruments | options preferred, open to ETFs | ideas are ranked by evidence after costs, not by instrument |
| Q7 | budget | $100 of data, at most 10 registered tests | a cap, not a target; each idea declares its share before it runs |
| Q8 | success before real money | development screen + one holdout confirmation + 60+ sessions of paper trading | "it made money last year" is never success |

## Decision
### D1. Reason first
Every candidate idea states, before any data is examined:
- **who pays** the strategy (which market participant, and why they accept it);
- **why it should persist** (a structural or behavioural reason, not a backtest);
- **why it is not already competed away** at this account size.

If an idea can't answer these, it isn't tested.

### D2. Costs and fills first
- **Each idea's costs are modelled before its signal is tested:**
  - the broker schedule (IBKR Canada; R3 of ADR-0014 for index options; the equity/ETF
    schedule to be fetched with sources);
  - bid–ask at **measured** fills (M24 fill-feasibility study for options; quoted spreads for
    ETFs);
  - settlement in a cash account.
- **An idea whose expected gross edge is below its round-trip cost is dropped** without a
  trial.

### D3. Budget and kill rules
- **Research budget:** $100 of data and at most **10 registered tests** (trials) under this
  ADR.
  - Each idea's ADR declares its share up front, for example 2–3 tests.
  - Unused tests stay unused.
  - The fill-feasibility study (M24) is not a trial.
- **Stop rule:** if nothing passes all gates (D4) within the budget, the mission stops. It is
  not extended without a new ADR.
- **Trading loss limits** (paper and any later live): 3% of the account per day, 20% total.
  Hitting 20% stops all trading pending review.
- **Multiple testing:** the 40 earlier trials are recorded. Any result on dates overlapping
  2020–2026 is judged against the combined count.

### D4. Gates (in order; none skipped)
1. **Development screen** at measured costs and fills, pre-registered, one registered run.
2. **One holdout confirmation** on untouched data:
   - QQQ options: 2026-04-03 → 2026-10-02;
   - SPX options: 2025-10-03 → 2026-10-02;
   - for any other instrument (for example ETFs), **the last 12 months are locked before that
     instrument's data is first examined**.
3. **Paper trading for 60+ sessions** under a **separate paper-only ADR**. It allows paper
   orders only: no live orders, and no live-order code.
4. **Small live trading:** the owner's decision alone, outside this project's scope, within
   Q3's limits.

### D5. What stays the same
The Phase 1 engine and process carry over:
- data quality and point-in-time features;
- labels, walk-forward splits and registry;
- holdout guards and leakage review;
- tests first;
- one milestone per session, with plan approval.

## Consequences
- `docs/ROADMAP.md` lists the next study (M24, fill feasibility) and a shortlist of
  reason-first ideas. Each needs its own ADR and budget share.
- M20–M22 stay blocked until an idea passes gate 2. Paper trading then needs the paper-only ADR.
- The owner's account facts (permission level, PDT status at IBKR Canada) are rechecked before
  any paper-trading ADR.
