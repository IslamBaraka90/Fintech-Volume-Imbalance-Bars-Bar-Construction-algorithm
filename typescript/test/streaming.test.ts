import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { VolumeImbalanceBarsValidationError, constructBars, type Config, type Trade } from "../src/bars.ts";
import { StreamingVolumeImbalanceBarBuilder } from "../src/streaming.ts";

const FIXTURE = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/worked_example.json", import.meta.url)), "utf8"),
);
const CONFIG: Config = FIXTURE.config;
const TRADES: Trade[] = FIXTURE.trades;
const TRACE = FIXTURE.trace as Array<{ tradeId: string; cumulativeSignedShares: number }>;
const POST_FIRST = FIXTURE.postFirstClose;

function stream(trades: Trade[], config: Config) {
  const builder = new StreamingVolumeImbalanceBarBuilder(config);
  const emitted = builder.pushMany(trades);
  emitted.push(...builder.flush());
  return emitted;
}

test("streaming matches batch", () => {
  assert.deepEqual(stream(TRADES, CONFIG), constructBars(TRADES, CONFIG));
});

test("streaming matches batch with defaults", () => {
  assert.deepEqual(stream(TRADES, {}), constructBars(TRADES, {}));
});

test("streaming matches batch (closePartial=false)", () => {
  const config = { ...CONFIG, closePartial: false };
  assert.deepEqual(stream(TRADES.slice(0, 3), config), constructBars(TRADES.slice(0, 3), config));
});

test("state is observable and seeded", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  assert.equal(builder.expectedTicks, 4);
  assert.equal(builder.expectedSignedVolume, 50);
  assert.equal(builder.threshold, 200);
  assert.equal(builder.signedVolume, 0);
  assert.equal(builder.tickCount, 0);
});

test("signed volume tracks the documented trace", () => {
  // W06 and W08 each close a bar, resetting the accumulator to 0.
  const closingIds = new Set(["W06", "W08"]);
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  TRACE.forEach((step, index) => {
    const closed = builder.push(TRADES[index]);
    if (closingIds.has(step.tradeId)) {
      assert.equal(closed.length, 1);
      assert.equal(closed[0].signedVolume, step.cumulativeSignedShares);
      assert.equal(builder.signedVolume, 0);
    } else {
      assert.deepEqual(closed, []);
      assert.equal(builder.signedVolume, step.cumulativeSignedShares, step.tradeId);
    }
  });
});

test("state updates after a threshold close", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  const closed = builder.pushMany(TRADES.slice(0, 6));
  assert.equal(closed.length, 1);
  assert.equal(closed[0].closeReason, "threshold");
  assert.equal(builder.expectedTicks, POST_FIRST.expectedTicks);
  assert.ok(Math.abs(builder.expectedSignedVolume - POST_FIRST.expectedSignedVolume) < 1e-6);
  assert.ok(Math.abs(builder.threshold - POST_FIRST.nextThresholdShares) < 1e-6);
});

test("push emits exactly when the threshold is reached", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  for (const trade of TRADES.slice(0, 5)) assert.deepEqual(builder.push(trade), []);
  const closed = builder.push(TRADES[5]);
  assert.equal(closed.length, 1);
  assert.equal(closed[0].signedVolume, -205);
});

test("tick sign carries through flat trades", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  builder.pushMany(TRADES.slice(0, 4));
  assert.equal(builder.tickSign, -1);
});

test("flush closes the partial tail", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  builder.pushMany(TRADES.slice(0, 3));
  const final = builder.flush();
  assert.equal(final.length, 1);
  assert.equal(final[0].closeReason, "stream_end");
});

test("cannot push after flush", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  builder.pushMany(TRADES);
  builder.flush();
  assert.throws(() => builder.push(TRADES[0]), VolumeImbalanceBarsValidationError);
});

test("streaming validates incrementally", () => {
  const builder = new StreamingVolumeImbalanceBarBuilder(CONFIG);
  builder.push(TRADES[0]);
  assert.throws(() => builder.push({ ...TRADES[1], tradeId: "W01" }), VolumeImbalanceBarsValidationError);
});
