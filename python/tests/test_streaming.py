"""StreamingVolumeImbalanceBarBuilder: batch parity plus observable state."""

import json
from pathlib import Path

import pytest

from fintech_volume_imbalance_bars import (
    StreamingVolumeImbalanceBarBuilder,
    VolumeImbalanceBarsValidationError,
    construct_bars,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "worked_example.json").read_text())
CONFIG = FIXTURE["config"]
TRADES = FIXTURE["trades"]
POST_FIRST = FIXTURE["postFirstClose"]


def _stream(trades, config):
    builder = StreamingVolumeImbalanceBarBuilder(config)
    emitted = builder.push_many(trades)
    emitted.extend(builder.flush())
    return emitted


def test_streaming_matches_batch():
    assert _stream(TRADES, CONFIG) == construct_bars(TRADES, CONFIG)


def test_streaming_matches_batch_with_defaults():
    assert _stream(TRADES, {}) == construct_bars(TRADES, {})


def test_streaming_matches_batch_close_partial_false():
    config = {**CONFIG, "closePartial": False}
    assert _stream(TRADES[:3], config) == construct_bars(TRADES[:3], config)


def test_state_is_observable_and_seeded():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    assert builder.expected_ticks == 4
    assert builder.expected_signed_volume == 50
    assert builder.threshold == 200  # max(120, 1*4*|50|)
    assert builder.signed_volume == 0 and builder.tick_count == 0


def test_signed_volume_tracks_the_documented_trace():
    # W06 and W08 each close a bar, which resets the accumulator to 0; on every
    # other trade the live signed volume must equal the documented cumulative.
    closing_ids = {"W06", "W08"}
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    for step, trade in zip(FIXTURE["trace"], TRADES):
        closed = builder.push(trade)
        if step["tradeId"] in closing_ids:
            assert closed and closed[0]["signedVolume"] == step["cumulativeSignedShares"]
            assert builder.signed_volume == 0  # accumulator reset for the next bar
        else:
            assert closed == []
            assert builder.signed_volume == step["cumulativeSignedShares"], step["tradeId"]


def test_state_updates_after_a_threshold_close():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    closed = builder.push_many(TRADES[:6])
    assert len(closed) == 1 and closed[0]["closeReason"] == "threshold"
    assert builder.expected_ticks == POST_FIRST["expectedTicks"] == 4.5
    assert builder.expected_signed_volume == pytest.approx(POST_FIRST["expectedSignedVolume"])
    assert builder.threshold == pytest.approx(POST_FIRST["nextThresholdShares"])


def test_push_emits_exactly_when_the_threshold_is_reached():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    for trade in TRADES[:5]:
        assert builder.push(trade) == []
    closed = builder.push(TRADES[5])
    assert len(closed) == 1 and closed[0]["signedVolume"] == -205


def test_tick_sign_carries_through_flat_trades():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    builder.push_many(TRADES[:4])  # ends on a downtick
    assert builder.tick_sign == -1


def test_flush_closes_the_partial_tail():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    builder.push_many(TRADES[:3])
    final = builder.flush()
    assert len(final) == 1 and final[0]["closeReason"] == "stream_end"


def test_cannot_push_after_flush():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    builder.push_many(TRADES)
    builder.flush()
    with pytest.raises(VolumeImbalanceBarsValidationError):
        builder.push(TRADES[0])


def test_streaming_validates_incrementally():
    builder = StreamingVolumeImbalanceBarBuilder(CONFIG)
    builder.push(TRADES[0])
    with pytest.raises(VolumeImbalanceBarsValidationError):
        builder.push({**TRADES[1], "tradeId": "W01"})
