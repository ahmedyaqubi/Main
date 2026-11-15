# M28 steps 1–3: config, broker check, expirations and literature check (ADR-0021)

Written 2026-11-14. No market data was read and no signal or return was computed. Every fact
below is marked **verified** (read today on the page named) or **not verified**. Search-engine
summaries are never counted as verified.

## Step 1. Config: done
- `study_options_day` in `configs/phase1.yaml` holds every frozen ADR-0021 parameter; the
  model (`core/config.py`) refuses contradictory values. Tests: `tests/test_options_day_config.py`.
- The ADVANCE level is computed as 1 − 0.05/3 = 98.33%, not typed in.

## Step 2. Broker (ADR-0021 OQ2 rule)

**The account is Canadian (owner, 2026-11-14).** Every fee below is for a Canadian client. A US account would change them.

### Fees for one US-listed option contract
| | IBKR Canada | Webull Canada |
|---|---|---|
| Commission | $0.65 per contract (premium ≥ $0.10), **minimum $1.00 per order** | **$0.99 per contract** after a 3-month refund period for accounts that activate options on or after 2026-08-01 |
| One contract, per side | **$1.00** | **$0.99** |
| Pass-through fees | OCC $0.025/contract; CAT $0.0003/contract; SEC 0.0000206 × sale value (sells only); ORF varies by exchange | "Regulatory, exchange, and other fees may apply": amounts **not on the page** |
| Round trip, one contract | about **$2.05** plus ORF | about **$1.98** plus unstated fees |
| Source (verified) | interactivebrokers.ca/en/pricing/commissions-options.php | webull.ca/pricing, webull.ca/trading-investing/options |

- **The two cost the same, within a few cents.** Cost does not separate them.
- **Correction to earlier work:** the Phase 1 `costs` block charges $0.70 per side. For one
  contract at IBKR the order minimum makes it about $1.03. Round-trip costs in earlier
  one-contract studies were understated by about $0.65. Every earlier options study
  failed, and a higher cost only makes a failure worse, so no result is reversed. ADR-0021
  uses the corrected figure (`study_options_day.broker_fees`).

### The three requirements
| requirement | IBKR | Webull |
|---|---|---|
| (i) Data-only connection | A **"Read-Only API"** setting exists in TWS's API settings (**verified**: named in IBKR's "TWS Configuration For API Use"). What exactly it blocks: **not verified** from a primary page today | An API key is issued with **"Market Data and Trading" permissions together** (**verified**, individual application guide). No data-only key is documented |
| (ii) Paper account reachable by program | **Not verified** from a primary page today | A PaperTrade (sandbox) environment with its own API keys exists (**verified**), on the US developer site |
| (iii) Option day trades in the owner's account type | **Not verified** (needs the owner's account settings and IBKR's rules) | **Not verified** |
| API available to a Canadian account | Market data by API needs an IBKR Pro account, $500 equity plus the subscription cost, and "Market Data API" enabled (**verified**) | The developer documentation covers "the US market" only; `developer.webull.ca` returned no content. **Not verified for Canada** |
| Does the existing live-data subscription work through the API? | Subscriptions are per account and must be enabled for the API (**verified**); price of the options feed **not verified** | **No.** "Market data subscriptions purchased through the Webull mobile app or desktop platform are independent of OpenAPI"; options need a separate "OPRA Real-Time Non-display" subscription (**verified**) |

### History: neither broker replaces the purchase (verified)
- **IBKR:** historical data for "expired options" is listed as unavailable.
- **Webull:** option history is trade bars only, "up to 180 days for minute bars". The study
  needs three years of minute bid and ask quotes.
- So the five new tickers must be bought (step 5), as expected.

### Outcome: **IBKR**
- Under the rule, Webull does not currently qualify: no data-only key is documented, and
  API access for a Canadian account is unconfirmed. IBKR has the documented read-only switch.
- It was provisional pending three IBKR items. They were checked the same day (follow-up
  below): two verified, one verified in substance with a stated gap.

