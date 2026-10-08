# M19T Step 0: data-gap price quote (ADR-0013 D0) - price only, nothing downloaded

Databento metadata.get_cost, 2026-10-08. Retail usage-based rates; M4's whole history purchase was priced at $13.26 (reference).

| item | scope | sessions | priced USD | unresolved requests | note |
|---|---|---|---|---|---|
| A | 0DTE contracts, dev 2023-03-28 -> 2026-04-02 | 757 | 5.08 | 0 | missing daily range: 0 |
| H | 0DTE contracts, holdout 2026-04-03 -> 2026-10-02 (optional) | 126 | 1.21 | 0 | storage only; access per ADR-0011 / ADR-0013 D7 |
| X | QQQ daily bars 2020-01-02 -> 2023-03-27 (XNAS.ITCH) | 814 | 0.0013 | - | strike-band selection only |
| E | D2 extension options (expiring D and D+1) | 814 | ~9 (ROUGH) | - | exact quote needs X first; per-session cost and quote volume pre-2023 may differ |
| F | forward collection, per month (Sept 2026 as proxy) | 21 | 0.64 | - | options D+1/D+2 0.42 + underlying 0.01 + 0DTE 0.21; excludes cross-asset feeds |
