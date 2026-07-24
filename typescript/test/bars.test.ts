import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { VolumeImbalanceBarsValidationError, constructBars, type Config, type Trade } from "../src/bars.ts";

const FIXTURE = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/worked_example.json", import.meta.url)), "utf8"),
);
const CONFIG: Config = FIXTURE.config;
const TRADES: Trade[] = FIXTURE.trades;
const TRACE = FIXTURE.trace as Array<{ tradeId: string; sign: number; cumulativeSignedShares: number }>;
const POST_FIRST = FIXTURE.postFirstClose;

test("worked example produces two complete bars", () => {
  const bars = constructBars(TRADES, CONFIG);
  assert.equal(bars.length, 2);
  assert.ok(bars.every((b) => b.closeReason === "threshold" && b.isComplete));
});

test("first bar matches the documented trace", () => {
  const bar = constructBars(TRADES, CONFIG)[0];
  const closing = TRACE.find((step) => step.tradeId === "W06")!;
  assert.equal(bar.signedVolume, closing.cumulativeSignedShares);
  assert.equal(bar.signedVolume, -205);
  assert.equal(bar.thresholdShares, 200);
  assert.equal(bar.overshootShares, 5);
  assert.equal(bar.tickCount, 6);
  assert.equal(bar.lastTradeId, "W06");
  assert.equal(bar.thresholdMet, true);
});

test("frozen snapshot is reported on the bar", () => {
  const bars = constructBars(TRADES, CONFIG);
  assert.equal(bars[0].expectedTicksBefore, CONFIG.initialExpectedTicks);
  assert.equal(bars[0].expectedSignedVolumeBefore, CONFIG.initialExpectedSignedVolume);
  assert.equal(bars[1].expectedTicksBefore, POST_FIRST.expectedTicks);
  assert.equal(bars[1].expectedSignedVolumeBefore, POST_FIRST.expectedSignedVolume);
  assert.equal(bars[1].thresholdShares, POST_FIRST.nextThresholdShares);
  assert.equal(bars[1].thresholdShares, 130.3125);
});

test("second bar matches the documented trace", () => {
  const bar = constructBars(TRADES, CONFIG)[1];
  assert.equal(bar.signedVolume, 135);
  assert.equal(bar.overshootShares, 4.6875);
  assert.equal(bar.tickCount, 2);
});

test("size weighting distinguishes this from tick imbalance", () => {
  const base = { timestamp: "2026-01-05T14:30:00.000Z", session: "S", symbol: "X", currency: "USD" };
  const big: Trade[] = [{ ...base, tradeId: "BIG", price: 100, volume: 500 }];
  assert.equal(constructBars(big, { ...CONFIG, thresholdFloorShares: 200 })[0].closeReason, "threshold");
  const small: Trade[] = [{ ...base, tradeId: "SMALL", price: 100, volume: 5 }];
  assert.equal(constructBars(small, { ...CONFIG, thresholdFloorShares: 200 })[0].closeReason, "stream_end");
});

test("flat trade carries the preceding sign", () => {
  const signs = Object.fromEntries(TRACE.map((s) => [s.tradeId, s.sign]));
  assert.equal(signs.W02, 1);
  assert.equal(signs.W05, -1);
});

test("equal timestamps retain input order", () => {
  assert.equal(TRADES[0].timestamp, TRADES[1].timestamp);
  assert.equal(constructBars(TRADES, CONFIG)[0].firstTradeId, "W01");
});

test("partial bar is not complete and does not learn", () => {
  const bars = constructBars(TRADES.slice(0, 3), CONFIG);
  assert.equal(bars.length, 1);
  assert.equal(bars[0].closeReason, "stream_end");
  assert.equal(bars[0].isComplete, false);
  assert.equal(bars[0].thresholdMet, false);
  assert.equal(bars[0].expectedTicksBefore, 4);
});

test("closePartial=false drops the tail", () => {
  assert.deepEqual(constructBars(TRADES.slice(0, 3), { ...CONFIG, closePartial: false }), []);
});

test("config defaults apply", () => {
  const bars = constructBars(TRADES, {});
  assert.equal(bars[0].thresholdShares, 560); // max(300, 16*35)
  assert.equal(bars[0].expectedTicksBefore, 16);
  assert.equal(bars[0].expectedSignedVolumeBefore, 35);
});

test("threshold floor applies", () => {
  const bars = constructBars(TRADES, { ...CONFIG, thresholdFloorShares: 10000 });
  assert.equal(bars.length, 1);
  assert.equal(bars[0].closeReason, "stream_end");
  assert.equal(bars[0].thresholdShares, 10000);
});

test("empty trades returns empty", () => {
  assert.deepEqual(constructBars([], CONFIG), []);
});

test("rejects bad config", () => {
  const overrides: Array<Partial<Config>> = [
    { initialTickSign: 0 as unknown as 1 },
    { initialExpectedTicks: 0 },
    { alphaTicks: 0 },
    { alphaSignedVolume: 1.5 },
    { thresholdFloorShares: -1 },
    { thresholdScale: 0 },
    { closePartial: "yes" as unknown as boolean },
  ];
  for (const override of overrides) {
    assert.throws(() => constructBars(TRADES, { ...CONFIG, ...override }), VolumeImbalanceBarsValidationError);
  }
});

test("negative initial expected signed volume is allowed", () => {
  const bars = constructBars(TRADES, { ...CONFIG, initialExpectedSignedVolume: -50 });
  assert.equal(bars[0].thresholdShares, 200);
});

test("rejects duplicate trade id", () => {
  assert.throws(
    () => constructBars([TRADES[0], { ...TRADES[1], tradeId: "W01" }], CONFIG),
    VolumeImbalanceBarsValidationError,
  );
});

test("rejects unordered trades", () => {
  assert.throws(() => constructBars([...TRADES].reverse(), CONFIG), VolumeImbalanceBarsValidationError);
});

test("rejects mixed currency", () => {
  assert.throws(
    () => constructBars([TRADES[0], { ...TRADES[1], currency: "EUR" }], CONFIG),
    VolumeImbalanceBarsValidationError,
  );
});
