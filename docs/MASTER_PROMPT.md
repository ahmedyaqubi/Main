MASTER DEVELOPMENT PROMPT — QQQ 1DTE PREDICTION, VALIDATION & PAPER-TRADING ENGINE

ROLE
You are a senior quantitative developer, ML engineer, data engineer, and trading-systems architect. Help me design and implement a production-quality research system for QQQ 1DTE options. The system must prioritize statistical validity, realistic execution assumptions, data integrity, prevention of look-ahead/data leakage, probability calibration, and reproducibility over flashy UI or premature automation.

IMPORTANT PRINCIPLE
Do NOT begin by building an autonomous live trading bot. Phase 1 is a research and validation engine whose purpose is to determine whether a QQQ 1DTE strategy has a real, statistically defensible positive expected value and whether its stated probabilities/confidence are actually calibrated. Live execution is explicitly out of scope until all Phase 1 gates are passed.

The system should eventually be able to answer:
1. What is the probability of a defined market/trade outcome?
2. Is that probability calibrated?
3. Does the associated options trade have positive expected value after spread, slippage, commissions, and realistic execution?
4. In which market regimes does the strategy work or fail?
5. When should the correct answer be NO TRADE?
6. Is model performance degrading over time?
7. Can all historical and live decisions be reproduced and audited?

==================================================
PHASE 1A — FORMAL EXPERIMENT SPECIFICATION
==================================================

Before coding the model, create a formal specification document (e.g. PHASE_1_SPEC.md). Treat it as the system's constitution. Do not allow later code to silently change these definitions.

Define:

INSTRUMENT
- Primary underlying: QQQ
- Primary options: QQQ 1DTE options
- Clearly define whether "1DTE" means the next listed expiration relative to the prediction timestamp.
- Handle expiration/holiday/weekend rules explicitly.

TRADING/PREDICTION WINDOW
- Define regular market hours.
- Define exactly which prediction timestamps are evaluated (initially use a configurable schedule such as every 5 minutes, but make this configurable).
- Define when entries are allowed and when new entries stop.
- Define maximum holding period.

PREDICTION TARGETS
Do NOT use vague targets such as "QQQ goes up." Define explicit labels.

At minimum support:
A. Direction:
   "Will QQQ be higher than X at a defined future horizon?"
B. Magnitude:
   "Will QQQ move at least +0.50% before the defined cutoff?"
C. Option outcome:
   "Will the selected option reach +30% before -20%?"
D. Risk:
   "Will the stop be hit before the target?"

All thresholds and horizons must be configurable.

TRADE DEFINITIONS
Define:
- Entry condition
- Candidate option selection
- Target
- Stop
- Maximum holding period
- What constitutes WIN, LOSS, BREAKEVEN, EXPIRED/UNRESOLVED
- Position sizing rules for research purposes
- Maximum number of simultaneous trades
- Minimum liquidity requirements
- Maximum acceptable bid/ask spread
- Commission assumptions
- Slippage assumptions

NO-TRADE MUST BE A VALID OUTCOME.
The system must never force itself to choose CALL or PUT.

==================================================
PHASE 1B — DATA REQUIREMENTS & DATA-SOURCE DECISION
==================================================

Build a data inventory before building ML.

UNDERLYING DATA
Initially support:
- QQQ
- NQ
- ES
- VIX
- SPY
- SOXX
- NVDA
- AMD
- AVGO
- TSM
- DXY
- US 2Y yield
- US 10Y yield

Capture appropriate historical OHLCV/intraday data and timestamps.

OPTIONS DATA
For QQQ options, ideally capture point-in-time:
- timestamp
- expiration
- strike
- call/put
- bid
- ask
- last
- volume
- open interest where legitimately available at that timestamp
- implied volatility
- Greeks if available
- underlying price
- quote conditions/quality where available

CRITICAL:
Do not pretend that an end-of-day options chain or today's open interest can be used as if it were known historically at an earlier time.

