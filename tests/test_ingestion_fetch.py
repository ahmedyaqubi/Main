"""Databento fetch planning and guarded download, with a fake client (no network, no cost)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from qqq1dte.ingestion.databento_fetch import (
    CostCapExceededError,
    FetchRequest,
    RetryPolicy,
    download,
    occ_symbol,
    option_symbols_for_day,
    price,
    strike_band,
)


# planning ---------------------------------------------------------------------------------
def test_occ_symbol_format() -> None:
    assert occ_symbol("QQQ", date(2025, 3, 11), "C", 483) == "QQQ   250311C00483000"
    assert occ_symbol("QQQ", date(2025, 3, 11), "P", 483.5) == "QQQ   250311P00483500"


def test_strike_band_pads_day_range() -> None:
    # 5% below the low and 5% above the high, whole-dollar strikes, inclusive.
    assert strike_band(low=100.0, high=110.0, pad=0.05) == list(range(95, 117))  # 115.5 -> 116
    assert strike_band(low=100.4, high=100.4, pad=0.0) == [100, 101]


def test_option_symbols_next_two_sessions() -> None:
    sessions = [date(2025, 3, 13), date(2025, 3, 14), date(2025, 3, 17), date(2025, 3, 18)]
    syms = option_symbols_for_day("QQQ", date(2025, 3, 14), sessions, [100, 101], (1, 2))
    assert syms == (
        "QQQ   250317C00100000", "QQQ   250317C00101000",
        "QQQ   250317P00100000", "QQQ   250317P00101000",
        "QQQ   250318C00100000", "QQQ   250318C00101000",
        "QQQ   250318P00100000", "QQQ   250318P00101000",
    )  # fmt: skip


# fake client ------------------------------------------------------------------------------
class SymbologyError(Exception):
    pass


class FakeClient:
    def __init__(self, costs: dict[str, float | None], fail_first: int = 0) -> None:
        self.costs = costs  # key: request start date; None = no symbols resolve
        self.downloaded: list[Path] = []
        self.fail_first = fail_first

        class _Meta:
            def get_cost(_self, **kw: Any) -> float:  # noqa: N805
                c = self.costs[kw["start"]]
                if c is None:
                    raise SymbologyError("422 symbology_invalid_request")
                return c

        class _Ts:
            def get_range(_self, **kw: Any) -> None:  # noqa: N805
                if self.fail_first:
                    self.fail_first -= 1
                    raise TimeoutError("504")
                Path(kw["path"]).write_bytes(b"dbn")
                self.downloaded.append(Path(kw["path"]))

        self.metadata = _Meta()
        self.timeseries = _Ts()


def _req(tmp: Path, day: str) -> FetchRequest:
    d = date.fromisoformat(day)
    return FetchRequest(
        dataset="OPRA.PILLAR", schema="cbbo-1m", start=d, end=d.replace(day=d.day + 1),
        symbols=("QQQ   250311C00483000",), stype_in="raw_symbol",
        path=tmp / f"{day}.dbn.zst",
    )  # fmt: skip


def test_price_logs_unresolved_and_skips_existing(tmp_path: Path) -> None:
    reqs = [
        _req(tmp_path, "2025-03-10"),
        _req(tmp_path, "2025-03-11"),
        _req(tmp_path, "2025-03-12"),
    ]
    reqs[2].path.write_bytes(b"already")
    client = FakeClient({"2025-03-10": 1.0, "2025-03-11": None, "2025-03-12": 9.0})
    plan = price(client, reqs, unresolved_errors=(SymbologyError,))
    assert [r.start.isoformat() for r in plan.priced] == ["2025-03-10"]
    assert [r.start.isoformat() for r in plan.unresolved] == ["2025-03-11"]
    assert [r.start.isoformat() for r in plan.already_present] == ["2025-03-12"]
    assert plan.total_usd == pytest.approx(1.0)


def test_download_refuses_over_cap(tmp_path: Path) -> None:
    reqs = [_req(tmp_path, "2025-03-10"), _req(tmp_path, "2025-03-11")]
    client = FakeClient({"2025-03-10": 6.0, "2025-03-11": 6.0})
    plan = price(client, reqs, unresolved_errors=(SymbologyError,))
    with pytest.raises(CostCapExceededError):
        download(client, plan, max_usd=10.0)
    assert client.downloaded == []


def test_download_writes_via_temp_and_retries(tmp_path: Path) -> None:
    reqs = [_req(tmp_path, "2025-03-10")]
    client = FakeClient({"2025-03-10": 1.0}, fail_first=2)
    plan = price(client, reqs, unresolved_errors=(SymbologyError,))
    saved = download(client, plan, max_usd=5.0, retry=RetryPolicy((TimeoutError,), backoff_s=0))
    assert saved == [reqs[0].path]
    assert reqs[0].path.read_bytes() == b"dbn"
    assert not list(tmp_path.glob("*.partial"))
    assert client.downloaded == [reqs[0].path.with_name(reqs[0].path.name + ".partial")]


def test_download_removes_stale_partial(tmp_path: Path) -> None:
    req = _req(tmp_path, "2025-03-10")
    stale = req.path.with_name(req.path.name + ".partial")
    stale.write_bytes(b"incomplete")
    client = FakeClient({"2025-03-10": 1.0})
    download(client, price(client, [req], unresolved_errors=(SymbologyError,)), max_usd=5.0)
    assert req.path.read_bytes() == b"dbn"
    assert not stale.exists()
