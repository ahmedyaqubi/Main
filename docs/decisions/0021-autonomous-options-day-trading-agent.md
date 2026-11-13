# ADR-0021: New mission: an autonomous options day-trading agent on a few tickers (long calls and puts first)

- Status: **PROPOSED**, revision 2 (2026-11-13). Drafted by the assistant at the owner's request
  ("re-strategize this whole idea for options day trading; calls and puts mainly, spreads as
  back-up; start with a small funded account"; then "only a few tickers"). **Not in force until
  the owner accepts it and answers OQ1–OQ7.**
- Revision 2 follows the assistant's own review of revision 1 (see "Review of revision 1").
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
  - **The inputs of the setups below are not new to the QQQ data.** `or_position` (opening
    range) and `overnight_gap` were features of the models that failed (`docs/FEATURES.md` #5,
    #6). What is new is the form (two named rules, not a model at every timestamp) and the
    other tickers. That is a weaker claim than "untested".
  - **The development sessions are heavily used:** 42 registered trials are recorded on the
    window covering these dates (`reports/research/m27_holdout.md`). Results here are judged
    against that count (D6).
  - **M24 measured fills:** a limit at the mid, then chasing, cost 1.35 half-spreads, and fill
    quality in half-spread units got *worse* from 0DTE to 2DTE (0.86 → 1.45 → 1.68). This ADR
    therefore assumes paying the ask and selling at the bid, and never relies on mid fills.
  - The setups come from published work, which the assistant knows along with the broad market
    history of 2023–2026. The protections are frozen rules, a fixed statistic, and one holdout
    access.

## Mission
> Build an **autonomous, rule-based agent** that day-trades **long calls and puts on at most
> four tickers**, entering only on **pre-registered setups**, and only if a setup's edge
> **survives ask/bid fills and commissions**, is confirmed on **untouched data** and in **paper
> trading**. The agent improves only through **gated promotion** of new rules. Spreads are a
> later stage, unlocked by account size and their own evidence.

"No setup survives, the agent trades nothing" remains a valid and likely result (rules 10, 12).

## The question being tested
A long option pays only when the underlying moves further, in the chosen direction, than the
premium already assumes. Each setup asks: *at this specific, recognisable moment, is the move
that follows large enough to pay for the option at the ask, the exit at the bid, and both
commissions?*

## Decision
### D1. Tickers (at most four, chosen by cost, never by backtest returns)
- **Fixed:** QQQ (data owned) and SPY.
- **Up to two more**, chosen in M28 from this candidate list, fixed now: **IWM, NVDA, TSLA,
  AAPL**.
- **Selection rule (frozen):** from a small quote sample on random development sessions (as
  the M23 comparison sample), with **no signal and no return computed**, rank candidates by the
  median round-trip cost of the D2 contract as a share of its premium. The two cheapest are
  added if, for each:
  - the share is no more than 1.5× QQQ's;
  - the premium fits the OQ1 loss cap on at least half of the sampled sessions.
  Fewer than two may qualify. The list is then closed.
- **Why a fixed short list:** every extra ticker is another chance to find a pattern by luck.
  Choosing by cost keeps the choice independent of the result.
- **What extra tickers add, honestly:** SPY moves almost together with QQQ, so it adds little
  independent evidence and must never be held at the same time as QQQ (D3). Single stocks add
  independent evidence but bring earnings days and wider spreads.
- **Single stocks:** sessions on or next to the company's earnings date are excluded, from a
  dated, sourced calendar file (as `configs/reference/macro_calendar.csv`). If no
  point-in-time source can be verified, single stocks are dropped (rule 9).
- *Uncertainty flagged:* which of the candidates list daily expirations, and since when, is
  to be verified in M28. The contract rule (D2) works with daily or weekly expirations.

### D2. Contract (frozen)
- **Structure:** one long call (up signal) or one long put (down signal). One contract.
- **Entry and exit the same session.** No position is held overnight.
- **Expiry:** the nearest listed expiration at least one session away (1DTE where expirations
  are daily; up to 5 sessions for weekly-only names). 0DTE is excluded: the premium is small,
  so spread and commission are a large share of it.
- **Strike:** the frozen spec §5 rule, `atm_first_otm_no_fallback`, unchanged.
- **Liquidity gates:** spec §4.9, unchanged. A contract that fails them is NO_TRADE with its
  reason; no substitute strike.
- **Fills:** conservative only for decisions: buy at the ask, sell at the bid, with the
  configured latency, rounded against the trader (spec §6). Moderate and mid fills are
  descriptive rows.
- **Costs:** `costs.commission_per_contract` and `costs.fees_per_contract`, re-read from the
  broker's schedule in M28 (OQ2).
- **Loss cap at entry:** if premium plus commissions exceeds the OQ1 cap, the trade is
  NO_TRADE (`PREMIUM_OVER_CAP`). The full premium is the worst case; a stop does not protect
  against a gap.
- **Cash account:** a purchase uses settled cash only. Premium spent in a session may not
  exceed the settled balance at the open.

### D3. Setups (frozen; 2 named, 1 reserved)
Times are America/New_York. Every input is available at the entry minute; `available_at <= T`
is enforced through `AsOfReader` as today.

| | setup | signal (direction) | entry | exit |
|---|---|---|---|---|
| S1 | Opening-range breakout | first 1-minute close above the 09:30–10:00 high (call) or below its low (put), between 10:00 and 12:00; first break only | the minute after the signal | 15:45, or earlier when a 1-minute close returns to the range midpoint |
| S2 | First-half-hour predicts the last | sign of the move from the previous close to 10:00 | 15:30 | 15:50 |
| S3 | **Reserved** | specified by an amendment, with its reason, **before** any data is examined for it | | |

- **Declared differences from the Phase 1 spec, for these setups only** (spec §2, §4.5 are not
  changed): S1 may hold longer than `trade.max_holding_minutes`; S2 enters after
  `schedule.last_new_entry`. `trade.forced_exit_time` (15:50) and the early-close offsets apply.
- **One position at a time across all tickers** (`trade.max_open_positions`). When several
  tickers signal in the same minute, the one with the lowest round-trip cost share in the
  quotes at that minute is taken; the others are NO_TRADE (`POSITION_OPEN`).
- **Sources (literature, not our data):** S1, opening-range breakout day-trading studies
  (Zarattini & Aziz, 2023); S2, Gao, Han, Li & Zhou (2018), "Market intraday momentum".
  - **Known differences, stated now:** the S1 paper uses a 5-minute range; 30 minutes is used
    here to trade less often. S2's paper measures to 16:00; the exit here is 15:50. Either
    may weaken the published effect.
  - M28 checks the remaining details against the papers. **The table above is not edited
    after acceptance**; a needed correction is an amendment made before any signal is computed.

### D4. Reason first (ADR-0015 D1)
| | who pays | why it may persist | why it may fail here |
|---|---|---|---|
| S1 | traders positioned against the early range who must cover or hedge | hedging and stop-driven flows are mechanical | widely traded; false breaks are common; a late entry pays an already-raised premium |
| S2 | dealers hedging gamma and funds rebalancing near the close | the flow is tied to the day's direction by construction | 20 minutes of movement must pay a full round trip; it trades every session, so costs compound; it was documented on index ETFs, not single stocks |

### D5. Cost map and feasibility before any signal (M28; not a trial)
From development sessions only, with **no signal computed**:
- round-trip cost share of the D2 contract per ticker, at 10:00–12:00 and 15:30;
- the underlying move needed to break even over each setup's holding window;
- share of sessions passing the D2 loss cap;
- **required edge:** the mean net return per trade each setup would need to reach ADVANCE at
  its expected number of trades, given how widely per-trade option returns vary.
  - The variation is taken from existing development backtest output (M11/M12 trades), which
    was computed without these setups' signals. *Not yet located:* `reports/labels/summary.md`
    holds outcome frequencies only, so M28 must find or recompute it, on development sessions.

Rules fixed now:
- **A setup whose median break-even move exceeds the 75th percentile of the ticker's absolute
  move over its holding window is dropped for that ticker without a trial** (ADR-0015 D2).
  The 75% line is a judgement, not a derived number.
- **If the required edge for a setup exceeds the largest effect reported in its source paper,
  the setup is dropped without a trial.** A test that cannot pass is not run.
- *Rule 9:* the QQQ data's presence and coverage on the owner's machine is verified first. It
  could not be verified in the session that drafted this ADR (`data/` is not in the repo).

### D6. Screen per setup (one registered run = 1 test, pooled over the tickers)
Registered before any statistic is computed, in two steps inside the same run:
- **Step A, underlying:** mean signed return of the underlying over the trade window. If its
  one-sided 95% lower bound is ≤ 0, the setup stops here. It still counts as 1 test.
- **Step B, options:** mean net P&L per trade as a share of the premium paid, at conservative
  fills with commissions, under the D3 one-position rule.
- **Unit:** one trade. **Resampling unit: the session**, so trades on different tickers on
  the same day are resampled together (`session_bootstrap_ci`), **20,000 reps**, fixed seed.
  The rep count is raised from 2,000 because at 2,000 the seed alone moved the M27 bound by
  more than the margin that decided it.
- **Outcome:**
  - **ADVANCE:** Step B lower bound > 0 at the D7 level, with ≥ 60 trades.
  - **KILL:** Step B two-sided 95% upper bound < 0 at the *mid* fill.
  - **AMBIGUOUS** otherwise. The setup stops, with no variants.
- **Per-ticker rows are descriptive only.** No ticker is added, dropped or reweighted from
  them.
- **Risk rows (always reported, ADR-0015 Q3):** worst trade, longest losing run, drawdown,
  and the count of `PREMIUM_OVER_CAP` and `POSITION_OPEN` rejections.

### D7. Budget and multiple testing
- **Tests:** at most **3** of ADR-0015's remaining 7 (3 of 10 used). Unused tests stay unused.
- **Data:** the QQQ history cost about $13; each added ticker is expected to cost a similar
  amount. This is an estimate. Each purchase is quoted to the cent and approved first, within
  the remaining $71.49.
- **Decision level:** one-sided 1 − 0.05/3 ≈ **98.3%** for ADVANCE (Bonferroni over this
  ADR's tests; OQ5). The bound at the full recorded count (42 + tests run) is reported beside
  it.

### D8. Holdout
- **QQQ: 2026-04-03 → 2026-10-02** (ADR-0011), recorded as never read. M28 verifies that
  `final_test_access_log` holds no QQQ access before anything relies on this.
- **Every other ticker: 2025-10-03 → 2026-10-02**, locked before its data is first examined
  (ADR-0015 D4). The M28 quote sample is drawn from development sessions only.
- **One access**, by a separate owner ADR, covering the advanced setups together, with the
  same statistic and level.
- **Power is limited and stated now:** 6 to 12 months. A holdout result under 40 trades is
  descriptive only; forward sessions after 2026-10-02 then form the confirmation (OQ6).

### D9. Autonomy, in stages (each needs its own owner ADR)
| stage | what the agent does | authorised by |
|---|---|---|
| 1 | research: D5–D8 | this ADR |
| 2 | paper executor: runs the frozen setups unattended, journals every decision, 60+ sessions | a **paper-only ADR** (ADR-0015 D4.3) |
| 3 | monitor: compares paper results with the backtest range; halts on drift, data failure, or a loss cap | same paper-only ADR |
| 4 | small live account, one contract | a **separate ADR that amends hard rule 1**; the owner's decision alone |
| 5 | spreads | account size and approval level (OQ4), **and** a spread study of its own; M19T and M23 found none that survived |

- **"Learning" means gated promotion only.** A new or changed rule reaches the agent only
  after D6, D8 and stage 2. The agent never adjusts its own parameters from live or paper
  results.
- **Loss caps in code from stage 2:** 3% of the account per day, 20% total; hitting 20% stops
  everything pending review (ADR-0015 D3).

### D10. Milestones
- **M28:** data verification, ticker selection, cost map and feasibility, literature check
  (not a trial).
- **M29–M30:** one screen each for the setups that survive D5.
- **M31:** holdout ADR and access, if a setup advances.
- Paper stages follow only by the paper-only ADR.

## Open questions for the owner (answers are recorded here before acceptance)
- **OQ1. Account size and per-trade loss cap.** ADR-0015 says under $5,000 and 3% a day
  (about $150). A long option can lose its whole premium, and a next-day at-the-money contract
  on these tickers may cost more than $150. Choose: (a) keep 3% as the most one trade may cost,
  accepting that many sessions will be NO_TRADE; or (b) a larger stated per-trade cap.
- **OQ2. Broker and account type.** Still IBKR Canada, cash account? *Uncertainty flagged:*
  same-day reuse of option sale proceeds, and how the pre-2027 day-trade rule applies, must be
  confirmed with the broker.
- **OQ3. Market-hours time.** ADR-0015 Q4 says none. Stage 2 onward then needs an agent
  running unattended during the session. Confirm that is intended.
- **OQ4. Spread trigger.** Which account size and approval level unlock stage 5?
- **OQ5. Decision level.** 98.3% (D7) or another pre-declared level?
- **OQ6. Forward data.** Approve starting forward collection for the chosen tickers, so
  sessions after 2026-10-02 exist for confirmation? Cost to be quoted.
- **OQ7. Tickers.** Accept the candidate list (IWM, NVDA, TSLA, AAPL), or name others
  **before** M28 starts? After that the list is closed.

## Review of revision 1 (assistant's own QA, 2026-11-13)
Errors corrected:
- **Contradicted a frozen definition.** Rev 1 chose "the first in-the-money strike" while
  saying the selection code was unchanged; spec §5 is first out-of-the-money. Rev 2 uses the
  frozen rule.
- **Broke spec times without saying so.** A 15:30 entry and a 15:55 exit are outside spec §2
  (last entry 15:00, forced exit 15:50), and S1 exceeded the 90-minute hold. Rev 2 exits at
  15:50 and declares the two remaining differences.
- **"Frozen" rules that could still change.** Rev 1 froze the setups and also allowed M28 to
  correct them. Rev 2 states the known differences from the papers and requires an amendment.
- **A missing decision threshold.** Step A had no confidence level. It is now 95%.
- **The loss cap was reported, not enforced.** Rev 2 adds `PREMIUM_OVER_CAP`.
- **Cash settlement and concurrent positions were not modelled.** Added in D2 and D3.
- **Trial count misquoted** as "40 plus 2"; the recorded figure is 42.

Design weaknesses corrected:
- **The macro-release setup was untestable and redundant.** Only 70 CPI/NFP sessions exist in
  development and 13 in the holdout, and its signal was the same as the half-hour setup's.
  Dropped.
- **Two reserved slots invited idea-shopping.** Reduced to one; tests cut from 5 to 3.
- **QQQ only** did not match the owner's aim. Rev 2 adds a cost-ranked list capped at four.
- **No check that the tests could pass.** D5 now computes the required edge first.

Weaknesses that remain:
- **Power is probably low.** Option returns per trade vary widely, so only a large edge can
  clear a 98.3% bound in three years of data. D5 measures this before any test is run, and may
  stop the mission there.
- **Pooling mixes unlike instruments.** Index ETFs and single stocks may behave differently;
  the per-ticker rows are descriptive and cannot rescue a failed pooled test.
- **SPY adds little** beyond QQQ.
- **Several numbers are judgements:** the 30-minute range, the 12:00 cutoff, the 75% line,
  the 1.5× cost limit, the 60- and 40-trade guards. They are fixed in advance, not derived.
- **This ADR mixes a mission, a study design and an autonomy roadmap.** Earlier ADRs kept
  these separate. If accepted, the per-setup details move to their own study ADRs.
- **Nothing here has been run.** No data was read in drafting or reviewing it.

## Consequences
- If accepted: `CLAUDE.md`'s first paragraph and `docs/ROADMAP.md` are updated to this mission;
  a `study_options_day` block is added to `configs/phase1.yaml` with every D1–D7 parameter.
- The M27 pullback result is unaffected. Its paper-only ADR remains available to the owner and
  is the cheaper path to a first paper executor.
- If nothing advances within the 3 tests, this mission stops and is not extended without a new
  ADR.
