# First Test Suite — proposal (Milestone 1)

**Status: DRAFT.** Test names are the IDs the code will use (`test_<id>_<name>`). Every
numerical test uses a synthetic fixture with an exactly known answer. Property-based tests use
`hypothesis`. "Milestone" shows when each test gets implemented. **Leakage and timestamp tests
come first**, because every later component depends on them.

## T-TIME — timestamps, timezones, calendar (M3)
| ID | Proves |
|---|---|
| T-TIME-01 `utc_roundtrip` | every stored timestamp is tz-aware UTC; naive datetimes are rejected at the boundary |
| T-TIME-02 `et_conversion_dst` | 09:30 ET maps to 14:30 UTC in winter and 13:30 UTC in summer; spring-forward/fall-back sessions have the correct bar count (390) |
| T-TIME-03 `early_close_sessions` | known early-close days (e.g. 2023-11-24, 2024-07-03) yield a 13:00 close, 210 bars, and shifted entry/exit cutoffs |
| T-TIME-04 `holiday_no_session` | full holidays (e.g. 2023-04-07 Good Friday) have no prediction timestamps |
| T-TIME-05 `prediction_schedule` | a normal day yields exactly 64 timestamps 09:45…15:00; property: all on 5-min boundaries, all within RTH |
| T-TIME-06 `bar_convention_start_vs_end` | a vendor bar labelled with its start time gets `available_at = start + 1m`; mixing up the convention fails |
| T-TIME-07 `one_dte_resolution` | for D = Fri 2023-03-10 → Mon 03-13; D before Good Friday → following Mon, if listed; D where the D+1 expiration isn't in the chain → `NO_1DTE_EXPIRY` |
| T-TIME-08 `pre_daily_era_excluded` | sessions before 2022-11-14 are excluded from option labels with a logged reason |

## T-LEAK — point-in-time / leakage (M3 core reader, M5 features, M6 labels)
| ID | Proves |
|---|---|
| T-LEAK-01 `asof_reader_filters` | `AsOfReader(T)` returns only rows with `available_at <= T` (property test over random T and data) |
| T-LEAK-02 `asof_reader_raises_on_future` | explicitly requesting data after T raises `LookAheadError`, rather than returning empty or clipped data |
| T-LEAK-03 `feature_available_at_stamp` | every feature row's `available_at` = max of its inputs' and ≤ T; the writer refuses a row that violates this |
| T-LEAK-04 `planted_future_canary` | a synthetic series where bar t+1 encodes the label: a feature pipeline that peeked would hit ~100% accuracy. Test asserts the pipeline output does not depend on the planted future values (perturbing data after T leaves features at T unchanged) |
| T-LEAK-05 `future_perturbation_invariance` | property: for random T, randomly mutating all data with `available_at > T` leaves every feature at T bit-identical |
| T-LEAK-06 `unfinished_bar_excluded` | at T = 10:02:30 the 10:02 bar (ends 10:03) is not visible; the rolling windows stop at the 10:01 bar |
| T-LEAK-07 `oi_prior_day_only` | OI dated D is invisible during D; OI dated D−1 becomes visible at 09:30 D, not before |
| T-LEAK-08 `daily_bar_not_intraday` | the daily close of D is invisible at any T within D |
| T-LEAK-09 `macro_actual_vs_scheduled` | at T before the CPI release, the scheduled flag is visible and the actual value is not; after release + lag, both are visible |
| T-LEAK-10 `import_contract` | `features`, `regimes`, `execution_sim.select`, and `models` inference cannot import `labels` (import-linter) |
| T-LEAK-11 `scaler_fit_train_only` | the fitted standardiser's statistics equal the training-fold statistics exactly; test-fold data changes nothing |
| T-LEAK-12 `regime_thresholds_fold_fit` | the VIX tercile cut points come from the training fold only |
| T-LEAK-13 `shuffled_label_auc` | a model trained on time-shuffled labels gives OOS AUC ≈ 0.5 (gate 4 canary) |

## T-DQ — data quality (M4)
| ID | Proves |
|---|---|
| T-DQ-01 `bid_gt_ask_rejected` | a crossed quote is rejected with reason `BID_GT_ASK` and a `data_quality_events` row |
| T-DQ-02 `nonpositive_prices` | bid ≤ 0 / ask ≤ 0 / NaN are each rejected with their own reason |
| T-DQ-03 `duplicates` | exact and same-key duplicates are detected and counted, never silently deduped |
| T-DQ-04 `missing_bars` | a session with 3 missing bars reports 387/390 and emits MISSING_BAR events at the right timestamps |
| T-DQ-05 `outside_rth` | out-of-session records are flagged correctly, including early-close days |
| T-DQ-06 `invalid_contract` | a contract whose expiration isn't a listed date, or with multiplier ≠ 100, is rejected |
| T-DQ-07 `contract_not_yet_listed` | a quote before the contract's first listed date is rejected |
| T-DQ-08 `no_silent_fill` | the cleaned dataset row count + rejected count = raw count (conservation) |
| T-DQ-09 `dq_report_numbers` | the DQ report for a synthetic dataset matches hand-computed counts exactly |

