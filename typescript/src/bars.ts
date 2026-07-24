/**
 * Causal Volume-Imbalance Bars under an explicit, disclosed convention.
 *
 * A faithful, cross-language twin of the Python
 * `fintech_volume_imbalance_bars.core` module and of the reference algorithm
 * published at The Fintech Builder (topic `D01-F01-A06`).
 *
 * Volume-imbalance bars weight each signed trade by **how much size** it carried:
 *
 *     signedVolume = sum of (tickSign_i * volume_i)
 *     close the bar when abs(signedVolume) >= threshold
 *
 * The tick rule is unchanged (uptick `+1`, downtick `-1`, flat carries the
 * preceding sign). The threshold adapts through two EWMAs updated only after a
 * **complete** bar, and is **frozen at bar open** so every emitted bar reports the
 * snapshot it was actually judged against.
 */

export class VolumeImbalanceBarsValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VolumeImbalanceBarsValidationError";
  }
}

export interface Trade {
  tradeId: string;
  timestamp: string;
  session: string;
  symbol: string;
  price: number;
  volume: number;
  currency: string;
}

export interface Config {
  closePartial?: boolean;
  initialTickSign?: -1 | 1;
  initialExpectedTicks?: number;
  initialExpectedSignedVolume?: number;
  alphaTicks?: number;
  alphaSignedVolume?: number;
  thresholdFloorShares?: number;
  thresholdScale?: number;
}

export type CloseReason = "threshold" | "session_end" | "stream_end";

export interface Bar {
  barIndex: number;
  session: string;
  startTime: string;
  endTime: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  dollarValue: number;
  tickCount: number;
  firstTradeId: string;
  lastTradeId: string;
  closeReason: CloseReason;
  isComplete: boolean;
  signedVolume: number;
  thresholdShares: number;
  expectedTicksBefore: number;
  expectedSignedVolumeBefore: number;
  overshootShares: number;
  thresholdMet: boolean;
}

export interface NormalizedConfig {
  closePartial: boolean;
  initialSign: number;
  initialExpectedTicks: number;
  initialExpectedSigned: number;
  alphaTicks: number;
  alphaSigned: number;
  floor: number;
  scale: number;
}

export function timestampMs(value: unknown): number {
  if (typeof value !== "string" || !value.endsWith("Z")) {
    throw new VolumeImbalanceBarsValidationError("timestamp must be an ISO-8601 UTC string ending in Z");
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new VolumeImbalanceBarsValidationError("timestamp must be valid ISO-8601");
  return parsed;
}

export function finite(value: unknown, name: string, positive = false): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new VolumeImbalanceBarsValidationError(`${name} must be a finite number`);
  }
  if (positive && value <= 0) throw new VolumeImbalanceBarsValidationError(`${name} must be positive`);
  return value;
}

export function rounded(value: number): number {
  return Number(value.toFixed(8));
}

/** Normalize config, applying the package defaults for anything omitted. */
export function normalized(config: Config): NormalizedConfig {
  if (config === null || typeof config !== "object") {
    throw new VolumeImbalanceBarsValidationError("config must be an object");
  }
  const closePartial = config.closePartial ?? true;
  if (typeof closePartial !== "boolean") throw new VolumeImbalanceBarsValidationError("closePartial must be boolean");
  const initialSign = config.initialTickSign ?? 1;
  if (initialSign !== -1 && initialSign !== 1) {
    throw new VolumeImbalanceBarsValidationError("initialTickSign must be -1 or 1");
  }
  const alphaTicks = finite(config.alphaTicks ?? 0.2, "alphaTicks", true);
  const alphaSigned = finite(config.alphaSignedVolume ?? 0.2, "alphaSignedVolume", true);
  if (alphaTicks > 1 || alphaSigned > 1) {
    throw new VolumeImbalanceBarsValidationError("EMA coefficients must be in (0, 1]");
  }
  return {
    closePartial,
    initialSign,
    initialExpectedTicks: finite(config.initialExpectedTicks ?? 16, "initialExpectedTicks", true),
    // Signed volume is in shares and may legitimately be negative.
    initialExpectedSigned: finite(config.initialExpectedSignedVolume ?? 35, "initialExpectedSignedVolume"),
    alphaTicks,
    alphaSigned,
    floor: finite(config.thresholdFloorShares ?? 300, "thresholdFloorShares", true),
    scale: finite(config.thresholdScale ?? 1, "thresholdScale", true),
  };
}

