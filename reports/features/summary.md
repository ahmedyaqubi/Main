# Feature snapshots f2: summary

Generated 2026-10-07 02:04 UTC, code c82446d20d18. Sessions 882 (2023-03-28 → 2026-10-02), rows 1,572,480 (sessions x timestamps x 28 features).

| feature | rows | missing | missing % | p01 | p50 | p99 |
|---|---|---|---|---|---|---|
| vwap_dist | 56,160 | 0 | 0.00% | -0.00985 | 0.0004161 | 0.008647 |
| ret_since_prev_close | 56,160 | 64 | 0.11% | -0.02759 | 0.001114 | 0.02675 |
| dist_prev_high | 56,160 | 64 | 0.11% | -0.03993 | -0.0038 | 0.01954 |
| dist_prev_low | 56,160 | 64 | 0.11% | -0.02081 | 0.007947 | 0.04332 |
| or_position | 56,160 | 0 | 0.00% | -4.354 | 0.6211 | 4.261 |
| overnight_gap | 56,160 | 64 | 0.11% | -0.01965 | 0.001037 | 0.0227 |
| range_atr | 56,160 | 960 | 1.71% | 0.1903 | 0.6072 | 1.746 |
| ret_5m | 56,160 | 0 | 0.00% | -0.003018 | 2.495e-05 | 0.00271 |
| ret_15m | 56,160 | 0 | 0.00% | -0.005318 | 7.463e-05 | 0.004732 |
| ret_30m | 56,160 | 2,646 | 4.71% | -0.007485 | 0.0001245 | 0.006462 |
| ret_60m | 56,160 | 7,938 | 14.13% | -0.01021 | 0.0002282 | 0.008926 |
| mom_accel | 56,160 | 2,646 | 4.71% | -0.006632 | -5.701e-05 | 0.00726 |
| rv_30m | 56,160 | 3,528 | 6.28% | 0.03792 | 0.1099 | 0.3856 |
| rel_volume | 56,160 | 640 | 1.14% | 0.4537 | 0.9732 | 2.332 |
| spy_qqq_rel_15m | 56,160 | 26 | 0.05% | -0.002037 | -1.741e-05 | 0.00229 |
| soxx_ret_15m | 56,160 | 123 | 0.22% | -0.01152 | 9.507e-05 | 0.01066 |
| megacap_ret_15m | 56,160 | 79 | 0.14% | -0.01077 | 9.497e-05 | 0.009422 |
| uup_ret_60m | 56,160 | 8,421 | 14.99% | -0.002727 | 0 | 0.002604 |
| ief_ret_60m | 56,160 | 7,938 | 14.13% | -0.002931 | 0 | 0.00275 |
| shy_ret_60m | 56,160 | 8,388 | 14.94% | -0.0007383 | 0 | 0.0007334 |
| vix_prev_close | 56,160 | 0 | 0.00% | 12.22 | 16.4 | 32.64 |
| straddle_move | 56,160 | 30 | 0.05% | 0.004628 | 0.008699 | 0.02106 |
| atm_spread_pct | 56,160 | 30 | 0.05% | 0.002996 | 0.008073 | 0.02185 |
| put_call_imbalance | 56,160 | 30 | 0.05% | -0.1728 | -0.008489 | 0.1646 |
| minutes_since_open | 56,160 | 0 | 0.00% | 15 | 170 | 330 |
| day_of_week | 56,160 | 0 | 0.00% | 0 | 2 | 4 |
| cal_days_to_expiry | 56,160 | 0 | 0.00% | 1 | 1 | 4 |
| macro_event_today | 56,160 | 0 | 0.00% | 0 | 0 | 1 |

## Missing values by reason

| feature | reason | rows |
|---|---|---|
| atm_spread_pct | no_valid_quote | 30 |
| dist_prev_high | insufficient_history | 64 |
| dist_prev_low | insufficient_history | 64 |
| ief_ret_60m | window_before_open | 7,938 |
| megacap_ret_15m | no_data | 79 |
| mom_accel | window_before_open | 2,646 |
| overnight_gap | insufficient_history | 64 |
| put_call_imbalance | no_valid_quote | 30 |
| range_atr | insufficient_history | 960 |
| rel_volume | insufficient_history | 640 |
| ret_30m | window_before_open | 2,646 |
| ret_60m | window_before_open | 7,938 |
| ret_since_prev_close | insufficient_history | 64 |
| rv_30m | window_before_open | 3,528 |
| shy_ret_60m | no_valid_quote | 450 |
| shy_ret_60m | window_before_open | 7,938 |
| soxx_ret_15m | no_valid_quote | 123 |
| spy_qqq_rel_15m | no_valid_quote | 26 |
| straddle_move | no_valid_quote | 30 |
| uup_ret_60m | no_valid_quote | 483 |
| uup_ret_60m | window_before_open | 7,938 |

## Cross-market NBBO data quality (M4 quote checks)

| symbol | raw | cleaned | rejected | sessions < 98% valid RTH quotes | worst session |
|---|---|---|---|---|---|
| AMD | 510,412 | 510,412 | 0 | 0 | 1.0000 |
| AVGO | 435,896 | 435,896 | 0 | 0 | 0.9949 |
| IEF | 451,821 | 451,821 | 0 | 1 | 0.9795 |
| NVDA | 593,616 | 593,615 | 1 | 1 | 0.0000 |
| SHY | 434,051 | 434,051 | 0 | 273 | 0.7846 |
| SOXX | 437,479 | 437,479 | 0 | 2 | 0.8436 |
| SPY | 631,874 | 631,874 | 0 | 0 | 1.0000 |
| TSM | 447,487 | 447,487 | 0 | 0 | 0.9974 |
| UUP | 476,679 | 476,679 | 0 | 360 | 0.8256 |
