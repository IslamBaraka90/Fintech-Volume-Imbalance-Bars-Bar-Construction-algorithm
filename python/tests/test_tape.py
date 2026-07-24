"""Trade-tape loader tests (imbalance bars need per-trade price *and* volume)."""

import json
from pathlib import Path

from fintech_volume_imbalance_bars import construct_bars, load_trades

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = json.loads((FIXTURES / "worked_example.json").read_text())["config"]


def test_load_trades_parses_tape():
    trades = load_trades(FIXTURES / "trade_tape.csv")
    assert len(trades) == 8
    assert trades[0]["tradeId"] == "W01"
    assert trades[0]["volume"] == 60.0 and isinstance(trades[0]["volume"], float)


def test_construct_bars_over_loaded_tape():
    bars = construct_bars(load_trades(FIXTURES / "trade_tape.csv"), CONFIG)
    assert [b["signedVolume"] for b in bars] == [-205.0, 135.0]
    assert [b["thresholdShares"] for b in bars] == [200.0, 130.3125]
    assert [b["overshootShares"] for b in bars] == [5.0, 4.6875]