export function validateTrades(trades: Trade[]): void {
  if (!Array.isArray(trades)) throw new VolumeImbalanceBarsValidationError("trades must be an array");
  const ids = new Set<string>();
  const closedSessions = new Set<string>();
  let previous = -Infinity;
  let currentSession: string | null = null;
  let symbol: string | null = null;
  let currency: string | null = null;
  for (const trade of trades) {
    if (!trade || typeof trade !== "object") {
      throw new VolumeImbalanceBarsValidationError("trade is missing a required field");
    }
    for (const key of ["tradeId", "timestamp", "session", "symbol", "currency"] as const) {
      if (typeof trade[key] !== "string" || !trade[key]) {
        throw new VolumeImbalanceBarsValidationError(`${key} must be a non-empty string`);
      }
    }
    const now = timestampMs(trade.timestamp);
    if (now < previous) throw new VolumeImbalanceBarsValidationError("trades must be globally chronological");
    previous = now;
    if (ids.has(trade.tradeId)) {
      throw new VolumeImbalanceBarsValidationError("tradeId must be unique after corrections are resolved");
    }
    ids.add(trade.tradeId);
    finite(trade.price, "price", true);
    finite(trade.volume, "volume", true);
    if (symbol === null) {
      symbol = trade.symbol;
      currency = trade.currency;
    } else if (trade.symbol !== symbol || trade.currency !== currency) {
      throw new VolumeImbalanceBarsValidationError("one symbol and one currency are allowed per call");
    }
    if (currentSession === null) currentSession = trade.session;
    else if (trade.session !== currentSession) {
      closedSessions.add(currentSession);
      if (closedSessions.has(trade.session)) {
        throw new VolumeImbalanceBarsValidationError("a session may not reappear after a later session begins");
      }
      currentSession = trade.session;
    }
  }
}

export function constructBars(trades: Trade[], config: Config): Bar[] {
  const cfg = normalized(config);
  validateTrades(trades);
  if (!trades.length) return [];

  const result: Bar[] = [];
  let current: Trade[] = [];
  let session: string | null = null;
  let previousPrice: number | null = null;
  let tickSign = cfg.initialSign;
  let expectedTicks = cfg.initialExpectedTicks;
  let expectedSigned = cfg.initialExpectedSigned;
  let signedVolume = 0;
  let frozenThreshold = 0;
  let frozenExpectedTicks = 0;
  let frozenExpectedSigned = 0;

  const beginBar = (): void => {
    // Snapshot the expectations at bar open so the bar can be audited against
    // exactly the threshold it was judged by.
    current = [];
    signedVolume = 0;
    frozenExpectedTicks = expectedTicks;
    frozenExpectedSigned = expectedSigned;
    frozenThreshold = Math.max(cfg.floor, cfg.scale * frozenExpectedTicks * Math.abs(frozenExpectedSigned));
  };

  const emit = (reason: CloseReason): void => {
    if (!current.length) return;
    const prices = current.map((t) => t.price);
    const volumes = current.map((t) => t.volume);
    const thresholdMet = Math.abs(signedVolume) >= frozenThreshold;
    result.push({
      barIndex: result.length,
      session: current[0].session,
      startTime: current[0].timestamp,
      endTime: current.at(-1)!.timestamp,
      open: rounded(prices[0]),
      high: rounded(Math.max(...prices)),
      low: rounded(Math.min(...prices)),
      close: rounded(prices.at(-1)!),
      volume: rounded(volumes.reduce((a, b) => a + b, 0)),
      dollarValue: rounded(current.reduce((a, t) => a + t.price * t.volume, 0)),
      tickCount: current.length,
      firstTradeId: current[0].tradeId,
      lastTradeId: current.at(-1)!.tradeId,
      closeReason: reason,
      isComplete: reason === "threshold",
      signedVolume: rounded(signedVolume),
      thresholdShares: rounded(frozenThreshold),
      expectedTicksBefore: rounded(frozenExpectedTicks),
      expectedSignedVolumeBefore: rounded(frozenExpectedSigned),
      overshootShares: rounded(Math.max(Math.abs(signedVolume) - frozenThreshold, 0)),
      thresholdMet,
    });
    // Only a complete bar is evidence about the process.
    if (reason === "threshold") {
      const observedTicks = current.length;
      const observedSigned = signedVolume / observedTicks;
      expectedTicks = (1 - cfg.alphaTicks) * expectedTicks + cfg.alphaTicks * observedTicks;
      expectedSigned = (1 - cfg.alphaSigned) * expectedSigned + cfg.alphaSigned * observedSigned;
    }
    beginBar();
  };

  beginBar();
  for (const trade of trades) {
    if (session !== null && trade.session !== session) {
      if (current.length && cfg.closePartial) emit("session_end");
      else beginBar();
      expectedTicks = cfg.initialExpectedTicks;
      expectedSigned = cfg.initialExpectedSigned;
      previousPrice = null;
      tickSign = cfg.initialSign;
      beginBar();
    }
    session = trade.session;
    if (previousPrice !== null) {
      // A flat trade deliberately carries the preceding sign.
      tickSign = trade.price > previousPrice ? 1 : trade.price < previousPrice ? -1 : tickSign;
    }
    previousPrice = trade.price;
    current.push(trade);
    signedVolume += tickSign * trade.volume;
    if (Math.abs(signedVolume) >= frozenThreshold) emit("threshold");
  }
  if (current.length && cfg.closePartial) emit("stream_end");
  return result;
}