Before implementing the backtester, explicitly evaluate and document the historical options-data source. IBKR is useful for live/current market data and eventual execution, but do not assume IBKR alone supplies the historical expired-options dataset required for robust backtesting. If historical options data is insufficient, identify an appropriate historical provider and document cost, coverage, granularity, licensing, and limitations.

Do not proceed to serious backtesting until historical options data requirements are satisfied or a clearly documented limitation is accepted.

==================================================
PHASE 1C — DATA INGESTION & STORAGE
==================================================

Use a robust architecture such as:
- Python
- Parquet for large historical research datasets
- PostgreSQL (or an equivalent relational DB) for metadata, predictions, trades, model versions, experiments, and audit records

Design schemas before implementation.

At minimum maintain:
1. raw_market_data
2. raw_options_data
3. cleaned_market_data
4. cleaned_options_data
5. feature_snapshots
6. predictions
7. trade_candidates
8. simulated_trades
9. model_versions
10. calibration_results
11. validation_runs
12. regime_labels
13. data_quality_events

Every important record should have timestamps and provenance.

==================================================
PHASE 1D — DATA QUALITY ENGINE
==================================================

Before ML, implement automated QA/QC.

For every observation/check:
- Timestamp valid?
- Timestamp timezone correct?
- Market open/closed status correct?
- Duplicate records?
- Missing records?
- Unexpected gaps?
- Bid > 0?
- Ask > 0?
- Bid <= Ask?
- Zero/negative/invalid prices?
- Unreasonable spread?
- Invalid option contract?
- Correct expiration?
- Contract actually existed at the timestamp?
- Underlying price available?
- Required features available?
- Future information accidentally present?
- Suspicious volume/open-interest changes?
- Corporate-action/data-adjustment issues where relevant?

Never silently fill critical financial data without documenting the method.

Every rejected record should have a reason.

Create a data-quality report such as:
- Days loaded
- Bars expected/received
- Missing %
- Duplicate count
- Invalid quote count
- Timestamp errors
- Leakage checks
- Coverage by instrument
- Coverage by date
- Options-chain coverage

Do not proceed if critical data-quality gates fail.

==================================================
PHASE 1E — POINT-IN-TIME / LEAKAGE PROTECTION
==================================================

This is a hard architectural requirement.

Every feature must have an "available_at" timestamp.

At prediction time T, the model may use only information that was genuinely available at or before T.

Examples:
- No future price
- No future volume
- No later option quote
- No end-of-day OI inserted into a morning prediction
- No future economic release result
- No future earnings outcome
- No future volatility information

Economic calendar information may be used only according to what was known at that time:
- Scheduled event known beforehand = allowed
- Actual event result not yet released = forbidden

Implement automated leakage tests.

The backtester must enforce temporal causality in code rather than relying only on developer discipline.

==================================================
PHASE 1F — FEATURE ENGINE
==================================================

Start with approximately 20–30 carefully chosen features, NOT hundreds.

Potential categories:

PRICE STRUCTURE
- QQQ price relative to VWAP
- Distance from VWAP
- Previous-day high/low
- Overnight high/low
- Opening range
- ATR
- Distance from important levels

MOMENTUM
- 5-minute return
- 15-minute return
- 30-minute return
- 60-minute return
- Momentum acceleration where justified

VOLUME
- Volume
- Relative volume
- Volume vs historical baseline

CROSS-MARKET
- NQ return
- ES return
- VIX level/change
- SPY relationship
- SOXX
- NVDA
- AMD
- AVGO
- TSM
- DXY
- 2Y/10Y yield changes

MARKET STRUCTURE/BREADTH
- Breadth if reliable historical data is available
- Trend/chop measurements
- Relative strength

OPTIONS
Only use options features that are truly available point-in-time:
- IV
- IV rank/percentile if valid historically
- spread
- volume
- OI
- gamma/exposure metrics only if reconstructable without leakage
- expected move

TIME
- Minutes since open
- Day of week
- Time to expiration
- Expiration-day classification

Document every feature:
- Definition
- Formula
- Data source
- Timestamp availability
- Missing-data behavior
- Why it might matter
- Leakage risk

