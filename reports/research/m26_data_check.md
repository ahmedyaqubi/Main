# M26 data check: Tiingo SPY from 1993 (ADR-0017 D2; ADR-0016 A1 checks)

Generated 2026-10-13 07:44 UTC by `scripts/m26_verify_data.py`. Development rows only, 1993-01-29 → 2015-12-31; the holdout was not read. Data quality only: no strategy computation.

| rows | missing sessions | extra dates | adjustment violations | jumps > 15% (unexplained) | dividends per full year |
|---|---|---|---|---|---|
| 5,774 | 0 | 0 | 0 | 0 (0) | 1994: 4, 1995: 4, 1996: 4, 1997: 4, 1998: 4, 1999: 4, 2000: 4, 2001: 4, 2002: 4, 2003: 4, 2004: 5, 2005: 4, 2006: 4, 2007: 4, 2008: 4, 2009: 4, 2010: 4, 2011: 4, 2012: 4, 2013: 4, 2014: 4, 2015: 4 |

(e) SPY vs Shiller S&P 500 (Yale `ie_data.xls`), 275 months from 1993-02: price-ratio months outside ±1% of the median: **0**. Trailing-12-month dividend months outside ±10%: **55**.

## Verdict: **PASS**

- All checks passed, with the explained exceptions below.

Explained exceptions (ADR-0017 E1, decided after seeing the result, disclosed):

- 2004: 5 dividends (special dividend, ex 2004-11-15; SPY N-30D filed 2005-12-01)
- Shiller dividends: 55 months outside ±10% explained by SPY's fees (1993-2000-12, SPY below Shiller by 0-15%: 45 months) or by the 2004 special dividend in the trailing 12 months (10 months); largest gaps [('2000-01', -0.136), ('2000-02', -0.137), ('2000-06', -0.138)]

SPY ex-dividend dates inside a turn-of-month holding day (-1, +1, +2, +3): **0** of 93. Dividends inside a window would only enter through the adjusted close.

