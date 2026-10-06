"""M1 skeleton tests: T-SMOKE-01, T-SAFE-01, T-CFG-01 (see docs/TEST_PLAN.md)."""

import importlib
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "qqq1dte"
SPEC = ROOT / "docs" / "PHASE_1_SPEC.md"
CONFIG = ROOT / "configs" / "phase1.yaml"

SUBPACKAGES = [
    "core",
    "ingestion",
    "validation",
    "features",
    "labels",
    "models",
    "calibration",
    "regimes",
    "backtesting",
    "execution_sim",
    "journal",
    "monitoring",
]

# Identifiers that indicate order placement / routing. Hard rule 1.
FORBIDDEN_ORDER_PATTERNS = [
    r"\bplaceOrder\b",
    r"\bplace_order\b",
    r"\bsubmit_order\b",
    r"\bsubmitOrder\b",
    r"\bcancelOrder\b",
    r"\bMarketOrder\b",
    r"\bLimitOrder\b",
    r"/iserver/account/[^\s\"']*/orders",
]


@pytest.mark.parametrize("name", ["qqq1dte", *(f"qqq1dte.{m}" for m in SUBPACKAGES)])
def test_smoke_01_package_imports(name: str) -> None:
    importlib.import_module(name)


def test_safe_01_no_order_code() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_ORDER_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(ROOT)}: {pattern}")
    assert not offenders, f"order-placement code found: {offenders}"


def _lookup(cfg: dict[str, Any], dotted: str) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, f"config key missing: {dotted}"
        node = node[part]
    return node


def test_cfg_01_spec_keys_exist_and_match() -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    spec = SPEC.read_text(encoding="utf-8")
    sections = set(cfg)
    # Backticked `section.key` or `section.key = value` references in the spec.
    refs = re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)(?: = ([^`]+))?`", spec)
    checked = 0
    for key, raw_value in refs:
        if key.split(".")[0] not in sections:
            continue
        actual = _lookup(cfg, key)
        if raw_value:
            expected = yaml.safe_load(raw_value)
            assert actual == expected, f"{key}: spec says {expected!r}, config has {actual!r}"
        checked += 1
    assert checked >= 20, f"only {checked} spec config references found; parser broken?"


DATA_SUFFIXES = (".dbn", ".zst", ".parquet", ".dbn.zst", ".feather", ".arrow", ".csv.gz")


def test_safe_02_no_market_data_tracked_in_git() -> None:
    """The repo may be public and vendor licences forbid redistribution (M2 ADR-0002 notes)."""
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(
        [git, "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    offenders = [
        f
        for f in tracked
        if f.endswith(DATA_SUFFIXES) or (f.startswith("data/") and f != "data/.gitkeep")
    ]
    assert not offenders, f"market data files tracked in git: {offenders}"
