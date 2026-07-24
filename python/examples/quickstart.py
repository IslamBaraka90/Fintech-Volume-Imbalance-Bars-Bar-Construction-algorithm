"""Quickstart: Volume-Imbalance Bars, batch and streaming (with adaptive state).

Run:  python examples/quickstart.py
"""

from fintech_volume_imbalance_bars import StreamingVolumeImbalanceBarBuilder, construct_bars

config = {
    "closePartial": True,
    "initialTickSign": 1,
    "initialExpectedTicks": 4,
    "initialExpectedSignedVolume": 50,
    "alphaTicks": 0.25,
    "alphaSignedVolume": 0.25,
    "thresholdFloorShares": 120,
    "thresholdScale": 1,
}
specs = [(100.00, 60), (100.00, 40), (99.99, 70), (99.98, 90), (99.98, 50), (99.97, 95), (99.98, 80), (99.99, 55)]
trades = [
    {"tradeId": f"W{i+1:02d}", "timestamp": f"2026-01-05T14:30:{i:02d}.000Z", "session": "2026-01-05",
     "symbol": "SYNTH", "price": p, "volume": v, "currency": "USD"}
    for i, (p, v) in enumerate(specs)
]

# 1) Batch: a bar closes when |signed volume| reaches its frozen threshold.
for bar in construct_bars(trades, config):
    print(f"bar {bar['barIndex']}: signedVolume={bar['signedVolume']:>7} "
          f"threshold={bar['thresholdShares']:>9} overshoot={bar['overshootShares']:>7} "
          f"ticks={bar['tickCount']} ({bar['closeReason']})")

# 2) Streaming: watch the size-weighted imbalance build and the threshold adapt.
print("--- streaming (adaptive state) ---")
builder = StreamingVolumeImbalanceBarBuilder(config)
print(f"seed: E[ticks]={builder.expected_ticks} E[signed]={builder.expected_signed_volume} "
      f"threshold={builder.threshold}")
for trade in trades:
    closed = builder.push(trade)
    for bar in closed:
        print(f"  closed on {trade['tradeId']}: |{bar['signedVolume']}| >= {bar['thresholdShares']} "
              f"-> new E[ticks]={builder.expected_ticks:.4f} threshold={builder.threshold:.4f}")
    if not closed:
        print(f"  {trade['tradeId']}: signedVolume={builder.signed_volume:>7} "
              f"(threshold {builder.threshold})")
for bar in builder.flush():
    print(f"  flushed partial: ticks={bar['tickCount']} ({bar['closeReason']})")
