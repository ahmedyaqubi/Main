# M25 data check: Tiingo ETF series (ADR-0016 D2, amendment A1)

Generated 2026-10-13 07:05 UTC by `scripts/m25_verify_data.py`. Development period only, 2004-11-18 → 2015-12-31; the holdout was not read. Data quality only: no strategy computation.

| ticker | rows | missing sessions | extra dates | adjustment violations | jumps > 15% (unexplained) | dividends per full year |
|---|---|---|---|---|---|---|
| SPY | 2,799 | 0 | 0 | 0 | 0 (0) | 2005: 4, 2006: 4, 2007: 4, 2008: 4, 2009: 4, 2010: 4, 2011: 4, 2012: 4, 2013: 4, 2014: 4, 2015: 4 |
| QQQ | 2,799 | 0 | 0 | 0 | 0 (0) | 2005: 2, 2006: 4, 2007: 4, 2008: 4, 2009: 4, 2010: 4, 2011: 4, 2012: 4, 2013: 4, 2014: 5, 2015: 4 |
| TLT | 2,799 | 0 | 0 | 0 | 0 (0) | 2005: 12, 2006: 12, 2007: 12, 2008: 12, 2009: 12, 2010: 12, 2011: 12, 2012: 12, 2013: 12, 2014: 12, 2015: 12 |
| GLD | 2,799 | 0 | 0 | 0 | 0 (0) | 2005: 0, 2006: 0, 2007: 0, 2008: 0, 2009: 0, 2010: 0, 2011: 0, 2012: 0, 2013: 0, 2014: 0, 2015: 0 |

(e) SPY vs Shiller S&P 500 (Yale `ie_data.xls`), 132 months: price-ratio months outside ±1% of the median: **0**. Trailing-12-month dividend months outside ±10%: **0**.

## Verdict: **PASS**

- All A1 checks passed, with the explained exceptions below.

Explained exceptions (ADR-0016 E1, decided after seeing the result, disclosed):

- QQQ 2005: 2 dividends (SEC N-30B-2 FY2005 $0.41 and FY2006 $0.18 per share match Tiingo)
- QQQ 2014: 5 dividends (Nasdaq record: extra payment $0.37313, ex-date 2014-02-27)

Limit (A1): QQQ, TLT and GLD have internal checks only; SPY also has the independent Shiller check.

