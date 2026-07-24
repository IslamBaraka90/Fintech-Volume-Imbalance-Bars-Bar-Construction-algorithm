/**
 * Stateful, streaming Volume-Imbalance-Bar builder.
 *
 * `./bars`'s `constructBars` aggregates a whole tape at once. A live tape needs a
 * builder that accepts one trade at a time and emits a bar the instant
 * `abs(signedVolume) >= threshold`.
 *
 * Because this bar type is *adaptive*, the builder also **exposes its state**:
 * `signedVolume`, `threshold` (the frozen snapshot the open bar is judged
 * against), `expectedTicks`, `expectedSignedVolume`, and `tickSign`.
 */

import {
  VolumeImbalanceBarsValidationError,
  finite,
  normalized,
  rounded,
  timestampMs,
  type Bar,
  type CloseReason,
  type Config,
  type NormalizedConfig,
  type Trade,
} from "./bars.ts";

const REQUIRED_TRADE_FIELDS = [
  "tradeId", "timestamp", "session", "symbol", "price", "volume", "currency",
] as const;

export class StreamingVolumeImbalanceBarBuilder {
  private readonly cfg: NormalizedConfig;

  // validation state
  private ids = new Set<string>();
  private closedSessions = new Set<string>();
  private validationSession: string | null = null;
  private previousTime = -Infinity;
  private symbol: string | null = null;
  private currency: string | null = null;

  // adaptive + aggregation state
  private current: Trade[] = [];
  private session: string | null = null;
  private previousPrice: number | null = null;
  private _tickSign: number;
  private _expectedTicks: number;
  private _expectedSigned: number;
  private _signedVolume = 0;
  private frozenThreshold = 0;
  private frozenExpectedTicks = 0;
  private frozenExpectedSigned = 0;
  private barCount = 0;
  private flushed = false;

  constructor(config: Config) {
    this.cfg = normalized(config);
    this._tickSign = this.cfg.initialSign;
    this._expectedTicks = this.cfg.initialExpectedTicks;
    this._expectedSigned = this.cfg.initialExpectedSigned;
    this.beginBar();
  }

  /** Signed share imbalance accumulated in the open bar. */
  get signedVolume(): number {
    return this._signedVolume;
  }

  /** Frozen threshold (shares) the open bar is being judged against. */
  get threshold(): number {
    return this.frozenThreshold;
  }

  /** Live EWMA estimate of ticks per bar (feeds the *next* bar's threshold). */
  get expectedTicks(): number {
    return this._expectedTicks;
  }

  /** Live EWMA estimate of signed volume per tick, in shares. */
  get expectedSignedVolume(): number {
    return this._expectedSigned;
  }

  /** Sign the next flat trade would carry (+1 or -1). */
  get tickSign(): number {
    return this._tickSign;
  }

  /** Trades currently held in the open bar. */
  get tickCount(): number {
    return this.current.length;
  }

  private beginBar(): void {
    this.current = [];
    this._signedVolume = 0;
    this.frozenExpectedTicks = this._expectedTicks;
    this.frozenExpectedSigned = this._expectedSigned;
    this.frozenThreshold = Math.max(
      this.cfg.floor,
      this.cfg.scale * this.frozenExpectedTicks * Math.abs(this.frozenExpectedSigned),
    );
  }

  private validateTrade(raw: unknown): Trade {
    if (!raw || typeof raw !== "object" || REQUIRED_TRADE_FIELDS.some((f) => !(f in (raw as object)))) {
      throw new VolumeImbalanceBarsValidationError("trade is missing a required field");
    }
    const trade = raw as Trade;
    for (const key of ["tradeId", "timestamp", "session", "symbol", "currency"] as const) {
      if (typeof trade[key] !== "string" || !trade[key]) {
        throw new VolumeImbalanceBarsValidationError(`${key} must be a non-empty string`);
      }
    }
    const now = timestampMs(trade.timestamp);
    if (now < this.previousTime) {
      throw new VolumeImbalanceBarsValidationError("trades must be globally chronological");
    }
    this.previousTime = now;
    if (this.ids.has(trade.tradeId)) {
      throw new VolumeImbalanceBarsValidationError("tradeId must be unique after corrections are resolved");
    }
    this.ids.add(trade.tradeId);
    finite(trade.price, "price", true);
    finite(trade.volume, "volume", true);
    if (this.symbol === null) {
      this.symbol = trade.symbol;
      this.currency = trade.currency;
    } else if (trade.symbol !== this.symbol || trade.currency !== this.currency) {
      throw new VolumeImbalanceBarsValidationError("one symbol and one currency are allowed per call");
    }
    if (this.validationSession === null) this.validationSession = trade.session;
    else if (trade.session !== this.validationSession) {
      this.closedSessions.add(this.validationSession);
      if (this.closedSessions.has(trade.session)) {
        throw new VolumeImbalanceBarsValidationError("a session may not reappear after a later session begins");
      }
      this.validationSession = trade.session;
    }
    return trade;
  }

