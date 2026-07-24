/**
 * Trade-tape loader for Volume-Imbalance Bars.
 *
 * Imbalance bars need each execution's price (to assign a tick sign) and its
 * volume (to weight that sign), so they are built from a trade tape. Yahoo
 * Finance does not expose tick data — only pre-aggregated bars, where the
 * per-trade signs are already lost.
 */

import { readFileSync } from "node:fs";

import type { Trade } from "./bars.ts";

const TRADE_FIELDS = ["tradeId", "timestamp", "session", "symbol", "currency"] as const;

/** Read a trade tape from a CSV into trades for `constructBars`. */
export function loadTrades(csvPath: string): Trade[] {
  const text = readFileSync(csvPath, "utf8").trim();
  const lines = text.split(/\r?\n/);
  if (lines.length < 2) return [];
  const header = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const cells = line.split(",");
    const row: Record<string, string> = {};
    header.forEach((name, i) => {
      row[name] = cells[i];
    });
    const trade: Record<string, unknown> = {};
    for (const field of TRADE_FIELDS) if (field in row) trade[field] = row[field];
    trade.price = Number(row.price);
    trade.volume = Number(row.volume);
    return trade as unknown as Trade;
  });
}
