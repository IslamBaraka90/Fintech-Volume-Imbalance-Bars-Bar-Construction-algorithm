/**
 * Quickstart: Volume-Imbalance Bars, batch and streaming (with adaptive state).
 *
 * Run:  node --experimental-strip-types examples/quickstart.ts
 */

import { constructBars, type Config, type Trade } from "../src/bars.ts";
import { StreamingVolumeImbalanceBarBuilder } from "../src/streaming.ts";

const config: Config = {
  closePartial: true,
  initialTickSign: 1,
  initialExpectedTicks: 4,
  initialExpectedSignedVolume: 50,
  alphaTicks: 0.25,
  alphaSignedVolume: 0.25,
  thresholdFloorShares: 120,
  thresholdScale: 1,
};
const specs: Array<[number, number]> = [
  [100.0, 60], [100.0, 40], [99.99, 70], [99.98, 90], [99.98, 50], [99.97, 95], [99.98, 80], [99.99, 55],
];
const trades: Trade[] = specs.map(([price, volume], i) => ({
  tradeId: `W${String(i + 1).padStart(2, "0")}`,
  timestamp: `2026-01-05T14:30:${String(i).padStart(2, "0")}.000Z`,
  session: "2026-01-05",
  symbol: "SYNTH",
  price,
  volume,
  currency: "USD",
}));

// 1) Batch: a bar closes when |signed volume| reaches its frozen threshold.
for (const bar of constructBars(trades, config)) {
  console.log(`bar ${bar.barIndex}: signedVolume=${bar.signedVolume} threshold=${bar.thresholdShares} overshoot=${bar.overshootShares} ticks=${bar.tickCount} (${bar.closeReason})`);
}

// 2) Streaming: watch the size-weighted imbalance build and the threshold adapt.
console.log("--- streaming (adaptive state) ---");
const builder = new StreamingVolumeImbalanceBarBuilder(config);
console.log(`seed: E[ticks]=${builder.expectedTicks} E[signed]=${builder.expectedSignedVolume} threshold=${builder.threshold}`);
for (const trade of trades) {
  const closed = builder.push(trade);
  for (const bar of closed) {
    console.log(`  closed on ${trade.tradeId}: |${bar.signedVolume}| >= ${bar.thresholdShares} -> new E[ticks]=${builder.expectedTicks.toFixed(4)} threshold=${builder.threshold.toFixed(4)}`);
  }
  if (!closed.length) {
    console.log(`  ${trade.tradeId}: signedVolume=${builder.signedVolume} (threshold ${builder.threshold})`);
  }
}
for (const bar of builder.flush()) {
  console.log(`  flushed partial: ticks=${bar.tickCount} (${bar.closeReason})`);
}
