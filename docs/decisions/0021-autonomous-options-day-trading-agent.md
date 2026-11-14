# ADR-0021: New mission: an autonomous options day-trading agent on a few tickers (long calls and puts first)

- Status: **ACCEPTED** 2026-11-14 by the owner ("$500 is fine, yes unattended, keep 98.3%,
  accept"), at revision 5 with OQ1–OQ7 answered as recorded below. Drafted by the assistant at
  the owner's request ("re-strategize this whole idea for options day trading; calls and puts
  mainly, spreads as back-up; start with a small funded account"; then "only a few tickers").
- Revision 2 follows the assistant's own review of revision 1 (see "Review of revision 1").
- Revision 3 records the owner's answers to OQ1 and OQ7 (2026-11-13): six tickers; a per-trade
  loss cap of the cost of 1 to 2 contracts.
- Revision 4 records the owner's input of 2026-11-14: broker is IBKR or Webull, with paid live
  data on either; the system must learn from history, from its own trades, and from watching
  the market when it does not trade (new D10).
- Revision 5 records the owner's answers of 2026-11-14: the recorder is approved; the account
  is $5,000; one contract per trade.
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
> Build an **autonomous, rule-based agent** that day-trades **long calls and puts on six
> tickers**, entering only on **pre-registered setups**, and only if a setup's edge
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
### D1. Tickers (fixed by the owner, 2026-11-13; never changed by backtest returns)
- **QQQ, SPY, IWM, NVDA, TSLA, AAPL.** QQQ's data is owned; the other five are purchased.
  - Revision 2 proposed adding at most two of the last four, ranked by cost. The owner chose
    to add all four. The list is now closed.
- **Cost still gates each ticker, by the D5 rules fixed in advance:** a ticker whose
  break-even move is too large for a setup is dropped for that setup, with the reason logged.
- **What the extra tickers add, honestly:** SPY and IWM move largely with QQQ, so they add
  little independent evidence. The single stocks add independent evidence but bring earnings
  days and wider spreads. Six tickers do not mean six times the evidence.
- **Single stocks:** sessions on or next to the company's earnings date are excluded, from a
  dated, sourced calendar file (as `configs/reference/macro_calendar.csv`). If no
  point-in-time source can be verified, single stocks are dropped (rule 9).
- *Uncertainty flagged:* which tickers list daily expirations, and since when, is to be
  verified in M28. The contract rule (D2) works with daily or weekly expirations.

### D2. Contract (frozen)
- **Structure:** one long call (up signal) or one long put (down signal). **One contract per
  trade** (owner, 2026-11-14).
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
  official schedules of **both** IBKR and Webull in M28. Results are reported under each; the
  decision uses the more expensive of the two until the broker is chosen (OQ2).
- **Loss cap at entry (owner, OQ1):** the most one trade may lose is the cost of its one
  contract. For entries this replaces ADR-0015's 3%-a-day figure.
  - **Account: $5,000.** ADR-0015's 20% total cap is unchanged: trading stops for review after
    $1,000 of losses.
  - **Dollar ceiling per trade: $500 (10% of the account), confirmed by the owner
    2026-11-14.** A contract costing more, commissions included, is NO_TRADE
    (`PREMIUM_OVER_CAP`). At $500 the total cap survives at least two full-premium losses.
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
- **Data:** the QQQ history cost about $13. If each of the five added tickers costs a similar
  amount, the total is about $65 of the remaining $71.49, which leaves almost nothing for
  forward data (OQ6). This is an estimate, and single stocks may differ. Each purchase is quoted to the cent and approved first, within
  the remaining $71.49.
- **Decision level:** one-sided 1 − 0.05/3 ≈ **98.3%** for ADVANCE (Bonferroni over this
  ADR's tests; confirmed by the owner, OQ5). The bound at the full recorded count (42 + tests run) is reported beside
  it.

### D8. Holdout
- **QQQ: 2026-04-03 → 2026-10-02** (ADR-0011), recorded as never read. M28 verifies that
  `final_test_access_log` holds no QQQ access before anything relies on this.
- **Every other ticker: 2025-10-03 → 2026-10-02**, locked before its data is first examined
  (ADR-0015 D4).
- **One access**, by a separate owner ADR, covering the advanced setups together, with the
  same statistic and level.
- **Power is limited and stated now:** 6 to 12 months. A holdout result under 40 trades is
  descriptive only; forward sessions after 2026-10-02 then form the confirmation (OQ6).

### D9. Autonomy, in stages (each needs its own owner ADR)
| stage | what the agent does | authorised by |
|---|---|---|
| 1 | research: D5–D8 | this ADR |
| 1b | recorder: reads live quotes for the six tickers and stores them, every session; computes shadow signals (D10). **Market-data access only; no order permission, no order code** | this ADR, once OQ2 names the broker and a data-only connection is verified (rule 9) |
| 2 | paper executor: runs the frozen setups unattended, journals every decision, 60+ sessions | a **paper-only ADR** (ADR-0015 D4.3) |
| 3 | monitor: compares paper results with the backtest range; halts on drift, data failure, or a loss cap | same paper-only ADR |
| 4 | small live account, one contract | a **separate ADR that amends hard rule 1**; the owner's decision alone |
| 5 | spreads | account size and approval level, set by its own later ADR (OQ4), **and** a spread study of its own; M19T and M23 found none that survived |

- **How the agent learns is fixed in D10.** A new or changed trading rule reaches the agent
  only through its promotion gate.
- **Loss caps in code from stage 2:** 3% of the account per day, 20% total; hitting 20% stops
  everything pending review (ADR-0015 D3).

### D10. Learning (owner requirement, 2026-11-14)
The system learns from three sources. What it may change by itself depends on how much
evidence each source can give.

| source | what is recorded | what it teaches |
|---|---|---|
| History | the D5–D8 studies | whether a setup has an edge at all |
| Its own trades (paper, later live) | every decision, order, fill and exit, against what the model expected | real fill prices and costs; whether results stay inside the backtest range |
| Watching without trading (the **shadow book**) | every session, for every ticker: each setup's signal, the trade it would have taken, why it did not trade, and what happened next; the same for candidate rules not yet promoted | what the frozen rules miss; whether NO_TRADE reasons are costing or saving money; how a candidate behaves on data nobody has tuned to |

**What changes automatically, and what does not:**
- **Automatic, with a log entry:** estimates of fills and costs; halts and stricter limits.
  These can only make the agent trade less or more cautiously.
- **Automatic, proposal only:** the system may draft a new candidate rule or a change to an
  existing one, with its reason (ADR-0015 D1), from anything it observes.
- **Never automatic:** entry or exit rules, tickers, sizing and loss caps. A candidate
  becomes a trading rule only by: pre-registration → shadow book for a pre-declared number of
  sessions with a pre-declared pass line → the owner's approval.

**Why trading rules are not retuned from recent results:** a setup trades at most once a day
per ticker. A few weeks of wins or losses is almost all noise, and a system that adjusts to
it loses what the testing was for.

**Why the shadow book matters most:** forward sessions are data that no one has examined. A
candidate that passes there has passed the cleanest test this project can run, and the
record costs nothing beyond the live data subscription. It also replaces most of the paid
forward data in OQ6.

**Rules that stay in force:** every shadow and live value carries `available_at` (rule 2);
every candidate is a registered trial and counts in n_trials (D7); shadow results are never
called profits (rule 12).

### D11. Milestones
- **M28:** data verification, ticker selection, cost map and feasibility, literature check
  (not a trial).
- **M29–M30:** one screen each for the setups that survive D5.
- **M31:** holdout ADR and access, if a setup advances.
- Paper stages follow only by the paper-only ADR.

## Owner's answers (all recorded before acceptance)
- **OQ1. Account size and per-trade loss cap. ANSWERED (owner, 2026-11-13 and 2026-11-14):**
  $5,000; one contract; the most a trade may lose is that contract's cost. Recorded in D2.
  - $500 ceiling per trade confirmed 2026-11-14.
- **OQ2. Broker and account type. PARTLY ANSWERED (owner, 2026-11-14):** IBKR or Webull;
  live data is paid on Webull and can be on IBKR.
  - **Still open:** which one. M28 decides by a rule fixed now: the broker must offer (i) a
    data-only connection, (ii) a paper account reachable by program, and (iii) option day
    trades in the owner's account type; among those that do, the lower modelled round-trip
    cost wins.
  - *Uncertainty flagged, none of it verified:* each broker's option fees for the owner's
    country; whether either live subscription includes historical quotes for expired option
    contracts (the assistant expects not); same-day reuse of option sale proceeds; how the
    pre-2027 day-trade rule applies.
- **OQ3. Market-hours time. ANSWERED (owner, 2026-11-14):** yes, the agent runs unattended
  during the session from stage 2 on.
- **OQ4. Spread trigger. DEFERRED:** the owner gave no figure. As the assistant suggested, it
  is set by a separate ADR when stage 5 is first considered. Nothing in this ADR unlocks
  spreads.
- **OQ5. Decision level. ANSWERED (owner, 2026-11-14):** 98.3%.
- **OQ6. Forward data. ANSWERED (owner, 2026-11-14):** the stage 1b recorder is approved.
  - It is built only after this ADR is accepted, the broker is chosen by the OQ2 rule, and a
    data-only connection is verified. Until then no code connects to a broker.
  - Paid forward pulls are needed only for sessions between 2026-10-02 and the recorder's
    first day; cost to be quoted.
- **OQ7. Tickers. ANSWERED (owner, 2026-11-13):** add IWM, NVDA, TSLA and AAPL to QQQ and
  SPY. Recorded in D1.

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
- **QQQ only** did not match the owner's aim. Rev 2 added a cost-ranked list capped at four;
  rev 3 fixes six tickers by the owner's choice.
- **No check that the tests could pass.** D5 now computes the required edge first.

Weaknesses that remain:
- **Power is probably low.** Option returns per trade vary widely, so only a large edge can
  clear a 98.3% bound in three years of data. D5 measures this before any test is run, and may
  stop the mission there.
- **Pooling mixes unlike instruments.** Index ETFs and single stocks may behave differently;
  the per-ticker rows are descriptive and cannot rescue a failed pooled test.
- **SPY and IWM add little** beyond QQQ.
- **Several numbers are judgements:** the 30-minute range, the 12:00 cutoff, the 75% line,
  the 60- and 40-trade guards. They are fixed in advance, not derived.
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