==================================================
PHASE 1G — BASELINE MODELS
==================================================

Do NOT start with an LLM.

First build a simple baseline:
MODEL 0:
- Historical/conditional baseline
- Naive probability estimate

Then:
MODEL 1:
- Logistic regression

Then:
MODEL 2:
- Gradient-boosted tree model such as XGBoost/LightGBM or an equivalent well-supported implementation

Optionally evaluate:
- Random forest
- Neural network only after simpler models are understood

The objective is not to find the most complicated model. The objective is to determine whether the features contain genuine predictive information.

Compare every model against the baseline.

If a sophisticated model cannot materially outperform a simple baseline after realistic costs and out-of-sample validation, do not assume complexity is valuable.

==================================================
PHASE 1H — SEPARATE UNDERLYING PREDICTION FROM OPTION SELECTION
==================================================

Do not allow the model to retrospectively choose the option that performed best.

Use two conceptual stages:

STAGE 1:
Predict underlying behavior.
Example:
P(QQQ reaches +0.50% before cutoff) = 0.68

STAGE 2:
Given the prediction and only point-in-time information, evaluate candidate options.

For each candidate contract:
- Entry bid/ask
- Estimated realistic fill
- IV
- Greeks
- Expiration
- Strike
- Liquidity
- Spread
- Expected payoff
- Stop/target behavior
- Expected value after costs

The option-selection process must run exactly as it would have run in real time.

==================================================
PHASE 1I — REALISTIC OPTIONS BACKTESTER
==================================================

Build a true event-driven backtester.

It must simulate:
- Signal generation
- Contract selection
- Entry
- Fill assumptions
- Bid/ask spread
- Slippage
- Commission/fees
- Latency
- Target
- Stop
- Expiration
- Exit

Do NOT use fantasy fills.

At minimum test:
1. Conservative: buy at ask / sell at bid
2. Moderate: realistic inside-spread fill model
3. Optimistic: midpoint

Compare all three.

The system must report how sensitive results are to execution assumptions.

Include:
- Maximum favorable excursion (MFE)
- Maximum adverse excursion (MAE)
- P&L
- Return
- R multiple
- Holding time
- Slippage
- Spread cost
- Fees
- Target/stop reason
- Unfilled trades

==================================================
PHASE 1J — TIME-SERIES / WALK-FORWARD VALIDATION
==================================================

Do NOT use a random train/test split.

Use chronological walk-forward testing.

Example:
Train: 2022–2024
Validate: 2025
Test: 2026

Then roll forward as appropriate.

Use purging/embargo concepts where labels overlap or observations are temporally dependent.

Never tune hyperparameters or thresholds using the final untouched test period.

Maintain:
- Training period
- Validation period
- Test period
- Exact dataset version
- Feature version
- Model version
- Code version

Every result must be reproducible.

==================================================
PHASE 1K — PERFORMANCE METRICS
==================================================

Do NOT optimize solely for win rate.

Track:
- Win rate
- Average winner
- Average loser
- Expectancy
- Profit factor
- Average R
- Sharpe-like risk-adjusted measures where appropriate
- Maximum drawdown
- Drawdown duration
- Consecutive losses
- Tail losses
- Daily/weekly/monthly P&L
- Number of trades
- Trade frequency
- Slippage
- Transaction costs

Core expectancy concept:
Expected return ≈
(P(win) × average win) -
(P(loss) × average loss) -
costs

The system must distinguish statistical prediction quality from actual trading profitability.

==================================================
PHASE 1L — PROBABILITY CALIBRATION
==================================================

Only after generating genuinely out-of-sample predictions, calibrate probabilities.

A model saying "82%" must mean something.

Evaluate:
- Reliability/calibration curve
- Brier score
- Log loss
- Expected calibration error
- Confidence intervals
- Sample size by confidence bucket

Use a separate calibration dataset from the model-training data.

Evaluate methods such as:
- Platt/sigmoid scaling
- Isotonic regression
- Temperature scaling where appropriate

