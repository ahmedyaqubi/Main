"""M19T Step 0, ADR-0013 Q3: supplemental expiry-day download of OCC-adjusted strikes.

The Step-0 0DTE pull (scripts/m19t_fetch.py) requested whole-dollar symbols only. Contracts
listed before OCC memo #53847 (ex-date 2023-12-27) carry adjusted strikes, so their expiry-day
quotes are missing. Example: 2023-12-28 has no 0DTE data at all.

For every expiration carrying adjusted strikes (`adjusted_expirations()`, as M4) that is a session
in 2023-12-28 -> 2026-10-02, this requests on that session the adjusted-strike contracts
expiring that day. Strikes are round(K - reduction, 2) for K on the $0.50 grid of the session's
band, the same rule as M4's supplement. The band is the M4 one (day's range +- 5%); it sets
storage scope only. Holdout sessions are stored only (ADR-0011), as in item H.

Owner approval 2026-10-08: proceed if the exact total is under $20. Prices are cached and files
already on disk are skipped.

    uv run python scripts/m19t_fetch_adjusted.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import databento as db
from dotenv import load_dotenv

from m4_fetch_history import BAND_PAD as M4_PAD
from m4_fetch_history import adjusted_expirations
from m19t_fetch import plan_of
from m19t_price_gap import HOLD, OUT, RETRY, ROOT, daily_ranges, priced
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import FetchRequest, download, occ_symbol

CAP_USD = 20.0  # owner approval 2026-10-08 (ADR-0013 Q3)
MAX_SYMBOLS = 1000


def requests(cal: TradingCalendar) -> tuple[list[FetchRequest], list[date]]:
    adj = cal.cfg.dq.strike_adjustments[0]
    ranges = daily_ranges()
    reqs, missing = [], []
    for e in sorted(adjusted_expirations()):
        if e <= adj.ex_date or e > HOLD[1] or not cal.is_session(e):
            continue  # the ex-date itself is excluded by ADR-0006
        if e not in ranges:
            missing.append(e)  # reported, never guessed
            continue
        lo, hi = ranges[e]
        grid = [x / 2 for x in range(int(lo * (1 - M4_PAD) * 2), int(hi * (1 + M4_PAD) * 2) + 2)]
        strikes = sorted({round(k - adj.reduction, 2) for k in grid})
        syms = tuple(occ_symbol("QQQ", e, r, k) for r in "CP" for k in strikes)
        for j in range(0, len(syms), MAX_SYMBOLS):
            for schema in ("cbbo-1m", "definition"):
                reqs.append(
                    FetchRequest(
                        "OPRA.PILLAR",
                        schema,
                        e,
                        e + timedelta(days=1),
                        syms[j : j + MAX_SYMBOLS],
                        "raw_symbol",
                        OUT
                        / "OPRA.PILLAR"
                        / f"{schema}-0dte"
                        / f"{e}_adj{j // MAX_SYMBOLS}.dbn.zst",
                    )
                )
    return reqs, missing


def main() -> int:
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(load_config())
    client = db.Historical()
    reqs, missing = requests(cal)
    costs = priced(client, reqs)
    plan = plan_of(reqs, costs)
    total = plan.total_usd
    print(
        f"adjusted supplement: {len(reqs)} requests, {len(plan.priced)} to download "
        f"(${total:.4f}), {len(plan.already_present)} on disk, {len(plan.unresolved)} unresolved "
        f"(no listed symbols); sessions without a daily range: {missing}",
        flush=True,
    )
    if total >= CAP_USD:
        print(f"at or over the approved cap ${CAP_USD:.2f}: nothing downloaded, ask the owner")
        return 1
    saved = download(client, plan, max_usd=CAP_USD, retry=RETRY)
    print(f"saved {len(saved)} files; unresolved: {[str(r.path.name) for r in plan.unresolved]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