### Follow-up, 2026-11-14: the three open IBKR points
Read on IBKR's own pages (interactivebrokers.com campus lesson "Installing & Configuring TWS
for the API", TWS API documentation, and interactivebrokers.ca "Configuring Your Account").

| point | finding | status |
|---|---|---|
| What Read-Only API blocks | "The setting 'Read-Only' is enabled by default and will block all API orders. It must be unchecked to allow any orders from the API." The settings reference: "true indicates modifications cannot be made through the API." | **verified** that it blocks orders. That market data still flows with it on is **not stated** on any page read; it is confirmed only by testing on the owner's own TWS, which is the recorder's first check |
| Paper account reachable by program | "Paper accounts are compatible to use with the TWS API." Default ports: TWS 7496 live / 7497 paper; IB Gateway 4001 live / 4002 paper. A paper account needs the live account approved and funded | **verified** |
| Option day trades in a Canadian cash account | "Full payment is required for all call and put purchases." "Cash from the sale of options is available one business day after the trade date." The USD 25,000 day-trading minimum is stated for **margin** accounts only ("accounts that remain subject to existing Pattern Day Trading regulations", during a "PDT rule phase-out period") | **verified** for the settlement rule. No page read says in so many words that a cash account may day-trade options without a count limit; the pages impose only the settled-cash limit |

Consequences:
- **The broker choice stands: IBKR.** Read-Only API is on by default, so the recorder runs
  with IBKR's own order block in place, in addition to this project having no order code.
- **The ADR's cash rule matches IBKR's:** premium spent in a session may not exceed settled
  cash, and sale proceeds return the next business day. With $5,000 and at most $500 per
  trade, settlement does not bind at one position at a time.
- **Two cautions for the recorder, both from IBKR's pages:**
  - Market data by API needs an IBKR Pro account, USD 500 of equity plus the subscription
    cost, and "Market Data API" enabled.
  - A paper session "will not receive market data if it is sharing data from a live user
    which is used to login to Client Portal" at the same time.
- **Still not verified:** the monthly price of IBKR's US options data feed.

## Step 3. Expirations, earnings calendar, literature

### Expirations
- **IWM:** Tuesday and Thursday expirations were planned to list from 2024-04-16 and
  2024-04-18, with first expirations 2024-04-23 and 2024-04-25 (**verified**, Cboe notice
  C2024041502, "pending regulatory review"). Before that, IWM did not expire every weekday.
  Consequence: IWM is not always 1DTE before late April 2024. The D2 rule (nearest expiration
  at least one session away) already handles this.
- **QQQ:** as recorded in spec §1.1 (verified in Phase 1). **SPY: not verified today.**
- **NVDA, TSLA, AAPL:** **not verified.** Search summaries describe SEC-approved Monday and
  Wednesday expirations for large "Qualifying Securities" in 2026, but sec.gov refused the
  download. Whatever the answer, it applies after the development window, and the definition
  files bought in step 5 will show each contract's real expiration.

### Earnings calendar
- **Not verified.** The intended source is each company's 8-K filings (Item 2.02) on SEC
  EDGAR, about 42 events for three companies. sec.gov refuses automated requests that do not
  identify a contact, and the assistant does not send the owner's details without permission.

### Literature check
**S1 does not match the paper it cites. This needs the owner's decision before any signal is
computed.** Zarattini & Aziz, "Can Day Trading Really Be Profitable?" (**verified**, full
PDF read):

| | the paper | ADR-0021 S1 |
|---|---|---|
| Opening range | first **5-minute** candle | first 30 minutes |
| Direction | **the direction of that first candle** (up → long, down → short; no trade if open = close) | a later break above the range high or below its low |
| Entry | open of the second 5-minute candle (09:35) | the minute after a break, 10:00–12:00 |
| Stop | the first candle's low (long) or high (short) | a close back at the range midpoint |
| Target / exit | 10× the stop distance, or the close | 15:45 |
| Trades | every session (1,795 trades, 2016-01 → 2023-02) | only on break days |
| Result reported | win rate 24%, average +0.13 of the stop distance per trade; commission $0.0005/share, **no slippage, no spread** | none; this variant has no published test that the assistant has verified |

