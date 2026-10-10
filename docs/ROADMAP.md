# Roadmap (after Phase 1 and Phase 2): approved 2026-10-10

Mission and rules: ADR-0015 (PROPOSED). Owner constraints:
- under $5k, cash account with basic options;
- rule-based, no market-hours time;
- 3% daily / 20% total loss caps;
- $100 and ≤ 10 tests;
- success = development screen + holdout + 60+ days of paper trading.

Background: `reports/research/phase1_synthesis.md`, `docs/LESSONS_LEARNED.md`.

## M24 result (2026-10-10): NOT PROMISING
- `reports/research/m24_fill_feasibility.md`: buy limits at mid fill often, but mostly when the
  price is moving against the order.
- "Limit at mid, then chase" cost **1.35 half-spreads**, worse than paying the ask.
- Options ideas are deprioritised. The next study is an ETF idea.

## Next study: M24, fill feasibility (no orders, no strategy trial)
**Question:** when a retail limit order is placed **at or near the mid** of QQQ, SPY or SPX
options, how often does it fill within a few minutes, and at what price relative to the mid?

**Why first:**
- In every study, results swung from clearly losing (buy at the ask, sell at the bid) to around
  break-even (mid).
- The real fill price is the missing number. It decides whether any options idea is worth a
  trial, including buying options, the only options strategy the cash account allows.

**Method (data only, nothing sent to any broker):**
- **Data:** OPRA trade prints plus 1-second quotes (`cbbo-1s`, available from 2025-02-20).
- **Contracts:** QQQ, SPY and SPX near-the-money, expiries 0–30 days.
- **Windows:** around 10:00 and the close (when our rules would trade).
- **Sessions:** a sample, only from dates outside every holdout: **2025-02-20 → 2025-10-02**.
  That keeps the SPX holdout, the QQQ holdout and a future SPY holdout untouched.
- **For each hypothetical limit order** (buy at mid, mid + 25% of the spread, …; and sells):
  - did a trade print at or through that price within 1, 5 or 15 minutes?
  - with what size?
  - and how did the mid move meanwhile (adverse selection)?
- **Output:** a fill-probability table by underlying, moneyness, DTE, spread width and time of
  day. It feeds the cost model of every later study.

**Limits, stated up front:**
- A print at our price doesn't prove our order would have filled (queue position, size).
- Paper trading is the real check, so this study gives an estimate with stated uncertainty.

**Data price quote (free, nothing bought; 2026-10-10):**
- **Whole option chains are too expensive.** Databento `get_cost` on 6 sampled sessions
  (2025-03-03 → 2025-09-04), with windows 09:55–10:35 and 15:25–16:00 ET, came to about
  **$17 per session** for QQQ + SPY + SPX (trades + 1-second quotes):

  | | QQQ | SPY | SPX |
  |---|---|---|---|
  | trades | $2.24 | $4.16 | $3.59 |
  | 1-second quotes | $1.80 | $1.67 | $3.79 |

  - Twenty 504 timeouts on the 1-second quotes mean this is an **underestimate**.
  - Even 6 sessions (about $100) would use the whole budget.
- **Proposed narrower scope (to be priced exactly before any approval):**
  - **QQQ and SPY only:** SPX doesn't fit an account under $5k.
  - **Near-the-money contracts only**, at 0–30 DTE.
  - **Trade prints only.** For the reference mid, use the QQQ 1-minute quotes **already on disk**
    (M4 1/2DTE, M19T 0DTE; 2023-03-28 → 2026-04-02, development dates only).
  - **About 20 sessions.**
  - **Rough estimate: about $15–30**, to be confirmed by an exact symbol-level quote.
  - Trade-off: a 1-minute mid is coarser than a 1-second one, so the fill estimates carry
    more uncertainty.

## Shortlist of candidate ideas (reason-first; not decisions)
Each needs its own ADR, declared test share, cost model and locked holdout before any data is
examined. Odds are my honest prior, given what we found and the owner's constraints.

| # | idea | who pays / why it might persist | fits your account? | my honest odds |
|---|---|---|---|---|
| 1 | **ETF trend following** (SPY/QQQ/TLT/GLD; hold while the price is above a long average, checked weekly or monthly) | Investors underreact to slow news; hedgers and institutions move slowly. Documented over ~100 years and many markets | Yes: cash account, a few trades a year, tiny costs | **Moderate.** The best evidence-to-cost ratio on this list. But returns are modest, drawdowns long, and it isn't "day trading". The likeliest to pass, and the least exciting |
| 2 | **Turn-of-month effect** (SPY; buy near the last trading day, sell a few days later) | Month-end salary, pension and fund inflows arrive on a schedule | Yes: ~12 round trips a year, cash account | **Low–moderate.** Well documented, but weaker in recent decades and widely known. Cheap to test honestly |
| 3 | **Short-term pullback buying** (SPY/QQQ after a sharp 1–3 day drop, hold 1–5 days) | Liquidity providers are paid for absorbing forced or panicked selling | Yes: cash account (settlement limits frequency), orders at the close | **Low.** Real effect in the literature, but one of the most over-mined ideas in retail trading. Needs strict pre-registration and the holdout |
| 4 | **Buying options only when they are cheap** (buy calls or puts when implied volatility is low relative to a forecast of realised volatility) | Option sellers may underprice moves after calm periods | Yes: buying options is allowed. But each trade is $50–100 risk, and costs are large per contract | **Low.** Phase 1 showed option prices already reflect expected moves. Only worth a test if M24 shows fills near mid |
| 5 | **Overnight-drift on index ETFs** (hold SPY/QQQ from close to next open) | Documented: most index gains historically came overnight (risk of holding through closures) | **Poor fit:** a daily round trip in a cash account hits settlement limits, and ~0.04–0.08% per day in costs eats most of the typical premium | **Very low** at this size and account type. Listed because it's famous, not because I recommend it |

**Honest overall view:**
- The ideas most likely to survive costs (1, 2) are **slower than day trading**.
- The ideas closest to what you asked for (4, and options generally) have the **weakest
  evidence** given our results.
- I'd test one slow ETF idea and at most one options idea, and leave the rest of the budget
  unused unless the first results justify it.

## Order of work
1. **Done 2026-10-10:** ADR-0015 and this roadmap approved; commit, then tag
   `v1.0-research-engine`.
   - **Owner's order:** M24 at the narrower scope (priced exactly first), then an ETF idea.
   - **Spending more on options fill work** only if M24 looks promising, against a threshold
     fixed in the M24 plan before the result, and within ADR-0015's $100 / 10-test cap.
2. **M24 fill-feasibility study:** plan → owner approves the exact data quote → tests first →
   report.
3. **The owner picks one or two shortlist ideas.** Each gets its own ADR (reason, costs,
   holdout lock, test share), then a development screen, then the holdout.
4. **If one passes:** a paper-only ADR, then 60+ sessions of paper trading, then the owner's
   decision.