Example desired behavior:

Predicted 50–60% -> actual ~50–60%
Predicted 60–70% -> actual ~60–70%
Predicted 70–80% -> actual ~70–80%
Predicted 80–90% -> actual ~80–90%

If the model says 85% but historically succeeds only 65%, report the calibrated probability rather than the raw probability.

Never display raw model confidence as if it were proven probability.

==================================================
PHASE 1M — REGIME ENGINE
==================================================

Identify and evaluate market regimes.

At minimum:
TREND
- Strong trend
- Weak trend
- Range/chop

VOLATILITY
- Low
- Normal
- High
- Extreme

MARKET STRUCTURE
- Bull
- Bear
- Reversal
- Chop

EVENT
- Normal
- CPI
- FOMC
- Jobs/NFP
- Major Fed events/speeches
- Major earnings/event risk

Evaluate model performance separately by regime.

Example:
Overall 75% may hide:
- Normal low-vol trend: 82%
- High-vol: 58%
- Macro event: 51%

The system should learn where it works and where it should reduce confidence or refuse trades.

Do not create overly specific regime buckets that are supported by tiny samples.

==================================================
PHASE 1N — NO-TRADE DECISION ENGINE
==================================================

NO TRADE must be a first-class output.

Possible outputs:
- CALL
- PUT
- NO TRADE

Example:
Call probability = 62%
Put probability = 58%
Expected value = negative
Regime = unstable
Liquidity = poor

Decision:
NO TRADE

Do not force a trade simply because one side has a slightly higher probability.

==================================================
PHASE 1O — TRADE JOURNAL / AUDIT TRAIL
==================================================

Every prediction must be permanently logged.

Record at minimum:
- prediction_id
- timestamp
- underlying price
- option chain snapshot/reference
- feature values
- feature version
- regime
- model version
- raw probability
- calibrated probability
- calibration version
- candidate contracts
- selected contract
- bid/ask
- assumed entry
- target
- stop
- expected value
- actual MFE
- actual MAE
- outcome
- P&L
- costs
- reason for decision
- whether trade was CALL/PUT/NO TRADE

The journal is the system's historical memory.

==================================================
PHASE 1P — MODEL VERSIONING & PROMOTION
==================================================

Never allow a new model to automatically replace the production model.

Maintain:
- Model ID
- Version
- Training data range
- Feature version
- Hyperparameters
- Calibration method/version
- Code commit/version
- Validation results

Example:

CURRENT MODEL:
- Expectancy +0.18R
- Calibration error 0.04
- Max DD 9%

CANDIDATE MODEL:
- Expectancy +0.23R
- Calibration error 0.03
- Max DD 8%

Candidate must pass defined promotion gates:
- Better out-of-sample performance
- No unacceptable degradation
- Acceptable calibration
- Robust across regimes
- Positive after transaction costs
- Adequate sample size
- No suspicious feature/leakage behavior
- Stable across walk-forward periods

If it fails:
KEEP CURRENT MODEL.

==================================================
PHASE 1Q — DRIFT DETECTION
==================================================

Markets change.

Monitor whether:
- Feature distributions change
- Prediction distributions change
- Calibration deteriorates
- Win rate deteriorates
- Expectancy deteriorates
- Regime frequency changes

Example:
Historical 80% predictions -> 78% success
Recent 80% predictions -> 59% success

Flag:
MODEL DRIFT

Potential response:
- Reduce confidence
- Disable strategy
- PAPER ONLY
- Retrain
- Revalidate
- Require model promotion process before deployment

Do not let a degraded model silently keep trading.

==================================================
PHASE 1R — UNCERTAINTY & SAMPLE-SIZE AWARENESS
==================================================

A probability with n=4 should not be treated like the same probability with n=4,872.

Display:
- Probability
- Sample size
- Confidence interval or uncertainty estimate
- Comparable historical sample size

Example:
82% probability, n=31 = low statistical support
82% probability, n=4,872 = much stronger evidence

Do not overstate certainty.

