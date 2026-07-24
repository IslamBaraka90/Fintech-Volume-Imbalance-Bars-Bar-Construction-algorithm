"""Exactness and contract tests for Volume-Imbalance Bars.

The worked-example fixture ships a per-trade ``trace`` (sign, signed shares,
running cumulative) plus ``postFirstClose`` EWMA values. Both language suites
walk that trace and assert the same numbers.
"""

import json
from pathlib import Path

import pytest

from fintech_volume_imbalance_bars import VolumeImbalanceBarsValidationError, construct_bars

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "worked_example.json").read_text())
CONFIG = FIXTURE["config"]
TRADES = FIXTURE["trades"]
TRACE = FIXTURE["trace"]
POST_FIRST = FIXTURE["postFirstClose"]


def test_worked_example_produces_two_complete_bars():
    bars = construct_bars(TRADES, CONFIG)
    assert len(bars) == 2
    assert all(b["closeReason"] == "threshold" and b["isComplete"] for b in bars)


def test_first_bar_matches_the_documented_trace():
    bar = construct_bars(TRADES, CONFIG)[0]
    # The trace closes bar 0 on W06 at cumulative -205 against a 200-share
    # frozen threshold, overshooting by 5.
    closing = next(step for step in TRACE if step["tradeId"] == "W06")
    assert bar["signedVolume"] == closing["cumulativeSignedShares"] == -205
    assert bar["thresholdShares"] == 200  # max(120, 1 * 4 * |50|)
    assert bar["overshootShares"] == 5
    assert bar["tickCount"] == 6
    assert bar["lastTradeId"] == "W06"
    assert bar["thresholdMet"] is True


def test_frozen_snapshot_is_reported_on_the_bar():
    # Every bar reports the expectations it was actually judged against.
    bars = construct_bars(TRADES, CONFIG)
    assert bars[0]["expectedTicksBefore"] == CONFIG["initialExpectedTicks"] == 4
    assert bars[0]["expectedSignedVolumeBefore"] == CONFIG["initialExpectedSignedVolume"] == 50
    # Bar 1 was judged against the post-first-close snapshot.
    assert bars[1]["expectedTicksBefore"] == POST_FIRST["expectedTicks"] == 4.5
    assert bars[1]["expectedSignedVolumeBefore"] == POST_FIRST["expectedSignedVolume"]
    assert bars[1]["thresholdShares"] == POST_FIRST["nextThresholdShares"] == 130.3125


def test_second_bar_matches_the_documented_trace():
    bar = construct_bars(TRADES, CONFIG)[1]
    assert bar["signedVolume"] == 135  # +80 (W07) +55 (W08)
    assert bar["overshootShares"] == 4.6875
    assert bar["tickCount"] == 2


def test_size_weighting_distinguishes_this_from_tick_imbalance():
    # A single large print can close a bar that many small ones would not.
    base = {"timestamp": "2026-01-05T14:30:00.000Z", "session": "S", "symbol": "X", "currency": "USD"}
    big = [{**base, "tradeId": "BIG", "price": 100.0, "volume": 500}]
    assert construct_bars(big, {**CONFIG, "thresholdFloorShares": 200})[0]["closeReason"] == "threshold"
    # Same tick count (1), but a tiny size does not reach the threshold.
    small = [{**base, "tradeId": "SMALL", "price": 100.0, "volume": 5}]
    assert construct_bars(small, {**CONFIG, "thresholdFloorShares": 200})[0]["closeReason"] == "stream_end"


def test_flat_trade_carries_the_preceding_sign():
    # W02 is flat after W01 and carries +1; W05 is flat after a downtick and carries -1.
    signs = {step["tradeId"]: step["sign"] for step in TRACE}
    assert signs["W02"] == 1 and signs["W05"] == -1


def test_equal_timestamps_retain_input_order():
    # W01 and W02 share a timestamp; no sequence field is required here.
    assert TRADES[0]["timestamp"] == TRADES[1]["timestamp"]
    bar = construct_bars(TRADES, CONFIG)[0]
    assert bar["firstTradeId"] == "W01"


def test_partial_bar_is_not_complete_and_does_not_learn():
    bars = construct_bars(TRADES[:3], CONFIG)  # never reaches 200 shares
    assert len(bars) == 1
    assert bars[0]["closeReason"] == "stream_end"
    assert bars[0]["isComplete"] is False
    assert bars[0]["thresholdMet"] is False
    assert bars[0]["expectedTicksBefore"] == 4  # unchanged seeds


def test_close_partial_false_drops_the_tail():
    bars = construct_bars(TRADES[:3], {**CONFIG, "closePartial": False})
    assert bars == []


def test_config_defaults_apply():
    # Defaults: expectedTicks 16, expectedSigned 35, floor 300 -> threshold 560.
    bars = construct_bars(TRADES, {})
    assert bars[0]["thresholdShares"] == 560
    assert bars[0]["expectedTicksBefore"] == 16
    assert bars[0]["expectedSignedVolumeBefore"] == 35


def test_threshold_floor_applies():
    bars = construct_bars(TRADES, {**CONFIG, "thresholdFloorShares": 10_000})
    assert len(bars) == 1 and bars[0]["closeReason"] == "stream_end"
    assert bars[0]["thresholdShares"] == 10_000


def test_empty_trades_returns_empty():
    assert construct_bars([], CONFIG) == []


@pytest.mark.parametrize(
    "override",
    [
        {"initialTickSign": 0},
        {"initialExpectedTicks": 0},
        {"alphaTicks": 0},
        {"alphaSignedVolume": 1.5},
        {"thresholdFloorShares": -1},
        {"thresholdScale": 0},
        {"closePartial": "yes"},
    ],
)
def test_rejects_bad_config(override):
    with pytest.raises(VolumeImbalanceBarsValidationError):
        construct_bars(TRADES, {**CONFIG, **override})


def test_negative_initial_expected_signed_volume_is_allowed():
    # Signed volume is in shares and may legitimately be negative.
    bars = construct_bars(TRADES, {**CONFIG, "initialExpectedSignedVolume": -50})
    assert bars[0]["thresholdShares"] == 200  # abs() is used


def test_rejects_duplicate_trade_id():
    with pytest.raises(VolumeImbalanceBarsValidationError):
        construct_bars([TRADES[0], {**TRADES[1], "tradeId": "W01"}], CONFIG)


def test_rejects_unordered_trades():
    with pytest.raises(VolumeImbalanceBarsValidationError):
        construct_bars(list(reversed(TRADES)), CONFIG)


def test_rejects_mixed_currency():
    with pytest.raises(VolumeImbalanceBarsValidationError):
        construct_bars([TRADES[0], {**TRADES[1], "currency": "EUR"}], CONFIG)
