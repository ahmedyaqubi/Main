# Regime analysis R1 (spec §9)

Generated 2026-10-07 19:33 UTC, code 161365e27bb3, run `regime-a1fc599d0e3b`. Test blocks 2024-05-28 → 2026-02-27 (440 sessions); final holdout (after 2026-04-02) not opened.

**Definitions.** Volatility: prior-session VIX close vs tercile cuts of the fold's training sessions (EXTREME merged into HIGH; training sessions with VIX ≥ 30 counted). Trend: efficiency ratio of the last 20 daily moves to the prior close, TREND above the training median else CHOP. Event: MACRO if CPI, FOMC, NFP is scheduled on the session and known by T. LOW_SUPPORT: fewer than 30 sessions (or 100 trades for trade tables); such cells are reported but never used to gate decisions. CIs: session-block bootstrap, 2000 reps, 95%.

## Thresholds per fold (fit on training sessions only, T-LEAK-12)

| fold | VIX cuts | ER median | training sessions | training VIX ≥ extreme | training ER unknown |
|---|---|---|---|---|---|
| 1 | 13.81 / 16.03 | 0.234 | 251 | 0 | 21 |
| 2 | 13.60 / 15.67 | 0.234 | 314 | 0 | 21 |
| 3 | 13.69 / 16.06 | 0.230 | 378 | 1 | 21 |
| 4 | 13.84 / 16.48 | 0.226 | 441 | 1 | 21 |
| 5 | 14.02 / 16.91 | 0.218 | 501 | 1 | 21 |
| 6 | 14.34 / 17.48 | 0.223 | 564 | 13 | 21 |
| 7 | 14.61 / 17.20 | 0.226 | 627 | 13 | 21 |

## Sessions per regime cell (test blocks)

| cell | fold 1 | fold 2 | fold 3 | fold 4 | fold 5 | fold 6 | fold 7 | pooled | support |
|---|---|---|---|---|---|---|---|---|---|
| HIGH/CHOP/MACRO | 1 | 4 | 3 | 2 | 1 | 1 | 3 | 15 | LOW_SUPPORT |
| HIGH/CHOP/NORMAL | 10 | 30 | 22 | 24 | 6 | 23 | 18 | 133 | ok |
| HIGH/TREND/MACRO | 2 | 3 | 0 | 6 | 3 | 0 | 0 | 14 | LOW_SUPPORT |
| HIGH/TREND/NORMAL | 7 | 12 | 1 | 29 | 17 | 0 | 2 | 68 | ok |
| LOW/CHOP/NORMAL | 0 | 0 | 1 | 0 | 0 | 0 | 7 | 8 | LOW_SUPPORT |
| LOW/TREND/MACRO | 4 | 0 | 1 | 0 | 0 | 0 | 0 | 5 | LOW_SUPPORT |
| LOW/TREND/NORMAL | 29 | 0 | 5 | 0 | 0 | 0 | 1 | 35 | ok |
| NORMAL/CHOP/MACRO | 0 | 0 | 2 | 0 | 0 | 4 | 5 | 11 | LOW_SUPPORT |
| NORMAL/CHOP/NORMAL | 9 | 11 | 18 | 0 | 8 | 16 | 25 | 87 | ok |
| NORMAL/TREND/MACRO | 0 | 1 | 2 | 0 | 4 | 1 | 0 | 8 | LOW_SUPPORT |
| NORMAL/TREND/NORMAL | 2 | 4 | 5 | 0 | 25 | 19 | 1 | 56 | ok |

## OD-9: does the trend axis separate outcomes?

Pre-declared test (owner, M14 Q4): stratified TREND - CHOP difference within volatility x event cells; keep the axis if any 95% CI excludes 0.

| quantity | TREND - CHOP | 95% CI | strata |
|---|---|---|---|
| C_call WIN rate | +0.0283 | [-0.0059, +0.0608] | 5 |
| baseline net CALL (conservative) | +12.9675 | [+3.2751, +22.9389] | 5 |
| C_put WIN rate | -0.0272 | [-0.0654, +0.0137] | 5 |
| baseline net PUT (conservative) | -12.7226 | [-22.7976, -2.7355] | 5 |

**Result: keep the trend axis (12 cells).**

## Baseline expectancy by single-axis buckets (mechanical baseline, NOT a strategy; net $)

| fill | side | axis | bucket | trades | sessions | mean net $ [CI] | support |
|---|---|---|---|---|---|---|---|
| CONSERVATIVE | C | volatility | LOW | 144 | 48 | +1.58 [-6.45, +9.28] | ok |
| CONSERVATIVE | C | volatility | NORMAL | 485 | 162 | -9.84 [-15.22, -4.73] | ok |
| CONSERVATIVE | C | volatility | HIGH | 690 | 230 | -3.55 [-11.15, +4.08] | ok |
| CONSERVATIVE | C | trend | TREND | 557 | 186 | +1.67 [-4.98, +8.79] | ok |
| CONSERVATIVE | C | trend | CHOP | 762 | 254 | -10.40 [-16.15, -4.81] | ok |
| CONSERVATIVE | C | event | NORMAL | 1,161 | 387 | -3.67 [-8.19, +1.15] | ok |
| CONSERVATIVE | C | event | MACRO | 158 | 53 | -17.31 [-31.00, -3.64] | ok |
| CONSERVATIVE | P | volatility | LOW | 144 | 48 | -12.08 [-19.48, -4.24] | ok |
| CONSERVATIVE | P | volatility | NORMAL | 485 | 162 | +2.90 [-3.44, +9.56] | ok |
| CONSERVATIVE | P | volatility | HIGH | 690 | 230 | -11.71 [-19.04, -4.31] | ok |
| CONSERVATIVE | P | trend | TREND | 557 | 186 | -13.09 [-19.58, -6.47] | ok |
| CONSERVATIVE | P | trend | CHOP | 762 | 254 | -1.47 [-8.16, +4.79] | ok |
| CONSERVATIVE | P | event | NORMAL | 1,161 | 387 | -7.43 [-12.57, -2.67] | ok |
| CONSERVATIVE | P | event | MACRO | 158 | 53 | +1.39 [-13.01, +15.99] | ok |
| MODERATE | C | volatility | LOW | 144 | 48 | +1.65 [-6.37, +9.34] | ok |
| MODERATE | C | volatility | NORMAL | 485 | 162 | -9.66 [-15.05, -4.54] | ok |
| MODERATE | C | volatility | HIGH | 690 | 230 | -2.92 [-10.42, +4.64] | ok |
| MODERATE | C | trend | TREND | 557 | 186 | +1.95 [-4.61, +8.99] | ok |
| MODERATE | C | trend | CHOP | 762 | 254 | -9.90 [-15.63, -4.35] | ok |
| MODERATE | C | event | NORMAL | 1,161 | 387 | -3.40 [-7.95, +1.41] | ok |
| MODERATE | C | event | MACRO | 158 | 53 | -15.87 [-29.43, -2.81] | ok |
| MODERATE | P | volatility | LOW | 144 | 48 | -11.81 [-19.22, -4.10] | ok |
| MODERATE | P | volatility | NORMAL | 485 | 162 | +3.63 [-2.56, +10.25] | ok |
| MODERATE | P | volatility | HIGH | 690 | 230 | -10.21 [-17.60, -2.81] | ok |
| MODERATE | P | trend | TREND | 557 | 186 | -12.55 [-18.88, -6.06] | ok |
| MODERATE | P | trend | CHOP | 762 | 254 | +0.01 [-6.70, +6.35] | ok |
| MODERATE | P | event | NORMAL | 1,161 | 387 | -6.26 [-11.44, -1.46] | ok |
| MODERATE | P | event | MACRO | 158 | 53 | +1.81 [-12.68, +16.42] | ok |