==================================================
PHASE 1S — OVERFITTING / BIAS CONTROLS
==================================================

Explicitly test for:
- Look-ahead bias
- Data leakage
- Survivorship bias where relevant
- Selection bias
- Options-contract selection bias
- Overfitting
- Multiple-testing/data-mining bias
- Regime overfitting
- Small-sample artifacts
- Unrealistic fills
- Latency assumptions
- Missing-data artifacts
- Overlapping-label dependence

If a 97% win-rate bucket contains 11 trades, flag it as unreliable rather than celebrating it.

==================================================
PHASE 1T — LIVE PAPER SYSTEM
==================================================

Only after historical validation passes, connect live market data.

Still NO real orders.

At every live prediction timestamp:
1. Pull current data
2. Validate data
3. Generate features
4. Identify regime
5. Generate predictions
6. Calibrate probability
7. Evaluate candidate options
8. Calculate expected value
9. Produce CALL/PUT/NO TRADE
10. Record the decision
11. Simulate realistic execution
12. Track outcome

Example output:

QQQ: $742.31
Regime: Bull Trend
CALL probability: 76%
PUT probability: 24%
Selected: QQQ 745C 1DTE
Bid: $3.70
Ask: $3.85
Simulated entry: $3.85
Target: $4.95
Stop: $3.05
Expected value: +0.31R
Data quality: 99.7%
Decision: TRADE

But the system must remain paper-only.

==================================================
PHASE 1U — DASHBOARD
==================================================

Build the visual dashboard LAST, not first.

Dashboard should expose the underlying evidence, not hide it.

Display:
- QQQ
- Market regime
- CALL probability
- PUT probability
- Calibrated confidence
- Sample size
- Expected value
- Candidate contract
- Bid/ask
- Assumed fill
- Target
- Stop
- Data quality
- Model version
- Calibration status
- Current model health
- Recent prediction accuracy
- Drift status
- NO TRADE reason

The dashboard is a visualization layer, not the decision engine.

==================================================
PHASE 1V — FINAL VALIDATION GATES
==================================================

Do not move toward automated live execution until ALL of these are satisfied:

1. Data coverage is adequate.
2. Data-quality checks pass.
3. Point-in-time integrity is verified.
4. Leakage tests pass.
5. Baseline is established.
6. ML model beats baseline out-of-sample.
7. Options selection is point-in-time.
8. Backtester models bid/ask and realistic execution.
9. Transaction costs are included.
10. Walk-forward testing is positive.
11. Results are robust across reasonable execution assumptions.
12. Probability calibration is demonstrated.
13. Regime behavior is understood.
14. NO TRADE behavior is validated.
15. Sample sizes are adequate.
16. No suspicious overfitting is found.
17. Model versioning/reproducibility works.
18. Drift monitoring works.
19. Paper trading reproduces the general behavior seen in research.
20. Performance remains stable during a sufficiently long live paper period.

==================================================
TECHNOLOGY GUIDELINES
==================================================

Preferred initial stack:
- Python
- pandas/polars as appropriate
- NumPy
- scikit-learn
- XGBoost or LightGBM if justified
- PostgreSQL
- Parquet
- FastAPI or another lightweight API layer if needed
- Streamlit or React for the dashboard, but only after the engine works
- Git for version control
- pytest for testing
- Docker where useful

Keep components modular:
- data/
- ingestion/
- validation/
- features/
- labels/
- models/
- calibration/
- regimes/
- backtesting/
- execution_sim/
- journal/
- monitoring/
- dashboard/
- tests/
- configs/

Use configuration files rather than hard-coding trading parameters.

==================================================
TESTING REQUIREMENTS
==================================================

Write tests alongside the system.

At minimum:
- Unit tests for indicators/features
- Timestamp tests
- Timezone tests
- Data-quality tests
- Option-chain selection tests
- Label-generation tests
- Leakage tests
- Backtest accounting tests
- Fill/slippage tests
- Calibration tests
- Walk-forward split tests
- Model serialization/version tests
- Reproducibility tests

