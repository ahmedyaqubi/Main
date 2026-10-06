# M4 gate evaluation (spec §11 gates 1-2)

| gate | result | numbers | rule |
|---|---|---|---|
| 1 Data coverage | PASS | sessions=882; sessions_below_bar_coverage=0; min_bar_coverage_seen=0.9923; sessions_with_valid_chain=879; valid_chain_session_share=0.9966 | all sessions >= 98% RTH bars; >= 95% of sessions with a valid chain at >= 95% of prediction timestamps |
| 2 Data quality | PASS | open_critical_events=0; invalid_quote_rate=0.0002544 | 0 open CRITICAL events; invalid-quote rate <= 2% (D+1, ATM +- 5, RTH) |

Overall ATM invalid-quote rate: 1,919/7,543,994 = 0.0254%.
Open CRITICAL events: 0 (see reports/dq/full_history.md).