## Baseline expectancy by full cells (mechanical baseline, NOT a strategy; net $)

| fill | side | axis | bucket | trades | sessions | mean net $ [CI] | support |
|---|---|---|---|---|---|---|---|
| CONSERVATIVE | C | volatility+trend+event | LOW/TREND/NORMAL | 105 | 35 | +4.97 [-3.76, +13.91] | ok |
| CONSERVATIVE | C | volatility+trend+event | NORMAL/TREND/NORMAL | 168 | 56 | -3.51 [-11.43, +4.51] | ok |
| CONSERVATIVE | C | volatility+trend+event | LOW/TREND/MACRO | 15 | 5 | -7.80 [-35.00, +13.00] | LOW_SUPPORT |
| CONSERVATIVE | C | volatility+trend+event | NORMAL/CHOP/NORMAL | 261 | 87 | -12.17 [-19.74, -4.95] | ok |
| CONSERVATIVE | C | volatility+trend+event | HIGH/CHOP/NORMAL | 399 | 133 | -8.06 [-16.67, +1.13] | ok |
| CONSERVATIVE | C | volatility+trend+event | HIGH/TREND/MACRO | 42 | 14 | -18.04 [-46.66, +10.51] | LOW_SUPPORT |
| CONSERVATIVE | C | volatility+trend+event | HIGH/TREND/NORMAL | 204 | 68 | +11.67 [-2.10, +27.92] | ok |
| CONSERVATIVE | C | volatility+trend+event | HIGH/CHOP/MACRO | 45 | 15 | -19.00 [-52.20, +10.69] | LOW_SUPPORT |
| CONSERVATIVE | C | volatility+trend+event | NORMAL/TREND/MACRO | 23 | 8 | -22.01 [-51.40, -2.32] | LOW_SUPPORT |
| CONSERVATIVE | C | volatility+trend+event | LOW/CHOP/NORMAL | 24 | 8 | -7.40 [-25.74, +11.44] | LOW_SUPPORT |
| CONSERVATIVE | C | volatility+trend+event | NORMAL/CHOP/MACRO | 33 | 11 | -15.13 [-33.46, +4.45] | LOW_SUPPORT |
| CONSERVATIVE | P | volatility+trend+event | LOW/TREND/NORMAL | 105 | 35 | -15.30 [-23.10, -7.96] | ok |
| CONSERVATIVE | P | volatility+trend+event | NORMAL/TREND/NORMAL | 168 | 56 | -2.99 [-12.02, +6.40] | ok |
| CONSERVATIVE | P | volatility+trend+event | LOW/TREND/MACRO | 15 | 5 | +1.00 [-26.47, +41.73] | LOW_SUPPORT |
| CONSERVATIVE | P | volatility+trend+event | NORMAL/CHOP/NORMAL | 261 | 87 | +6.36 [-3.19, +15.80] | ok |
| CONSERVATIVE | P | volatility+trend+event | HIGH/CHOP/NORMAL | 399 | 133 | -7.55 [-16.79, +2.16] | ok |
| CONSERVATIVE | P | volatility+trend+event | HIGH/TREND/MACRO | 42 | 14 | +7.84 [-19.78, +34.60] | LOW_SUPPORT |
| CONSERVATIVE | P | volatility+trend+event | HIGH/TREND/NORMAL | 204 | 68 | -24.63 [-38.80, -10.93] | ok |
| CONSERVATIVE | P | volatility+trend+event | HIGH/CHOP/MACRO | 45 | 15 | -8.27 [-39.03, +27.54] | LOW_SUPPORT |
| CONSERVATIVE | P | volatility+trend+event | NORMAL/TREND/MACRO | 23 | 8 | -21.88 [-55.36, +7.35] | LOW_SUPPORT |
| CONSERVATIVE | P | volatility+trend+event | LOW/CHOP/NORMAL | 24 | 8 | -6.15 [-27.15, +14.14] | LOW_SUPPORT |
| CONSERVATIVE | P | volatility+trend+event | NORMAL/CHOP/MACRO | 33 | 11 | +22.75 [-1.10, +45.30] | LOW_SUPPORT |
| MODERATE | C | volatility+trend+event | LOW/TREND/NORMAL | 105 | 35 | +5.04 [-3.71, +14.00] | ok |
| MODERATE | C | volatility+trend+event | NORMAL/TREND/NORMAL | 168 | 56 | -3.48 [-11.46, +4.55] | ok |
| MODERATE | C | volatility+trend+event | LOW/TREND/MACRO | 15 | 5 | -7.60 [-34.87, +13.20] | LOW_SUPPORT |
| MODERATE | C | volatility+trend+event | NORMAL/CHOP/NORMAL | 261 | 87 | -11.90 [-19.52, -4.65] | ok |
| MODERATE | C | volatility+trend+event | HIGH/CHOP/NORMAL | 399 | 133 | -7.78 [-16.43, +1.43] | ok |
| MODERATE | C | volatility+trend+event | HIGH/TREND/MACRO | 42 | 14 | -17.64 [-46.33, +10.86] | LOW_SUPPORT |
| MODERATE | C | volatility+trend+event | HIGH/TREND/NORMAL | 204 | 68 | +12.21 [-1.54, +28.14] | ok |
| MODERATE | C | volatility+trend+event | HIGH/CHOP/MACRO | 45 | 15 | -14.69 [-46.80, +14.09] | LOW_SUPPORT |
| MODERATE | C | volatility+trend+event | NORMAL/TREND/MACRO | 23 | 8 | -21.57 [-51.17, -1.82] | LOW_SUPPORT |
| MODERATE | C | volatility+trend+event | LOW/CHOP/NORMAL | 24 | 8 | -7.40 [-25.74, +11.44] | LOW_SUPPORT |
| MODERATE | C | volatility+trend+event | NORMAL/CHOP/MACRO | 33 | 11 | -15.01 [-33.25, +4.48] | LOW_SUPPORT |
| MODERATE | P | volatility+trend+event | LOW/TREND/NORMAL | 105 | 35 | -14.95 [-22.70, -7.72] | ok |
| MODERATE | P | volatility+trend+event | NORMAL/TREND/NORMAL | 168 | 56 | -2.83 [-11.88, +6.58] | ok |
| MODERATE | P | volatility+trend+event | LOW/TREND/MACRO | 15 | 5 | +1.13 [-26.47, +42.13] | LOW_SUPPORT |
| MODERATE | P | volatility+trend+event | NORMAL/CHOP/NORMAL | 261 | 87 | +7.58 [-1.67, +17.06] | ok |
| MODERATE | P | volatility+trend+event | HIGH/CHOP/NORMAL | 399 | 133 | -5.61 [-14.83, +4.12] | ok |
| MODERATE | P | volatility+trend+event | HIGH/TREND/MACRO | 42 | 14 | +8.29 [-19.21, +35.13] | LOW_SUPPORT |
| MODERATE | P | volatility+trend+event | HIGH/TREND/NORMAL | 204 | 68 | -23.59 [-37.12, -10.28] | ok |
| MODERATE | P | volatility+trend+event | HIGH/CHOP/MACRO | 45 | 15 | -7.53 [-38.34, +28.34] | LOW_SUPPORT |
| MODERATE | P | volatility+trend+event | NORMAL/TREND/MACRO | 23 | 8 | -21.70 [-55.31, +7.64] | LOW_SUPPORT |
| MODERATE | P | volatility+trend+event | LOW/CHOP/NORMAL | 24 | 8 | -6.15 [-27.15, +14.14] | LOW_SUPPORT |
| MODERATE | P | volatility+trend+event | NORMAL/CHOP/MACRO | 33 | 11 | +22.99 [-1.28, +45.90] | LOW_SUPPORT |

