# M27 holdout (ADR-0019): **STOP — data checks failed**

Run `screen_pullback_holdout-b47cc1560348`. No strategy statistic was computed. The holdout counts as opened. A new ADR is needed for any exception (H2).

- (e) Shiller price: 1 months outside ±1%, e.g. [('2023-09', 0.024705457921270435)]

- (a)-(c), opens: 2,701 holdout rows; 0 missing, 0 adjustment, 0 jump, 0 open-ratio, 0 open-gap findings
- (d) dividends per year 2016-2025: [4, 4, 4, 4, 4, 4, 4, 4, 4, 4]
- (e) Shiller: 93 price months (2016-01 → 2023-09), 1 outside ±1%; 90 dividend months (→ 2023-06), 0 outside ±10%. After 2023-09: internal checks only (A1).