## T-LBL — labels (M6)
| ID | Proves |
|---|---|
| T-LBL-01 `direction_deadband` | synthetic paths: +4 bp → A_up = 0, +6 bp → A_up = 1 at d = 5 bp |
| T-LBL-02 `magnitude_touch` | B_up = 1 when a single bar high touches the threshold exactly (≥) |
| T-LBL-03 `option_target_first` / `stop_first` | hand-built quote paths give WIN / LOSS / TIME_EXIT correctly, checked on the bid |
| T-LBL-04 `ambiguous_bar_stop_first` | a bar hitting both levels → LOSS + `ambiguous_bar = true` |
| T-LBL-05 `horizon_clipped_at_forced_exit` | T = 15:00 → T_end = 15:50, not 16:30 |
| T-LBL-06 `missing_bar_invalid` | a gap inside W → INVALID with reason, not interpolated |
| T-LBL-07 `up_down_not_complements` | a flat path gives both B_up = 0 and B_dn = 0 |

## T-SEL — option selection (M11)
| ID | Proves |
|---|---|
| T-SEL-01 `atm_first_otm` | S = 512.40 with strikes {511, 512, 513} → call 513, put 512 |
| T-SEL-02 `exactly_at_strike` | S = 512.00 → call 512, put 512 |
| T-SEL-03 `only_pit_chain` | adding a better-looking contract with `available_at > T_e` doesn't change the selection |
| T-SEL-04 `no_fallback` | an illiquid selected contract → NO_TRADE(`SELECTED_CONTRACT_ILLIQUID`) even if the neighbour is liquid |
| T-SEL-05 `deterministic` | property: the same inputs give the same output across 1,000 random chains |

## T-FILL / T-BT — fills and accounting (M11–M12)
| ID | Proves |
|---|---|
| T-FILL-01 `three_models` | bid 1.00 / ask 1.10: conservative buy 1.10, moderate 1.08 (1.075 rounded against the trader), optimistic 1.05 |
| T-FILL-02 `tick_rounding_against_trader` | buys round up, sells round down |
| T-FILL-03 `triggers_use_bid` | the optimistic model doesn't trigger a target that only the mid reached |
| T-BT-01 `pnl_accounting` | hand-computed net P&L, costs, and R multiple for 5 synthetic trades match exactly |
| T-BT-02 `one_position_at_a_time` | signals during an open position are logged as BLOCKED_POSITION_OPEN |
| T-BT-03 `max_entries_per_day` | the 4th signal in a day isn't traded |
| T-BT-04 `forced_flat` | an open position is exited at 15:50; EXPIRED never occurs with `allow_overnight = false` |
| T-BT-05 `clock_monotonic` | the quote cursor can't move backward and never returns a quote later than the clock |

## T-WF — walk-forward (M10)
| ID | Proves |
|---|---|
| T-WF-01 `chronological_disjoint` | train < calib < test for every fold, no overlap |
| T-WF-02 `embargo` | ≥ 1 full session between train end and the next block |
| T-WF-03 `final_holdout_locked` | accessing the holdout without registering it raises an error; the access is logged |
| T-WF-04 `no_random_split` | the splitter API has no shuffle option (static check) |

## T-CAL — calibration (M13)
| ID | Proves |
|---|---|
| T-CAL-01 `ece_known` | ECE on a hand-built bin set equals the analytic value |
| T-CAL-02 `perfectly_calibrated_synthetic` | y ~ Bernoulli(p): ECE → small, slope ≈ 1 within tolerance |
| T-CAL-03 `separate_calibration_data` | calibration refuses to fit on rows that overlap the model's training period |
| T-CAL-04 `uncalibrated_forces_no_trade` | missing calibration version → decision NO_TRADE |

## T-REP / T-CFG / T-SAFE — reproducibility, config, safety (from M1/M3)
| ID | Proves |
|---|---|
| T-CFG-01 `config_matches_spec_keys` | every `config:` key named in PHASE_1_SPEC.md exists in `configs/phase1.yaml` (parses the spec) |
| T-CFG-02 `config_hash_stable` | the same config gives the same hash regardless of key order |
| T-REP-01 `model_serialization_roundtrip` | save → load → identical predictions |
| T-REP-02 `replay_prediction` | `journal.replay(id)` reproduces the stored scores to 1e-9 |
| T-SAFE-01 `no_order_code` | the source tree has no order-placement identifiers or broker order endpoints |
| T-SMOKE-01 `package_imports` | (M1) the package and all subpackages import |

Implemented in M1: **T-SMOKE-01** and **T-SAFE-01**. Everything else waits for its milestone.