## Calibrated probabilities by single-axis buckets (test blocks)

| model | target | axis | bucket | n | sessions | mean predicted | observed | obs - pred | Brier [CI] | ECE | support |
|---|---|---|---|---|---|---|---|---|---|---|---|
| logistic_m1 | A_up | volatility | LOW | 2,817 | 48 | 0.425 | 0.459 | +0.033 | 0.2497 [+0.2401, +0.2591] | 0.0450 | ok |
| logistic_m1 | A_up | volatility | NORMAL | 10,036 | 162 | 0.442 | 0.420 | -0.022 | 0.2457 [+0.2408, +0.2508] | 0.0404 | ok |
| logistic_m1 | A_up | volatility | HIGH | 14,519 | 230 | 0.486 | 0.466 | -0.019 | 0.2544 [+0.2486, +0.2610] | 0.0527 | ok |
| logistic_m1 | A_up | trend | TREND | 11,578 | 186 | 0.476 | 0.460 | -0.016 | 0.2528 [+0.2463, +0.2610] | 0.0505 | ok |
| logistic_m1 | A_up | trend | CHOP | 15,794 | 254 | 0.455 | 0.441 | -0.014 | 0.2492 [+0.2453, +0.2530] | 0.0418 | ok |
| logistic_m1 | A_up | event | NORMAL | 24,070 | 387 | 0.462 | 0.447 | -0.014 | 0.2510 [+0.2470, +0.2557] | 0.0477 | ok |
| logistic_m1 | A_up | event | MACRO | 3,302 | 53 | 0.475 | 0.459 | -0.017 | 0.2489 [+0.2422, +0.2554] | 0.0622 | ok |
| logistic_m1 | A_dn | volatility | LOW | 2,817 | 48 | 0.374 | 0.331 | -0.043 | 0.2225 [+0.2055, +0.2387] | 0.0612 | ok |
| logistic_m1 | A_dn | volatility | NORMAL | 10,036 | 162 | 0.386 | 0.378 | -0.009 | 0.2322 [+0.2241, +0.2407] | 0.0236 | ok |
| logistic_m1 | A_dn | volatility | HIGH | 14,519 | 230 | 0.400 | 0.411 | +0.011 | 0.2433 [+0.2374, +0.2491] | 0.0453 | ok |
| logistic_m1 | A_dn | trend | TREND | 11,578 | 186 | 0.391 | 0.366 | -0.025 | 0.2317 [+0.2240, +0.2388] | 0.0252 | ok |
| logistic_m1 | A_dn | trend | CHOP | 15,794 | 254 | 0.394 | 0.409 | +0.015 | 0.2410 [+0.2352, +0.2471] | 0.0304 | ok |
| logistic_m1 | A_dn | event | NORMAL | 24,070 | 387 | 0.393 | 0.393 | +0.000 | 0.2375 [+0.2324, +0.2425] | 0.0174 | ok |
| logistic_m1 | A_dn | event | MACRO | 3,302 | 53 | 0.392 | 0.374 | -0.017 | 0.2342 [+0.2204, +0.2490] | 0.0604 | ok |
| logistic_m1 | B_up[m=0.0025] | volatility | LOW | 2,817 | 48 | 0.246 | 0.284 | +0.037 | 0.1989 [+0.1674, +0.2322] | 0.0742 | ok |
| logistic_m1 | B_up[m=0.0025] | volatility | NORMAL | 10,036 | 162 | 0.300 | 0.252 | -0.048 | 0.1733 [+0.1611, +0.1854] | 0.0480 | ok |
| logistic_m1 | B_up[m=0.0025] | volatility | HIGH | 14,519 | 230 | 0.516 | 0.470 | -0.046 | 0.2220 [+0.2129, +0.2313] | 0.0599 | ok |
| logistic_m1 | B_up[m=0.0025] | trend | TREND | 11,578 | 186 | 0.390 | 0.352 | -0.037 | 0.1950 [+0.1827, +0.2082] | 0.0611 | ok |
| logistic_m1 | B_up[m=0.0025] | trend | CHOP | 15,794 | 254 | 0.423 | 0.384 | -0.039 | 0.2067 [+0.1969, +0.2160] | 0.0422 | ok |
| logistic_m1 | B_up[m=0.0025] | event | NORMAL | 24,070 | 387 | 0.397 | 0.361 | -0.036 | 0.1998 [+0.1915, +0.2079] | 0.0420 | ok |
| logistic_m1 | B_up[m=0.0025] | event | MACRO | 3,302 | 53 | 0.494 | 0.438 | -0.056 | 0.2160 [+0.1992, +0.2326] | 0.0683 | ok |
| logistic_m1 | B_dn[m=0.0025] | volatility | LOW | 2,817 | 48 | 0.328 | 0.277 | -0.051 | 0.1872 [+0.1625, +0.2115] | 0.0599 | ok |
| logistic_m1 | B_dn[m=0.0025] | volatility | NORMAL | 10,036 | 162 | 0.370 | 0.339 | -0.031 | 0.2026 [+0.1911, +0.2138] | 0.0486 | ok |
| logistic_m1 | B_dn[m=0.0025] | volatility | HIGH | 14,519 | 230 | 0.481 | 0.489 | +0.008 | 0.2307 [+0.2223, +0.2384] | 0.0315 | ok |
| logistic_m1 | B_dn[m=0.0025] | trend | TREND | 11,578 | 186 | 0.416 | 0.371 | -0.045 | 0.2096 [+0.1988, +0.2207] | 0.0541 | ok |
| logistic_m1 | B_dn[m=0.0025] | trend | CHOP | 15,794 | 254 | 0.431 | 0.442 | +0.011 | 0.2206 [+0.2118, +0.2292] | 0.0504 | ok |
| logistic_m1 | B_dn[m=0.0025] | event | NORMAL | 24,070 | 387 | 0.419 | 0.406 | -0.013 | 0.2145 [+0.2073, +0.2215] | 0.0369 | ok |
| logistic_m1 | B_dn[m=0.0025] | event | MACRO | 3,302 | 53 | 0.468 | 0.458 | -0.010 | 0.2263 [+0.2047, +0.2487] | 0.0601 | ok |
| logistic_m1 | B_up[m=0.005] | volatility | LOW | 2,817 | 48 | 0.061 | 0.058 | -0.002 | 0.0552 [+0.0324, +0.0829] | 0.0236 | ok |
| logistic_m1 | B_up[m=0.005] | volatility | NORMAL | 10,036 | 162 | 0.075 | 0.046 | -0.029 | 0.0424 [+0.0329, +0.0519] | 0.0302 | ok |
| logistic_m1 | B_up[m=0.005] | volatility | HIGH | 14,519 | 230 | 0.243 | 0.209 | -0.034 | 0.1452 [+0.1311, +0.1598] | 0.0475 | ok |
| logistic_m1 | B_up[m=0.005] | trend | TREND | 11,578 | 186 | 0.159 | 0.123 | -0.036 | 0.0862 [+0.0716, +0.1020] | 0.0386 | ok |
| logistic_m1 | B_up[m=0.005] | trend | CHOP | 15,794 | 254 | 0.165 | 0.142 | -0.023 | 0.1071 [+0.0952, +0.1196] | 0.0320 | ok |
| logistic_m1 | B_up[m=0.005] | event | NORMAL | 24,070 | 387 | 0.151 | 0.127 | -0.024 | 0.0942 [+0.0843, +0.1051] | 0.0296 | ok |
| logistic_m1 | B_up[m=0.005] | event | MACRO | 3,302 | 53 | 0.249 | 0.185 | -0.064 | 0.1273 [+0.1012, +0.1565] | 0.0640 | ok |
| logistic_m1 | B_dn[m=0.005] | volatility | LOW | 2,817 | 48 | 0.103 | 0.089 | -0.014 | 0.0783 [+0.0486, +0.1100] | 0.0267 | ok |
| logistic_m1 | B_dn[m=0.005] | volatility | NORMAL | 10,036 | 162 | 0.122 | 0.120 | -0.003 | 0.0993 [+0.0826, +0.1174] | 0.0179 | ok |
| logistic_m1 | B_dn[m=0.005] | volatility | HIGH | 14,519 | 230 | 0.219 | 0.242 | +0.023 | 0.1764 [+0.1606, +0.1931] | 0.0585 | ok |
| logistic_m1 | B_dn[m=0.005] | trend | TREND | 11,578 | 186 | 0.167 | 0.160 | -0.006 | 0.1229 [+0.1058, +0.1416] | 0.0242 | ok |
| logistic_m1 | B_dn[m=0.005] | trend | CHOP | 15,794 | 254 | 0.175 | 0.197 | +0.022 | 0.1492 [+0.1338, +0.1641] | 0.0389 | ok |
| logistic_m1 | B_dn[m=0.005] | event | NORMAL | 24,070 | 387 | 0.163 | 0.177 | +0.014 | 0.1341 [+0.1216, +0.1479] | 0.0231 | ok |
| logistic_m1 | B_dn[m=0.005] | event | MACRO | 3,302 | 53 | 0.235 | 0.217 | -0.017 | 0.1671 [+0.1372, +0.2002] | 0.0742 | ok |
| logistic_m1 | C_call | volatility | LOW | 2,986 | 48 | 0.230 | 0.263 | +0.033 | 0.1958 [+0.1680, +0.2250] | 0.0602 | ok |
| logistic_m1 | C_call | volatility | NORMAL | 10,248 | 162 | 0.240 | 0.214 | -0.026 | 0.1682 [+0.1551, +0.1820] | 0.0373 | ok |
| logistic_m1 | C_call | volatility | HIGH | 14,557 | 230 | 0.268 | 0.256 | -0.012 | 0.1909 [+0.1817, +0.2006] | 0.0276 | ok |
| logistic_m1 | C_call | trend | TREND | 11,764 | 186 | 0.251 | 0.257 | +0.005 | 0.1906 [+0.1780, +0.2041] | 0.0394 | ok |
| logistic_m1 | C_call | trend | CHOP | 16,027 | 254 | 0.255 | 0.229 | -0.026 | 0.1775 [+0.1680, +0.1875] | 0.0392 | ok |
| logistic_m1 | C_call | event | NORMAL | 24,461 | 387 | 0.250 | 0.238 | -0.012 | 0.1816 [+0.1734, +0.1901] | 0.0312 | ok |
| logistic_m1 | C_call | event | MACRO | 3,330 | 53 | 0.280 | 0.265 | -0.016 | 0.1941 [+0.1751, +0.2131] | 0.0505 | ok |
| logistic_m1 | C_put | volatility | LOW | 2,981 | 48 | 0.274 | 0.258 | -0.016 | 0.1900 [+0.1666, +0.2129] | 0.0405 | ok |
| logistic_m1 | C_put | volatility | NORMAL | 10,234 | 162 | 0.287 | 0.292 | +0.005 | 0.2019 [+0.1883, +0.2153] | 0.0255 | ok |
| logistic_m1 | C_put | volatility | HIGH | 14,569 | 230 | 0.282 | 0.287 | +0.006 | 0.2054 [+0.1938, +0.2165] | 0.0335 | ok |
| logistic_m1 | C_put | trend | TREND | 11,750 | 186 | 0.282 | 0.269 | -0.013 | 0.1967 [+0.1826, +0.2094] | 0.0308 | ok |
| logistic_m1 | C_put | trend | CHOP | 16,034 | 254 | 0.284 | 0.298 | +0.014 | 0.2067 [+0.1965, +0.2170] | 0.0175 | ok |
| logistic_m1 | C_put | event | NORMAL | 24,458 | 387 | 0.284 | 0.287 | +0.004 | 0.2028 [+0.1942, +0.2117] | 0.0164 | ok |
| logistic_m1 | C_put | event | MACRO | 3,326 | 53 | 0.278 | 0.276 | -0.003 | 0.1997 [+0.1785, +0.2226] | 0.0456 | ok |
| logistic_m1 | D_call | volatility | LOW | 1,584 | 47 | 0.706 | 0.666 | -0.040 | 0.2253 [+0.1954, +0.2568] | 0.0770 | ok |
| logistic_m1 | D_call | volatility | NORMAL | 5,825 | 160 | 0.691 | 0.729 | +0.038 | 0.1999 [+0.1870, +0.2126] | 0.0480 | ok |
| logistic_m1 | D_call | volatility | HIGH | 11,796 | 230 | 0.631 | 0.648 | +0.017 | 0.2318 [+0.2258, +0.2382] | 0.0416 | ok |
| logistic_m1 | D_call | trend | TREND | 7,631 | 186 | 0.647 | 0.669 | +0.022 | 0.2228 [+0.2121, +0.2335] | 0.0459 | ok |
| logistic_m1 | D_call | trend | CHOP | 11,574 | 251 | 0.661 | 0.677 | +0.016 | 0.2208 [+0.2136, +0.2281] | 0.0411 | ok |
| logistic_m1 | D_call | event | NORMAL | 16,698 | 384 | 0.659 | 0.677 | +0.018 | 0.2208 [+0.2140, +0.2278] | 0.0408 | ok |
| logistic_m1 | D_call | event | MACRO | 2,507 | 53 | 0.633 | 0.656 | +0.023 | 0.2270 [+0.2124, +0.2411] | 0.0573 | ok |
| logistic_m1 | D_put | volatility | LOW | 1,627 | 48 | 0.625 | 0.675 | +0.051 | 0.2210 [+0.2032, +0.2380] | 0.0534 | ok |
| logistic_m1 | D_put | volatility | NORMAL | 5,974 | 161 | 0.617 | 0.590 | -0.027 | 0.2437 [+0.2338, +0.2531] | 0.0493 | ok |
| logistic_m1 | D_put | volatility | HIGH | 12,001 | 230 | 0.617 | 0.621 | +0.004 | 0.2360 [+0.2308, +0.2412] | 0.0281 | ok |
| logistic_m1 | D_put | trend | TREND | 7,907 | 186 | 0.618 | 0.639 | +0.021 | 0.2315 [+0.2236, +0.2392] | 0.0293 | ok |
| logistic_m1 | D_put | trend | CHOP | 11,695 | 253 | 0.618 | 0.600 | -0.017 | 0.2408 [+0.2350, +0.2461] | 0.0295 | ok |
| logistic_m1 | D_put | event | NORMAL | 17,063 | 386 | 0.616 | 0.616 | -0.000 | 0.2366 [+0.2315, +0.2415] | 0.0205 | ok |
| logistic_m1 | D_put | event | MACRO | 2,539 | 53 | 0.631 | 0.618 | -0.013 | 0.2402 [+0.2292, +0.2521] | 0.0687 | ok |
| gbm_m2 | A_up | volatility | LOW | 2,817 | 48 | 0.459 | 0.459 | +0.000 | 0.2433 [+0.2352, +0.2520] | 0.0322 | ok |
| gbm_m2 | A_up | volatility | NORMAL | 10,036 | 162 | 0.439 | 0.420 | -0.019 | 0.2500 [+0.2423, +0.2584] | 0.0573 | ok |
| gbm_m2 | A_up | volatility | HIGH | 14,519 | 230 | 0.487 | 0.466 | -0.020 | 0.2524 [+0.2493, +0.2558] | 0.0475 | ok |
| gbm_m2 | A_up | trend | TREND | 11,578 | 186 | 0.460 | 0.460 | +0.000 | 0.2515 [+0.2452, +0.2587] | 0.0530 | ok |
| gbm_m2 | A_up | trend | CHOP | 15,794 | 254 | 0.471 | 0.441 | -0.031 | 0.2499 [+0.2463, +0.2535] | 0.0451 | ok |
| gbm_m2 | A_up | event | NORMAL | 24,070 | 387 | 0.466 | 0.447 | -0.018 | 0.2506 [+0.2468, +0.2543] | 0.0389 | ok |
| gbm_m2 | A_up | event | MACRO | 3,302 | 53 | 0.470 | 0.459 | -0.011 | 0.2505 [+0.2426, +0.2594] | 0.0382 | ok |
| gbm_m2 | A_dn | volatility | LOW | 2,817 | 48 | 0.357 | 0.331 | -0.026 | 0.2221 [+0.2054, +0.2393] | 0.0440 | ok |
| gbm_m2 | A_dn | volatility | NORMAL | 10,036 | 162 | 0.395 | 0.378 | -0.017 | 0.2345 [+0.2266, +0.2425] | 0.0332 | ok |
| gbm_m2 | A_dn | volatility | HIGH | 14,519 | 230 | 0.403 | 0.411 | +0.008 | 0.2438 [+0.2373, +0.2502] | 0.0385 | ok |
| gbm_m2 | A_dn | trend | TREND | 11,578 | 186 | 0.393 | 0.366 | -0.028 | 0.2316 [+0.2242, +0.2385] | 0.0366 | ok |
| gbm_m2 | A_dn | trend | CHOP | 15,794 | 254 | 0.396 | 0.409 | +0.013 | 0.2429 [+0.2367, +0.2490] | 0.0354 | ok |
| gbm_m2 | A_dn | event | NORMAL | 24,070 | 387 | 0.394 | 0.393 | -0.001 | 0.2391 [+0.2341, +0.2442] | 0.0311 | ok |
| gbm_m2 | A_dn | event | MACRO | 3,302 | 53 | 0.404 | 0.374 | -0.030 | 0.2313 [+0.2166, +0.2465] | 0.0707 | ok |
| gbm_m2 | B_up[m=0.0025] | volatility | LOW | 2,817 | 48 | 0.221 | 0.284 | +0.063 | 0.1861 [+0.1549, +0.2201] | 0.0631 | ok |
| gbm_m2 | B_up[m=0.0025] | volatility | NORMAL | 10,036 | 162 | 0.273 | 0.252 | -0.021 | 0.1683 [+0.1552, +0.1812] | 0.0256 | ok |
| gbm_m2 | B_up[m=0.0025] | volatility | HIGH | 14,519 | 230 | 0.478 | 0.470 | -0.009 | 0.2173 [+0.2109, +0.2238] | 0.0225 | ok |
| gbm_m2 | B_up[m=0.0025] | trend | TREND | 11,578 | 186 | 0.344 | 0.352 | +0.008 | 0.1866 [+0.1749, +0.1984] | 0.0268 | ok |
| gbm_m2 | B_up[m=0.0025] | trend | CHOP | 15,794 | 254 | 0.400 | 0.384 | -0.016 | 0.2031 [+0.1940, +0.2112] | 0.0200 | ok |
| gbm_m2 | B_up[m=0.0025] | event | NORMAL | 24,070 | 387 | 0.370 | 0.361 | -0.008 | 0.1949 [+0.1874, +0.2026] | 0.0154 | ok |
| gbm_m2 | B_up[m=0.0025] | event | MACRO | 3,302 | 53 | 0.428 | 0.438 | +0.010 | 0.2048 [+0.1898, +0.2205] | 0.0471 | ok |
| gbm_m2 | B_dn[m=0.0025] | volatility | LOW | 2,817 | 48 | 0.308 | 0.277 | -0.031 | 0.1858 [+0.1604, +0.2107] | 0.0628 | ok |
| gbm_m2 | B_dn[m=0.0025] | volatility | NORMAL | 10,036 | 162 | 0.377 | 0.339 | -0.038 | 0.2051 [+0.1925, +0.2174] | 0.0528 | ok |
| gbm_m2 | B_dn[m=0.0025] | volatility | HIGH | 14,519 | 230 | 0.465 | 0.489 | +0.024 | 0.2385 [+0.2312, +0.2457] | 0.0435 | ok |
| gbm_m2 | B_dn[m=0.0025] | trend | TREND | 11,578 | 186 | 0.397 | 0.371 | -0.026 | 0.2138 [+0.2033, +0.2247] | 0.0307 | ok |
| gbm_m2 | B_dn[m=0.0025] | trend | CHOP | 15,794 | 254 | 0.431 | 0.442 | +0.011 | 0.2261 [+0.2179, +0.2341] | 0.0401 | ok |
| gbm_m2 | B_dn[m=0.0025] | event | NORMAL | 24,070 | 387 | 0.410 | 0.406 | -0.005 | 0.2197 [+0.2124, +0.2266] | 0.0346 | ok |
| gbm_m2 | B_dn[m=0.0025] | event | MACRO | 3,302 | 53 | 0.460 | 0.458 | -0.002 | 0.2293 [+0.2094, +0.2498] | 0.0616 | ok |
| gbm_m2 | B_up[m=0.005] | volatility | LOW | 2,817 | 48 | 0.042 | 0.058 | +0.017 | 0.0534 [+0.0304, +0.0817] | 0.0214 | ok |
| gbm_m2 | B_up[m=0.005] | volatility | NORMAL | 10,036 | 162 | 0.066 | 0.046 | -0.020 | 0.0414 [+0.0320, +0.0507] | 0.0202 | ok |
| gbm_m2 | B_up[m=0.005] | volatility | HIGH | 14,519 | 230 | 0.206 | 0.209 | +0.003 | 0.1412 [+0.1284, +0.1542] | 0.0131 | ok |
| gbm_m2 | B_up[m=0.005] | trend | TREND | 11,578 | 186 | 0.120 | 0.123 | +0.003 | 0.0848 [+0.0702, +0.0996] | 0.0234 | ok |
| gbm_m2 | B_up[m=0.005] | trend | CHOP | 15,794 | 254 | 0.151 | 0.142 | -0.009 | 0.1034 [+0.0926, +0.1146] | 0.0142 | ok |
| gbm_m2 | B_up[m=0.005] | event | NORMAL | 24,070 | 387 | 0.131 | 0.127 | -0.004 | 0.0927 [+0.0831, +0.1029] | 0.0075 | ok |
| gbm_m2 | B_up[m=0.005] | event | MACRO | 3,302 | 53 | 0.190 | 0.185 | -0.005 | 0.1165 [+0.0928, +0.1421] | 0.0300 | ok |
| gbm_m2 | B_dn[m=0.005] | volatility | LOW | 2,817 | 48 | 0.098 | 0.089 | -0.008 | 0.0792 [+0.0491, +0.1116] | 0.0340 | ok |
| gbm_m2 | B_dn[m=0.005] | volatility | NORMAL | 10,036 | 162 | 0.139 | 0.120 | -0.019 | 0.0995 [+0.0835, +0.1167] | 0.0194 | ok |
| gbm_m2 | B_dn[m=0.005] | volatility | HIGH | 14,519 | 230 | 0.212 | 0.242 | +0.031 | 0.1742 [+0.1590, +0.1911] | 0.0445 | ok |
| gbm_m2 | B_dn[m=0.005] | trend | TREND | 11,578 | 186 | 0.158 | 0.160 | +0.002 | 0.1234 [+0.1062, +0.1425] | 0.0166 | ok |
| gbm_m2 | B_dn[m=0.005] | trend | CHOP | 15,794 | 254 | 0.184 | 0.197 | +0.013 | 0.1470 [+0.1324, +0.1617] | 0.0197 | ok |
| gbm_m2 | B_dn[m=0.005] | event | NORMAL | 24,070 | 387 | 0.167 | 0.177 | +0.010 | 0.1332 [+0.1214, +0.1466] | 0.0138 | ok |
| gbm_m2 | B_dn[m=0.005] | event | MACRO | 3,302 | 53 | 0.221 | 0.217 | -0.003 | 0.1648 [+0.1345, +0.1964] | 0.0557 | ok |
| gbm_m2 | C_call | volatility | LOW | 2,986 | 48 | 0.227 | 0.263 | +0.036 | 0.1998 [+0.1702, +0.2325] | 0.0519 | ok |
| gbm_m2 | C_call | volatility | NORMAL | 10,248 | 162 | 0.233 | 0.214 | -0.020 | 0.1685 [+0.1553, +0.1827] | 0.0319 | ok |
| gbm_m2 | C_call | volatility | HIGH | 14,557 | 230 | 0.263 | 0.256 | -0.007 | 0.1886 [+0.1792, +0.1984] | 0.0177 | ok |
| gbm_m2 | C_call | trend | TREND | 11,764 | 186 | 0.237 | 0.257 | +0.020 | 0.1913 [+0.1778, +0.2054] | 0.0322 | ok |
| gbm_m2 | C_call | trend | CHOP | 16,027 | 254 | 0.256 | 0.229 | -0.027 | 0.1759 [+0.1666, +0.1854] | 0.0315 | ok |
| gbm_m2 | C_call | event | NORMAL | 24,461 | 387 | 0.245 | 0.238 | -0.007 | 0.1801 [+0.1721, +0.1885] | 0.0235 | ok |
| gbm_m2 | C_call | event | MACRO | 3,330 | 53 | 0.270 | 0.265 | -0.006 | 0.1996 [+0.1774, +0.2213] | 0.0511 | ok |
| gbm_m2 | C_put | volatility | LOW | 2,981 | 48 | 0.266 | 0.258 | -0.008 | 0.1875 [+0.1649, +0.2103] | 0.0472 | ok |
| gbm_m2 | C_put | volatility | NORMAL | 10,234 | 162 | 0.287 | 0.292 | +0.005 | 0.2057 [+0.1921, +0.2194] | 0.0192 | ok |
| gbm_m2 | C_put | volatility | HIGH | 14,569 | 230 | 0.273 | 0.287 | +0.015 | 0.2042 [+0.1923, +0.2152] | 0.0220 | ok |
| gbm_m2 | C_put | trend | TREND | 11,750 | 186 | 0.278 | 0.269 | -0.009 | 0.1957 [+0.1822, +0.2082] | 0.0186 | ok |
| gbm_m2 | C_put | trend | CHOP | 16,034 | 254 | 0.277 | 0.298 | +0.022 | 0.2083 [+0.1981, +0.2186] | 0.0220 | ok |
| gbm_m2 | C_put | event | NORMAL | 24,458 | 387 | 0.277 | 0.287 | +0.010 | 0.2038 [+0.1951, +0.2126] | 0.0158 | ok |
| gbm_m2 | C_put | event | MACRO | 3,326 | 53 | 0.279 | 0.276 | -0.004 | 0.1968 [+0.1758, +0.2184] | 0.0428 | ok |
| gbm_m2 | D_call | volatility | LOW | 1,584 | 47 | 0.727 | 0.666 | -0.061 | 0.2196 [+0.1849, +0.2573] | 0.0641 | ok |
| gbm_m2 | D_call | volatility | NORMAL | 5,825 | 160 | 0.700 | 0.729 | +0.030 | 0.1983 [+0.1852, +0.2118] | 0.0429 | ok |
| gbm_m2 | D_call | volatility | HIGH | 11,796 | 230 | 0.638 | 0.648 | +0.010 | 0.2298 [+0.2239, +0.2353] | 0.0443 | ok |
| gbm_m2 | D_call | trend | TREND | 7,631 | 186 | 0.671 | 0.669 | -0.002 | 0.2198 [+0.2075, +0.2319] | 0.0421 | ok |
| gbm_m2 | D_call | trend | CHOP | 11,574 | 251 | 0.659 | 0.677 | +0.018 | 0.2192 [+0.2123, +0.2263] | 0.0378 | ok |
| gbm_m2 | D_call | event | NORMAL | 16,698 | 384 | 0.664 | 0.677 | +0.013 | 0.2190 [+0.2122, +0.2261] | 0.0421 | ok |
| gbm_m2 | D_call | event | MACRO | 2,507 | 53 | 0.665 | 0.656 | -0.009 | 0.2219 [+0.2063, +0.2366] | 0.0280 | ok |
| gbm_m2 | D_put | volatility | LOW | 1,627 | 48 | 0.616 | 0.675 | +0.060 | 0.2226 [+0.2058, +0.2389] | 0.0783 | ok |
| gbm_m2 | D_put | volatility | NORMAL | 5,974 | 161 | 0.614 | 0.590 | -0.024 | 0.2443 [+0.2347, +0.2532] | 0.0498 | ok |
| gbm_m2 | D_put | volatility | HIGH | 12,001 | 230 | 0.618 | 0.621 | +0.003 | 0.2360 [+0.2312, +0.2410] | 0.0285 | ok |
| gbm_m2 | D_put | trend | TREND | 7,907 | 186 | 0.613 | 0.639 | +0.026 | 0.2319 [+0.2249, +0.2390] | 0.0412 | ok |
| gbm_m2 | D_put | trend | CHOP | 11,695 | 253 | 0.619 | 0.600 | -0.018 | 0.2411 [+0.2356, +0.2464] | 0.0317 | ok |
| gbm_m2 | D_put | event | NORMAL | 17,063 | 386 | 0.617 | 0.616 | -0.001 | 0.2378 [+0.2328, +0.2424] | 0.0234 | ok |
| gbm_m2 | D_put | event | MACRO | 2,539 | 53 | 0.614 | 0.618 | +0.005 | 0.2352 [+0.2256, +0.2451] | 0.0493 | ok |

