/**
 * Fintech Volume-Imbalance Bars — size-weighted information-driven bars.
 *
 * Companion article (canonical): https://thefintechbuilder.com/market-data-engineering/bar-construction/volume-imbalance-bars/
 * Catalog topic id: D01-F01-A06 (Domain D01 — Market Data Engineering / Family D01-F01 — Bar Construction)
 */

export {
  VolumeImbalanceBarsValidationError,
  constructBars,
  type Trade,
  type Config,
  type Bar,
  type CloseReason,
} from "./bars.ts";
export { StreamingVolumeImbalanceBarBuilder } from "./streaming.ts";
export { loadTrades } from "./tape.ts";
