"""M27 (ADR-0018 D2): the added open-price check on Tiingo SPY, development rows only (the
holdout lock applies). Any failure = STOP.
- Every session's adj_open / open equals adj_close / close (relative tolerance `open_ratio_tol`).
- Opens more than `open_gap` away from the previous close are listed; any one is a failure
  until explained.

    uv run python scripts/m27_verify_opens.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from qqq1dte.core.config import load_config
from qqq1dte.ingestion.etf_data import dev_only, parse_tiingo
from qqq1dte.validation.etf_checks import open_gaps, open_ratio_violations

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m27_open_check.md"


def main() -> int:
    s = load_config().study_pullback
    rows = json.loads((ROOT / s.raw_dir / "tiingo" / f"{s.ticker}.json").read_text("utf-8"))
    df = dev_only(parse_tiingo(rows, s.ticker), s.dev_end)
    ratio = open_ratio_violations(df, s.open_ratio_tol)
    gaps = open_gaps(df, s.open_gap)
    failures = []
    if ratio:
        failures.append(f"{len(ratio)} open adjustment violations, first {ratio[:5]}")
    if gaps:
        failures.append(f"{len(gaps)} opens more than {s.open_gap:.0%} from the previous close: "
                        f"{gaps[:10]}")  # fmt: skip
    verdict = "PASS" if not failures else "STOP"
    lines = [
        "# M27 open-price check: Tiingo SPY (ADR-0018 D2)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m27_verify_opens.py`. "
        f"Development rows only, {s.data_start} → {s.dev_end} ({df.height:,} sessions); the "
        "holdout was not read. Data quality only: no strategy computation. The M26 checks "
        "(`m26_data_check.md`, PASS with ADR-0017 E1) cover everything else.",
        "",
        f"- Sessions where adj_open / open differs from adj_close / close by more than "
        f"{s.open_ratio_tol:.2%}: **{len(ratio)}**",
        f"- Opens more than {s.open_gap:.0%} from the previous close: **{len(gaps)}**",
        f"- Largest open gap: {max((abs(g) for _, g in open_gaps(df, 0.0)), default=0):.2%}",
        "",
        f"## Verdict: **{verdict}**",
        "",
        *([f"- {f}" for f in failures] or ["- All open checks passed."]),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"verdict {verdict}; wrote {REPORT.relative_to(ROOT)}")
    for f in failures:
        print(" -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