## Calibrated probabilities by full cells, C targets (test blocks)

| model | target | axis | bucket | n | sessions | mean predicted | observed | obs - pred | Brier [CI] | ECE | support |
|---|---|---|---|---|---|---|---|---|---|---|---|
| logistic_m1 | C_call | volatility+trend+event | LOW/TREND/NORMAL | 2,192 | 35 | 0.221 | 0.279 | +0.058 | 0.2044 [+0.1701, +0.2407] | 0.0725 | ok |
| logistic_m1 | C_call | volatility+trend+event | NORMAL/TREND/NORMAL | 3,570 | 56 | 0.238 | 0.229 | -0.009 | 0.1783 [+0.1550, +0.2025] | 0.0484 | ok |
| logistic_m1 | C_call | volatility+trend+event | LOW/TREND/MACRO | 319 | 5 | 0.258 | 0.285 | +0.027 | 0.2057 [+0.1528, +0.2622] | 0.0953 | LOW_SUPPORT |
| logistic_m1 | C_call | volatility+trend+event | NORMAL/CHOP/NORMAL | 5,514 | 87 | 0.236 | 0.200 | -0.036 | 0.1613 [+0.1449, +0.1784] | 0.0415 | ok |
| logistic_m1 | C_call | volatility+trend+event | HIGH/CHOP/NORMAL | 8,386 | 133 | 0.262 | 0.245 | -0.016 | 0.1861 [+0.1735, +0.1993] | 0.0408 | ok |
| logistic_m1 | C_call | volatility+trend+event | HIGH/TREND/MACRO | 892 | 14 | 0.288 | 0.276 | -0.012 | 0.1997 [+0.1743, +0.2260] | 0.0565 | LOW_SUPPORT |
| logistic_m1 | C_call | volatility+trend+event | HIGH/TREND/NORMAL | 4,324 | 68 | 0.269 | 0.264 | -0.005 | 0.1932 [+0.1743, +0.2117] | 0.0523 | ok |
| logistic_m1 | C_call | volatility+trend+event | HIGH/CHOP/MACRO | 955 | 15 | 0.303 | 0.292 | -0.011 | 0.2144 [+0.1831, +0.2494] | 0.1001 | LOW_SUPPORT |
| logistic_m1 | C_call | volatility+trend+event | NORMAL/TREND/MACRO | 467 | 8 | 0.260 | 0.246 | -0.014 | 0.1694 [+0.1012, +0.2345] | 0.1018 | LOW_SUPPORT |
| logistic_m1 | C_call | volatility+trend+event | LOW/CHOP/NORMAL | 475 | 8 | 0.251 | 0.175 | -0.077 | 0.1493 [+0.1028, +0.2074] | 0.0877 | LOW_SUPPORT |
| logistic_m1 | C_call | volatility+trend+event | NORMAL/CHOP/MACRO | 697 | 11 | 0.263 | 0.217 | -0.046 | 0.1706 [+0.1306, +0.2111] | 0.0684 | LOW_SUPPORT |
| logistic_m1 | C_put | volatility+trend+event | LOW/TREND/NORMAL | 2,188 | 35 | 0.273 | 0.260 | -0.014 | 0.1908 [+0.1646, +0.2167] | 0.0362 | ok |
| logistic_m1 | C_put | volatility+trend+event | NORMAL/TREND/NORMAL | 3,563 | 56 | 0.284 | 0.283 | -0.001 | 0.1998 [+0.1776, +0.2229] | 0.0295 | ok |
| logistic_m1 | C_put | volatility+trend+event | LOW/TREND/MACRO | 318 | 5 | 0.307 | 0.233 | -0.074 | 0.1773 [+0.1163, +0.2380] | 0.1423 | LOW_SUPPORT |
| logistic_m1 | C_put | volatility+trend+event | NORMAL/CHOP/NORMAL | 5,509 | 87 | 0.294 | 0.313 | +0.019 | 0.2102 [+0.1919, +0.2288] | 0.0443 | ok |
| logistic_m1 | C_put | volatility+trend+event | HIGH/CHOP/NORMAL | 8,398 | 133 | 0.282 | 0.296 | +0.015 | 0.2074 [+0.1926, +0.2216] | 0.0291 | ok |
| logistic_m1 | C_put | volatility+trend+event | HIGH/TREND/MACRO | 892 | 14 | 0.284 | 0.327 | +0.043 | 0.2297 [+0.1823, +0.2773] | 0.1022 | LOW_SUPPORT |
| logistic_m1 | C_put | volatility+trend+event | HIGH/TREND/NORMAL | 4,325 | 68 | 0.283 | 0.257 | -0.026 | 0.1941 [+0.1721, +0.2182] | 0.0476 | ok |
| logistic_m1 | C_put | volatility+trend+event | HIGH/CHOP/MACRO | 954 | 15 | 0.279 | 0.309 | +0.030 | 0.2163 [+0.1836, +0.2480] | 0.0787 | LOW_SUPPORT |
| logistic_m1 | C_put | volatility+trend+event | NORMAL/TREND/MACRO | 464 | 8 | 0.268 | 0.231 | -0.037 | 0.1751 [+0.1204, +0.2262] | 0.0878 | LOW_SUPPORT |
| logistic_m1 | C_put | volatility+trend+event | LOW/CHOP/NORMAL | 475 | 8 | 0.255 | 0.269 | +0.014 | 0.1947 [+0.1277, +0.2550] | 0.0794 | LOW_SUPPORT |
| logistic_m1 | C_put | volatility+trend+event | NORMAL/CHOP/MACRO | 698 | 11 | 0.264 | 0.213 | -0.051 | 0.1653 [+0.1213, +0.2118] | 0.0748 | LOW_SUPPORT |
| gbm_m2 | C_call | volatility+trend+event | LOW/TREND/NORMAL | 2,192 | 35 | 0.216 | 0.279 | +0.064 | 0.2053 [+0.1685, +0.2433] | 0.0635 | ok |
| gbm_m2 | C_call | volatility+trend+event | NORMAL/TREND/NORMAL | 3,570 | 56 | 0.212 | 0.229 | +0.017 | 0.1754 [+0.1506, +0.2012] | 0.0362 | ok |
| gbm_m2 | C_call | volatility+trend+event | LOW/TREND/MACRO | 319 | 5 | 0.300 | 0.285 | -0.015 | 0.2405 [+0.1448, +0.3398] | 0.1073 | LOW_SUPPORT |
| gbm_m2 | C_call | volatility+trend+event | NORMAL/CHOP/NORMAL | 5,514 | 87 | 0.242 | 0.200 | -0.042 | 0.1621 [+0.1458, +0.1793] | 0.0507 | ok |
| gbm_m2 | C_call | volatility+trend+event | HIGH/CHOP/NORMAL | 8,386 | 133 | 0.262 | 0.245 | -0.017 | 0.1826 [+0.1707, +0.1953] | 0.0286 | ok |
| gbm_m2 | C_call | volatility+trend+event | HIGH/TREND/MACRO | 892 | 14 | 0.270 | 0.276 | +0.006 | 0.2037 [+0.1770, +0.2312] | 0.0660 | LOW_SUPPORT |
| gbm_m2 | C_call | volatility+trend+event | HIGH/TREND/NORMAL | 4,324 | 68 | 0.258 | 0.264 | +0.006 | 0.1926 [+0.1736, +0.2112] | 0.0248 | ok |
| gbm_m2 | C_call | volatility+trend+event | HIGH/CHOP/MACRO | 955 | 15 | 0.276 | 0.292 | +0.016 | 0.2086 [+0.1722, +0.2465] | 0.0852 | LOW_SUPPORT |
| gbm_m2 | C_call | volatility+trend+event | NORMAL/TREND/MACRO | 467 | 8 | 0.225 | 0.246 | +0.022 | 0.1765 [+0.0977, +0.2514] | 0.0680 | LOW_SUPPORT |
| gbm_m2 | C_call | volatility+trend+event | LOW/CHOP/NORMAL | 475 | 8 | 0.233 | 0.175 | -0.059 | 0.1468 [+0.0977, +0.2107] | 0.0620 | LOW_SUPPORT |
| gbm_m2 | C_call | volatility+trend+event | NORMAL/CHOP/MACRO | 697 | 11 | 0.281 | 0.217 | -0.064 | 0.1786 [+0.1388, +0.2173] | 0.1042 | LOW_SUPPORT |
| gbm_m2 | C_put | volatility+trend+event | LOW/TREND/NORMAL | 2,188 | 35 | 0.265 | 0.260 | -0.006 | 0.1884 [+0.1627, +0.2142] | 0.0359 | ok |
| gbm_m2 | C_put | volatility+trend+event | NORMAL/TREND/NORMAL | 3,563 | 56 | 0.289 | 0.283 | -0.006 | 0.2063 [+0.1843, +0.2285] | 0.0576 | ok |
| gbm_m2 | C_put | volatility+trend+event | LOW/TREND/MACRO | 318 | 5 | 0.272 | 0.233 | -0.039 | 0.1733 [+0.0980, +0.2481] | 0.1576 | LOW_SUPPORT |
| gbm_m2 | C_put | volatility+trend+event | NORMAL/CHOP/NORMAL | 5,509 | 87 | 0.286 | 0.313 | +0.027 | 0.2125 [+0.1932, +0.2315] | 0.0297 | ok |
| gbm_m2 | C_put | volatility+trend+event | HIGH/CHOP/NORMAL | 8,398 | 133 | 0.272 | 0.296 | +0.025 | 0.2091 [+0.1941, +0.2239] | 0.0315 | ok |
| gbm_m2 | C_put | volatility+trend+event | HIGH/TREND/MACRO | 892 | 14 | 0.286 | 0.327 | +0.042 | 0.2188 [+0.1750, +0.2619] | 0.0508 | LOW_SUPPORT |
| gbm_m2 | C_put | volatility+trend+event | HIGH/TREND/NORMAL | 4,325 | 68 | 0.273 | 0.257 | -0.016 | 0.1894 [+0.1678, +0.2124] | 0.0250 | ok |
| gbm_m2 | C_put | volatility+trend+event | HIGH/CHOP/MACRO | 954 | 15 | 0.273 | 0.309 | +0.036 | 0.2140 [+0.1790, +0.2478] | 0.0848 | LOW_SUPPORT |
| gbm_m2 | C_put | volatility+trend+event | NORMAL/TREND/MACRO | 464 | 8 | 0.284 | 0.231 | -0.053 | 0.1774 [+0.1272, +0.2311] | 0.0959 | LOW_SUPPORT |
| gbm_m2 | C_put | volatility+trend+event | LOW/CHOP/NORMAL | 475 | 8 | 0.266 | 0.269 | +0.004 | 0.1927 [+0.1353, +0.2437] | 0.0787 | LOW_SUPPORT |
| gbm_m2 | C_put | volatility+trend+event | NORMAL/CHOP/MACRO | 698 | 11 | 0.280 | 0.213 | -0.066 | 0.1686 [+0.1272, +0.2105] | 0.0698 | LOW_SUPPORT |
