# ADR-0021: New mission: an autonomous options day-trading agent (long calls and puts first)

- Status: **PROPOSED** 2026-11-13. Drafted by the assistant at the owner's request ("re-strategize
  this whole idea for options day trading; calls and puts mainly, spreads as back-up; start with
  a small funded account"). **Not in force until the owner accepts it and answers OQ1–OQ7.**
- Supersedes, if accepted: the ADR-0015 mission statement, for all work after M27.
  - ADR-0015's constraints Q1–Q8, budget and gates stay in force except where this ADR says so.
  - **Every hard rule in `CLAUDE.md` stays in force, rule 1 included.** This ADR authorises
    research only. It does not authorise orders, paper orders, or order code (see D8).
- Milestones: M28 onward (D9).
- **Disclosures:**
  - **The assistant advised against this direction before drafting it.** The project's own
    evidence is against daily options trading (below). The owner chose to proceed.
  - **Buying QQQ options was already tested and failed.** M19 (FAIL), M19R (no validated edge
    in move size or direction) and M19S (kill rule) all studied long calls and puts on QQQ
    1DTE. `docs/LESSONS_LEARNED.md` finding 1: option prices already reflected how far QQQ
    would move; best direction accuracy was 0.557 against a required 0.57–0.65.
  - **The inputs of the setups below are not new to this data.** `or_position` (opening range)
    and `overnight_gap` were features of the models that failed (`docs/FEATURES.md` #5, #6), and
    the macro calendar drove the event flags. What is new is the form: a few named rules on a
    few days, not a model at every timestamp. That is a weaker claim than "untested".
  - **The development sessions are heavily used:** 40 registered trials overlap 2020–2026, plus
    2 on SPY. Results here are judged against that count (D6).
  - **M24 measured fills:** a limit at the mid, then chasing, cost 1.35 half-spreads, and fill
    quality in half-spread units got *worse* from 0DTE to 2DTE (0.86 → 1.45 → 1.68). This ADR
    therefore assumes paying the ask and selling at the bid, and never relies on mid fills.
  - The setups come from published work, which the assistant knows along with the broad market
    history of 2023–2026. The protections are frozen rules, a fixed statistic, and one holdout
    access.

## Mission
> Build an **autonomous, rule-based agent** that day-trades **long calls and puts on QQQ**,
> entering only on a **small set of pre-registered setups**, and only if a setup's edge
> **survives ask/bid fills and commissions**, is confirmed on **untouched data** and in **paper
> trading**. The agent improves only through **gated promotion** of new rules. Spreads are a
> later stage, unlocked by account size and their own evidence.

"No setup survives, the agent trades nothing" remains a valid and likely result (rule 10, rule 12).

## The question being tested
A long option pays only when the underlying moves further, in the chosen direction, than the
premium already assumes. Each setup asks: *at this specific, recognisable moment, is the move
that follows large enough to pay for the option at the ask, the exit at the bid, and both
commissions?*

## Decision
### D1. Instrument and contract (frozen)
- **Underlying:** QQQ only.
  - Reason: 1-minute QQQ quotes and 0/1/2DTE option quotes are already owned ($0). SPY is a
    later extension that needs purchased data and its own ADR.
- **Structure:** one long call (up signal) or one long put (down signal). One contract.
- **Entry and exit the same session.** No position is held overnight.
- **Expiry:** 1DTE or 2DTE, chosen once in M28 (D4) by cost alone, before any signal is
  computed. 0DTE is excluded: the premium is small, so spread and commission are a large
  share of it.
- **Strike:** the first in-the-money strike at the entry minute (call: highest listed strike ≤
  spot; put: lowest listed strike ≥ spot), from the quote in force at that minute.
- **Selection and liquidity gates:** `execution_sim/selection.py` and the spec §4.9 gates,
  unchanged. A contract that fails them is NO_TRADE with its reason; no substitute strike.
- **Fills:** conservative only for decisions: buy at the ask, sell at the bid, rounded against
  the trader (spec §6). Moderate and mid fills are reported as descriptive rows.
- **Costs:** `costs.commission_per_contract` and `fees_per_contract` as configured, to be
  re-read from the broker's schedule in M28 (OQ2).

### D2. Setups (frozen; 3 named, 2 reserved)
Times are America/New_York. Every input is available at the entry minute; `available_at <= T`
is enforced through `AsOfReader` as today. At most one trade per setup per session.

| | setup | signal (direction) | entry | exit |
|---|---|---|---|---|
| S1 | Opening-range breakout | first 1-minute QQQ close above the 09:30–10:00 high (call) or below its low (put), between 10:00 and 12:00 | the minute after the signal | 15:45, or earlier when a 1-minute close returns to the range midpoint |
| S2 | Macro-release continuation | on CPI and NFP sessions in `configs/reference/macro_calendar.csv`: sign of the move from the previous close to 10:00 | 10:00 | 15:45, or earlier when a 1-minute close crosses back through the previous close |
| S3 | First-half-hour predicts the last | sign of the move from the previous close to 10:00, every session | 15:30 | 15:55 |
| S4, S5 | **Reserved** | specified by an amendment to this ADR, with its reason, **before** any data is examined for it | | |

Source of each rule (literature, not our data; exact parameters to be checked against the
papers in M28, and any correction made before a signal is computed):
- S1: opening-range breakout day-trading studies on QQQ (Zarattini & Aziz, 2023).
- S2: post-announcement drift after scheduled macro releases.
- S3: Gao, Han, Li & Zhou (2018), "Market intraday momentum".

The assistant's earlier chat proposal listed a gap setup as a fourth. It is not named here
because it cannot answer ADR-0015 D1 ("who pays") convincingly.

### D3. Reason first (ADR-0015 D1)
| | who pays | why it may persist | why it may fail here |
|---|---|---|---|
| S1 | traders positioned against the early range who must cover or hedge | hedging and stop-driven flows are mechanical | widely traded; false breaks are common; a late entry pays an already-raised premium |
| S2 | participants slow to reposition after a release | large institutions adjust over hours | the release is known in advance, so 1DTE premium is already raised for it; only about 2–3 events a month |
| S3 | dealers hedging gamma and funds rebalancing near the close | the flow is tied to the day's direction by construction | 25 minutes of movement must pay a full round trip; trades every session, so costs compound |

### D4. Cost map before any signal (M28; not a trial)
From development sessions only, using quotes on disk, with **no signal computed**:
- round-trip cost of the D1 contract (ask − bid + commissions and fees) as a share of the
  premium, by DTE (1, 2) and entry time (10:00, 10:00–12:00, 15:30);
- the QQQ move needed to break even over each setup's holding window, from the contract's
  delta-equivalent sensitivity at entry.

Rules fixed now:
- **The DTE with the lower median round-trip cost share is used for all setups.**
- **A setup whose median break-even move exceeds the 75th percentile of QQQ's absolute move
  over its holding window is dropped without a trial** (ADR-0015 D2).
- *Rule 9:* the data's presence and coverage on the owner's machine is verified first. It
  could not be verified in the session that drafted this ADR (`data/` is not in the repo).

### D5. Screen per surviving setup (one registered run = 1 test)
Registered before any statistic is computed, in two steps inside the same run:
- **Step A, underlying:** mean signed QQQ return over the trade window (in the signal's
  direction). If its one-sided lower bound is ≤ 0, the setup stops here. It still counts as 1
  test.
- **Step B, options:** mean net P&L per trade as a share of the premium paid, at conservative
  fills with commissions.
- **Unit:** one trade (at most one per session per setup).
- **Uncertainty:** session-block bootstrap (`session_bootstrap_ci`), **20,000 reps**, fixed
  seed. The rep count is raised from 2,000 because at 2,000 the seed alone moved the M27 bound
  by more than the margin that decided it.
- **Outcome:**
  - **ADVANCE:** Step B lower bound > 0 at the D6 level, with ≥ 60 trades.
  - **KILL:** Step B two-sided 95% upper bound < 0 at the *mid* fill.
  - **AMBIGUOUS** otherwise. The setup stops, with no variants.
- **Risk rows (always reported, ADR-0015 Q3):** number of trades losing more than 3% of the
  account (OQ1), worst trade, longest losing run, drawdown.
- **At most 2 setups advance** (largest lower bound first).

### D6. Budget and multiple testing
- **Tests:** at most **5** of ADR-0015's remaining 7 (3 of 10 used). Unused tests stay unused.
- **Data:** $0 planned; any purchase is quoted to the cent and approved first, within the
  remaining $71.49.
- **Decision level:** one-sided 1 − 0.05/5 = **99%** for ADVANCE (Bonferroni over this ADR's
  tests; OQ5). The bound at the full recorded count (42 + tests run) is reported beside it.

### D7. Holdout
- **QQQ options, 2026-04-03 → 2026-10-02** (ADR-0011): recorded as never read. M28 verifies
  that `final_test_access_log` holds no QQQ access before anything relies on this.
- **One access**, by a separate owner ADR, covering the advanced setups together, with the
  same statistic and level.
- **Power is limited and stated now:** about 125 sessions. S2 would have roughly 15–20
  holdout trades, below any sensible guard. A holdout result under 40 trades is descriptive
  only; forward sessions after 2026-10-02 then form the confirmation (OQ6).

### D8. Autonomy, in stages (each needs its own owner ADR)
| stage | what the agent does | authorised by |
|---|---|---|
| 1 | research: D4–D7 | this ADR |
| 2 | paper executor: runs the frozen setups unattended, journals every decision, 60+ sessions | a **paper-only ADR** (ADR-0015 D4.3) |
| 3 | monitor: compares paper results with the backtest range; halts on drift, data failure, or a loss cap | same paper-only ADR |
| 4 | small live account, one contract | a **separate ADR that amends hard rule 1**; the owner's decision alone |
| 5 | spreads | account size and approval level (OQ4), **and** a spread study of its own; M19T and M23 found none that survived |

- **"Learning" means gated promotion only.** A new or changed rule reaches the agent only
  after D5, D7 and stage 2. The agent never adjusts its own parameters from live or paper
  results.
- **Loss caps in code from stage 2:** 3% of the account per day, 20% total; hitting 20% stops
  everything pending review (ADR-0015 D3).

### D9. Milestones
- **M28:** data verification, cost map, DTE choice, literature check of S1–S3 (not a trial).
- **M29–M31:** one screen each for the setups that survive D4.
- **M32:** holdout ADR and access, if any setup advances.
- Paper stages follow only by the paper-only ADR.

## Open questions for the owner (answers are recorded here before acceptance)
- **OQ1. Starting account size.** ADR-0015 says under $5,000. A 1DTE in-the-money QQQ
  contract may cost several hundred dollars, so one losing trade can exceed the 3% daily cap.
  What is the amount, and does the 3% cap stay?
- **OQ2. Broker and account type.** Still IBKR Canada, cash account? Commission schedule and
  day-trade limits depend on it. *Uncertainty flagged:* whether a cash account may reuse
  option sale proceeds the same day, and how the pre-2027 day-trade rule applies, must be
  confirmed with the broker.
- **OQ3. Market-hours time.** ADR-0015 Q4 says none. Stage 2 onward then needs an agent
  running unattended during the session. Confirm that is intended.
- **OQ4. Spread trigger.** Which account size and approval level unlock stage 5?
- **OQ5. Decision level.** 99% (D6) or another pre-declared level?
- **OQ6. Forward data.** Approve starting the forward collection already priced at about
  $0.64/month, so sessions after 2026-10-02 exist for confirmation?
- **OQ7. Reserved setups S4–S5.** Keep the two slots, or cap this ADR at three tests?

## Consequences
- If accepted: `CLAUDE.md`'s first paragraph and `docs/ROADMAP.md` are updated to this mission;
  a `study_options_day` block is added to `configs/phase1.yaml` with every D1–D6 parameter.
- The M27 pullback result is unaffected. Its paper-only ADR remains available to the owner and
  is the cheaper path to a first paper executor.
- If nothing advances within the 5 tests, this mission stops and is not extended without a new
  ADR.