Create synthetic test cases where the expected result is known exactly.

==================================================
DEVELOPMENT PROCESS
==================================================

DO NOT attempt to build everything in one giant step.

Proceed in milestones:

MILESTONE 1
Create PHASE_1_SPEC.md and architecture.

MILESTONE 2
Research and document data requirements/providers, especially historical QQQ 1DTE options.

MILESTONE 3
Build ingestion/storage.

MILESTONE 4
Build data-quality validation.

MILESTONE 5
Build point-in-time feature engine.

MILESTONE 6
Build label-generation system.

MILESTONE 7
Build baseline model.

MILESTONE 8
Build logistic regression.

MILESTONE 9
Build gradient-boosted model.

MILESTONE 10
Build chronological walk-forward validation.

MILESTONE 11
Build realistic options backtester.

MILESTONE 12
Add transaction costs/slippage/latency.

MILESTONE 13
Build probability calibration.

MILESTONE 14
Build regime analysis.

MILESTONE 15
Build NO TRADE logic.

MILESTONE 16
Build prediction/trade journal.

MILESTONE 17
Build model versioning and promotion.

MILESTONE 18
Build drift monitoring.

MILESTONE 19
Run full historical validation.

MILESTONE 20
Connect live market data in PAPER MODE.

MILESTONE 21
Run live paper validation.

MILESTONE 22
Build dashboard.

Only after these milestones should we discuss Phase 2 (advanced/adaptive ML and AI analyst) and later Phase 3 (safe broker execution).

==================================================
AI / LLM ROLE
==================================================

Do NOT use an LLM as the core numerical predictor initially.

The LLM can later be used for:
- Explaining why a quantitative model generated a signal
- Summarizing market context
- Reading news/event information
- Producing human-readable reports
- Assisting research
- Suggesting hypotheses/features for testing

Any hypothesis suggested by the LLM must be quantitatively tested before being incorporated into the trading model.

The LLM must never be allowed to fabricate confidence.

==================================================
IMPORTANT DEVELOPMENT RULES
==================================================

1. Do not skip steps.
2. Do not silently change definitions.
3. Do not assume data exists; verify.
4. Do not use future information.
5. Do not use today's information to reconstruct historical decisions.
6. Do not choose historically best-performing options retrospectively.
7. Do not optimize solely for win rate.
8. Do not trust backtests using unrealistic fills.
9. Do not call a raw ML score "confidence" until calibrated.
10. Do not automatically promote a new model.
11. Do not force trades.
12. Do not use an LLM to hide weak quantitative evidence.
13. Every result must be reproducible.
14. Every important assumption must be configurable and documented.
15. If evidence is insufficient, say so.
16. If a proposed component cannot be validated, stop and flag it rather than inventing a workaround.
17. Keep a clear distinction between prediction accuracy and trading profitability.
18. Treat the system as research software until Phase 1 validation is complete.
19. Never place real orders during Phase 1.
20. Prioritize correctness over speed.

==================================================
FIRST TASK
==================================================

Do NOT start by writing the entire application.

First:
1. Restate the architecture in your own words.
2. Identify any remaining ambiguities in the specification.
3. Produce PHASE_1_SPEC.md.
4. Produce an implementation plan with milestones and dependencies.
5. Produce a data requirements matrix.
6. Identify the exact historical options data needed for QQQ 1DTE research.
7. Explain what can be obtained from IBKR versus what requires another historical source.
8. Propose the initial database schema.
9. Propose the Python project structure.
10. Define the first test suite.
11. Define the acceptance criteria for each milestone.
12. Do not build live execution.
13. Do not claim the strategy is profitable until the validation process demonstrates it.

The ultimate goal is not to create a flashy "AI trading bot."

The goal is to build a rigorous, auditable system that can honestly determine:

"Does this QQQ 1DTE strategy have a repeatable edge, how large is that edge, under what conditions does it exist, how reliable are the stated probabilities, and when should the system stay out of the market?"

Only after that has been demonstrated should automation and advanced AI be considered.