  private emit(reason: CloseReason): Bar | null {
    if (!this.current.length) return null;
    const prices = this.current.map((t) => t.price);
    const volumes = this.current.map((t) => t.volume);
    const thresholdMet = Math.abs(this._signedVolume) >= this.frozenThreshold;
    const bar: Bar = {
      barIndex: this.barCount,
      session: this.current[0].session,
      startTime: this.current[0].timestamp,
      endTime: this.current.at(-1)!.timestamp,
      open: rounded(prices[0]),
      high: rounded(Math.max(...prices)),
      low: rounded(Math.min(...prices)),
      close: rounded(prices.at(-1)!),
      volume: rounded(volumes.reduce((a, b) => a + b, 0)),
      dollarValue: rounded(this.current.reduce((a, t) => a + t.price * t.volume, 0)),
      tickCount: this.current.length,
      firstTradeId: this.current[0].tradeId,
      lastTradeId: this.current.at(-1)!.tradeId,
      closeReason: reason,
      isComplete: reason === "threshold",
      signedVolume: rounded(this._signedVolume),
      thresholdShares: rounded(this.frozenThreshold),
      expectedTicksBefore: rounded(this.frozenExpectedTicks),
      expectedSignedVolumeBefore: rounded(this.frozenExpectedSigned),
      overshootShares: rounded(Math.max(Math.abs(this._signedVolume) - this.frozenThreshold, 0)),
      thresholdMet,
    };
    this.barCount += 1;
    if (reason === "threshold") {
      const observedTicks = this.current.length;
      const observedSigned = this._signedVolume / observedTicks;
      this._expectedTicks = (1 - this.cfg.alphaTicks) * this._expectedTicks + this.cfg.alphaTicks * observedTicks;
      this._expectedSigned = (1 - this.cfg.alphaSigned) * this._expectedSigned + this.cfg.alphaSigned * observedSigned;
    }
    this.beginBar();
    return bar;
  }

  /** Accept one trade and return any bars it closes (zero or one). */
  push(rawTrade: Trade): Bar[] {
    if (this.flushed) throw new VolumeImbalanceBarsValidationError("cannot push after flush()");
    const trade = this.validateTrade(rawTrade);
    const emitted: Bar[] = [];

    if (this.session !== null && trade.session !== this.session) {
      if (this.current.length && this.cfg.closePartial) {
        const bar = this.emit("session_end");
        if (bar) emitted.push(bar);
      } else {
        this.beginBar();
      }
      this._expectedTicks = this.cfg.initialExpectedTicks;
      this._expectedSigned = this.cfg.initialExpectedSigned;
      this.previousPrice = null;
      this._tickSign = this.cfg.initialSign;
      this.beginBar();
    }
    this.session = trade.session;

    if (this.previousPrice !== null) {
      this._tickSign =
        trade.price > this.previousPrice ? 1 : trade.price < this.previousPrice ? -1 : this._tickSign;
    }
    this.previousPrice = trade.price;
    this.current.push(trade);
    this._signedVolume += this._tickSign * trade.volume;

    if (Math.abs(this._signedVolume) >= this.frozenThreshold) {
      const bar = this.emit("threshold");
      if (bar) emitted.push(bar);
    }
    return emitted;
  }

  /** Feed an array of trades, returning every bar closed along the way. */
  pushMany(trades: readonly Trade[]): Bar[] {
    const emitted: Bar[] = [];
    for (const trade of trades) emitted.push(...this.push(trade));
    return emitted;
  }

  /** Close the final partial bar (if `closePartial`) and end the stream. */
  flush(): Bar[] {
    this.flushed = true;
    if (this.current.length && this.cfg.closePartial) {
      const bar = this.emit("stream_end");
      return bar ? [bar] : [];
    }
    return [];
  }
}
