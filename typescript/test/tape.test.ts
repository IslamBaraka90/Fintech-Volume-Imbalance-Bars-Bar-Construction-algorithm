import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { constructBars, type Config } from "../src/bars.ts";
import { loadTrades } from "../src/tape.ts";

const CONFIG: Config = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/worked_example.json", import.meta.url)), "utf8"),
).config;
const TAPE_PATH = fileURLToPath(new URL("./fixtures/trade_tape.csv", import.meta.url));

test("loadTrades parses the tape", () => {
  const trades = loadTrades(TAPE_PATH);
  assert.equal(trades.length, 8);
  assert.equal(trades[0].tradeId, "W01");
  assert.equal(trades[0].volume, 60);
});

test("constructBars over the loaded tape", () => {
  const bars = constructBars(loadTrades(TAPE_PATH), CONFIG);
  assert.deepEqual(bars.map((b) => b.signedVolume), [-205, 135]);
  assert.deepEqual(bars.map((b) => b.thresholdShares), [200, 130.3125]);
  assert.deepEqual(bars.map((b) => b.overshootShares), [5, 4.6875]);
});