- ADR-0021 disclosed only the 5-versus-30-minute difference. The rule itself is different.
- The paper's sample ends 2023-02, one month before this project's QQQ data begins, so the
  whole development window is outside its sample.
- **Decided (owner, 2026-11-14): option (a), adopt the paper's rule.** Recorded as ADR-0021
  amendment A1; config and tests updated.
- The options that were offered:
  - **(a) Adopt the paper's rule.** Entry at 09:35 is before spec `schedule.first` (09:45),
    a new declared exception, and option spreads are widest just after the open; the cost
    map would show whether that kills it.
  - **(b) Keep S1 as written** and correct the attribution: a generic opening-range breakout
    with no verified published source.

**S2: not verified from a primary source.** The paper (Gao, Han, Li & Zhou, JFE 2018) could
not be downloaded. Search summaries agree with the ADR's description and report an R² of
about 1.6–2% and a gross return of about 6–7% a year on SPY, before costs. To be confirmed
from the paper before S2's test is registered.

**Update 2026-11-15: verified from the publisher's page; the full text was not read.**
Source: Journal of Financial Economics 129(2), August 2018, pp. 394–414, on ScienceDirect
(`sciencedirect.com/science/article/abs/pii/S0304405X18301351`). The page shows the abstract,
the full introduction and the opening lines of each section. The tables are behind the paywall,
and SSRN answered with a bot check, which was not bypassed.

| | the paper | ADR-0021 S2 |
|---|---|---|
| Signal | sign of the first half-hour return, "measured from the previous day's market close" | sign of the move from the previous close to 10:00: **matches** |
| Entry | "at the beginning of the last half hour" (15:30) | 15:30: **matches** |
| Exit | "at the market close" (16:00) | 15:50: differs, already declared in D3 |
| Position | long if the signal is positive, **short otherwise**, in the ETF | long call or long put |
| Instrument | SPY, 1993-02-01 → 2013-12-31 (TAQ trade prices; days with under 500 trades excluded) | options on six tickers, 2023 onward |
| Other tickers | "ten other most actively traded" ETFs, the Nasdaq and Russell 2000 ETFs among them | QQQ, SPY and IWM are covered in kind; **NVDA and TSLA are single stocks: this project's extension** |

What the paper reports for SPY (introduction):
- Predictive R² 1.6% in sample and 1.4% out of sample, using the first half-hour return alone.
- Timing by the sign of the first half-hour return: **6.67% a year on average, standard
  deviation 6.19%, Sharpe ratio 1.08**. Over about 252 sessions that is about **0.026% of the
  underlying per trade**, before costs.
- It says the result "remains significant even after accounting for transaction costs" and is
  often stronger on the other ETFs. **Not verified:** the cost assumption and the per-ETF
  figures, which are in the tables.

Points for the owner:
- **The effect is about the size of the cost.** The M28 cost map puts S2's median break-even
  move at 0.02–0.04% for QQQ and SPY and 0.05–0.07% for IWM, against the paper's average of
  about 0.026% per trade on SPY.
- **Amendment A2's reason for S2 has changed.** It said S2 had no verified paper figure. It
  now has one, in units of the underlying's return. D5 rule 2 compares a return on option
  premium, so applying it would still need a stated conversion (the option's delta and
  premium). Whether to revisit A2 for S2 is the owner's decision.
- The paper's sample ends in 2013, ten years before this project's data. Whether the effect
  persisted after publication is not something the paper can show.

## Could not be done here
- Three sites refused the download (sec.gov, papers.ssrn.com, alphaarchitect.com).
- Steps 4–7 need the market data, the database and the vendor key, which are not in this
  environment.
