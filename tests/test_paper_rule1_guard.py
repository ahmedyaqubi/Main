"""ADR-0022 P6 (hard rule 1): no broker connection of any kind anywhere in the code: no broker
SDK import, no broker order or account endpoint, no IBKR API port."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CODE = sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")])

FORBIDDEN = {
    "broker SDK import": r"^\s*(?:import|from)\s+(?:ibapi|ib_insync|ib_async|ibkr|webull)\b",
    "IBKR API port": r"(?<![\d.])(?:7496|7497|4001|4002)(?![\d.])",
    "IBKR Client Portal endpoint": r"/v1/api/|/iserver/",
    "order call": r"\b(?:placeOrder|place_order|submit_order|submitOrder|cancelOrder)\b",
}


@pytest.mark.parametrize("kind", sorted(FORBIDDEN))
def test_no_broker_connection_code(kind: str) -> None:
    pat = re.compile(FORBIDDEN[kind], re.MULTILINE)
    offenders = [str(p.relative_to(ROOT)) for p in CODE if pat.search(p.read_text("utf-8"))]
    assert not offenders, f"{kind} found in {offenders}"


def test_guard_sees_the_paper_scripts() -> None:
    names = {p.name for p in CODE}
    assert {"m32_evening.py", "m32_record_fill.py", "m32_review.py"} <= names


@pytest.mark.parametrize(
    "line",
    [
        "import ib_insync",
        "from ibapi.client import EClient",
        "port = 7497",
        "connect(host, 4002)",
        "url = base + '/v1/api/iserver/account'",
    ],
)
def test_patterns_catch_examples(line: str) -> None:
    assert any(re.search(p, line, re.MULTILINE) for p in FORBIDDEN.values())
