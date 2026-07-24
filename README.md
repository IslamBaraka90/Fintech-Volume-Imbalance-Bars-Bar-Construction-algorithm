# Fintech Volume-Imbalance Bars — Bar Construction Algorithm

> A canonical, well-specified, **cross-language (Python + TypeScript)** reference
> implementation of **Volume-Imbalance Bars** — information-driven bars that close
> on **size-weighted** signed order flow against an **EWMA-adaptive threshold**,
> with every bar reporting the **frozen threshold it was judged against**.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="TypeScript" src="https://img.shields.io/badge/typescript-5.7%2B-3178c6">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Tests" src="https://img.shields.io/badge/tests-36%20py%20%2F%2030%20ts-brightgreen">
</p>

**📖 Full article (canonical):** **[Volume-Imbalance Bars — The Fintech Builder](https://thefintechbuilder.com/market-data-engineering/bar-construction/volume-imbalance-bars/)**

This repository is the runnable, production-oriented companion to that article.
The article teaches the concept; this repo is the code you install and build on.

🧭 **Browse all algorithms:** [Awesome FinTech Algorithms](https://github.com/IslamBaraka90/Fintech-Algorithms-Awesome) — the full index of the library.
🗂️ **This algorithm's domain:** [Market Data Engineering](https://thefintechbuilder.com/domains/market-data-engineering/) › **Bar Construction**
↔️ **Sibling bar types:** [Time](https://github.com/IslamBaraka90/Fintech-Time-Bars-Bar-Construction-algorithm) · [Tick](https://github.com/IslamBaraka90/Fintech-Tick-Bars-Bar-Construction-algorithm) · [Volume](https://github.com/IslamBaraka90/Fintech-Volume-Bars-Bar-Construction-algorithm) · [Dollar](https://github.com/IslamBaraka90/Fintech-Dollar-Bars-Bar-Construction-algorithm) · [Tick-Imbalance](https://github.com/IslamBaraka90/Fintech-Tick-Imbalance-Bars-Bar-Construction-algorithm).

| | |
|---|---|
| **Catalog topic** | `D01-F01-A06` |
| **Domain** | D01 — Market Data Engineering |
| **Family** | D01-F01 — Bar Construction |
| **Difficulty** | 4 / 5 |
| **Languages** | Python, TypeScript |

---

## Table of contents

- [What are Volume-Imbalance Bars?](#what-are-volume-imbalance-bars)
- [Why size weighting changes the answer](#why-size-weighting-changes-the-answer)
- [The frozen threshold](#the-frozen-threshold)
- [Why this implementation](#why-this-implementation)
- [Install](#install)
- [Quickstart](#quickstart)
- [Streaming, with observable state](#streaming-with-observable-state)
- [Loading a trade tape](#loading-a-trade-tape)
- [Config & bar shapes](#config--bar-shapes)
- [Worked example (exact)](#worked-example-exact)
- [API reference](#api-reference)
- [Edge cases & limitations](#edge-cases--limitations)
- [Testing](#testing)
- [Related algorithms](#related-algorithms)
- [License](#license)

---

## What are Volume-Imbalance Bars?

[Tick-imbalance bars](https://github.com/IslamBaraka90/Fintech-Tick-Imbalance-Bars-Bar-Construction-algorithm)
count each trade as `±1`. **Volume-imbalance bars** weight each signed trade by
**how much size it carried**:

```
signedVolume = Σ (tickSign_i × volume_i)
close the bar when  abs(signedVolume) >= threshold
```

The tick rule is unchanged — uptick `+1`, downtick `-1`, and a **flat trade
carries the preceding sign** (a session's first trade uses `initialTickSign`).

## Why size weighting changes the answer

One 10,000-share sweep and ten 10-share prints are *identical* to a tick-imbalance
bar and wildly different here. Because institutional intent shows up in **size**,
weighting by volume makes the bar boundary track pressure that actually moves the
book rather than message count — which is why volume-imbalance bars often
separate informed flow better than their tick-only cousin.

The test suite pins this down directly: with a 200-share floor, a single
500-share print closes a bar immediately, while a single 5-share print does not.

## The frozen threshold

The threshold adapts through two EWMAs, updated **only after a complete
(threshold-closed) bar**:

```
E[ticks]        ← (1 − alphaTicks)        · E[ticks]        + alphaTicks        · observedTicks
E[signedVolume] ← (1 − alphaSignedVolume) · E[signedVolume] + alphaSignedVolume · (signedVolume / observedTicks)

threshold = max(thresholdFloorShares,  thresholdScale · E[ticks] · abs(E[signedVolume]))
```

The important design choice: **the threshold is snapshotted when a bar opens**,
and each emitted bar reports that snapshot — `thresholdShares`,
`expectedTicksBefore`, `expectedSignedVolumeBefore` — plus its
`overshootShares` and a `thresholdMet` flag. You never have to re-derive which
threshold applied to a historical bar; the bar carries its own audit trail.

Two guards, same as the tick-imbalance sibling:

- **Partial bars never learn.** `session_end` / `stream_end` bars are artifacts of
  where the tape stopped (`isComplete: false`), so they don't move expectations.
- **A floor.** `thresholdFloorShares` stops the threshold collapsing toward zero
  when the estimated signed volume drifts to ~0.

## Why this implementation

- **Faithful, disclosed convention** with sensible **defaults** — every config key
  is optional (`16` ticks, `35` shares, floor `300`, alphas `0.2`).
- **Self-auditing bars** — the frozen snapshot travels with each bar.
- **Observable adaptation** — the streaming builder exposes `signed_volume`,
  `threshold`, `expected_ticks`, `expected_signed_volume`, and `tick_sign`.
- **Session-correct** — a boundary resets previous price, tick sign, *and* both
  expectations back to their seeds.
- **Cross-language parity** — both suites walk the documented per-trade trace and
  assert the same numbers, including `postFirstClose` (`E[ticks] = 4.5`,
  `E[signed] = 28.958…`, next threshold `130.3125`).

## Install

**Python**

```bash
pip install fintech-volume-imbalance-bars
```

**TypeScript / JavaScript (Node ≥ 20)**

```bash
npm install fintech-volume-imbalance-bars
```

## Quickstart

**Python**

```python
from fintech_volume_imbalance_bars import construct_bars

bars = construct_bars(trades, {"thresholdFloorShares": 5000})   # other keys default
```

**TypeScript**

```ts
import { constructBars } from "fintech-volume-imbalance-bars";

const bars = constructBars(trades, { thresholdFloorShares: 5000 });
```

## Streaming, with observable state

```python
from fintech_volume_imbalance_bars import StreamingVolumeImbalanceBarBuilder

builder = StreamingVolumeImbalanceBarBuilder(config)
for trade in tape:
    for bar in builder.push(trade):
        publish(bar)
    monitor(builder.signed_volume, builder.threshold, builder.expected_ticks)
for bar in builder.flush():
    publish(bar)
```

The bundled example prints the imbalance building and the threshold adapting:

```
seed: E[ticks]=4 E[signed]=50 threshold=200
  W01: signedVolume=60 (threshold 200)
  W02: signedVolume=100 (threshold 200)
  ...
  closed on W06: |-205| >= 200 -> new E[ticks]=4.5000 threshold=130.3125
```

## Loading a trade tape

Volume-imbalance bars need each execution's **price** (to sign the tick) and its
**volume** (to weight it), so they are built from a trade tape. Yahoo Finance does
not expose tick data — only pre-aggregated bars, where the per-trade signs are
already lost — so there is no live Yahoo source for this algorithm.

```python
from fintech_volume_imbalance_bars import construct_bars, load_trades

trades = load_trades("tape.csv")   # tradeId,timestamp,session,symbol,price,volume,currency
bars = construct_bars(trades, config)
```

> **Data note:** the committed fixtures are synthetic and prove the package
> mechanics only. They are not a market episode or a predictive result.

## Config & bar shapes

**Config** (every key optional — defaults shown):

| Key | Default | Meaning |
|---|--:|---|
| `closePartial` | `true` | emit trailing partial bars |
| `initialTickSign` | `1` | sign for a session's first trade (`-1` or `1`) |
| `initialExpectedTicks` | `16` | positive seed for `E[ticks]` |
| `initialExpectedSignedVolume` | `35` | seed for `E[signedVolume]` — **may be negative** (it's in shares) |
| `alphaTicks`, `alphaSignedVolume` | `0.2` | EWMA weights in `(0, 1]` |
| `thresholdFloorShares` | `300` | positive lower bound (shares) |
| `thresholdScale` | `1` | positive scale on the expectation product |

**Bar:** the usual OHLCV/audit fields plus `signedVolume`, `thresholdShares`,
`expectedTicksBefore`, `expectedSignedVolumeBefore`, `overshootShares`,
`thresholdMet`, and `isComplete`.

## Worked example (exact)

Seeds `E[ticks] = 4`, `E[signed] = 50`, floor `120`, scale `1` ⇒ opening threshold
`max(120, 4 · 50) = 200` shares.

| # | price | vol | sign | signed | cumulative | decision |
|---|--:|--:|--:|--:|--:|---|
| W01 | 100.00 | 60 | +1 (seed) | +60 | 60 | continue |
| W02 | 100.00 | 40 | +1 (flat carries) | +40 | 100 | continue |
| W03 | 99.99 | 70 | −1 | −70 | 30 | continue |
| W04 | 99.98 | 90 | −1 | −90 | −60 | continue |
| W05 | 99.98 | 50 | −1 (flat carries) | −50 | −110 | continue |
| W06 | 99.97 | 95 | −1 | −95 | **−205** | **close** (205 ≥ 200, overshoot 5) |

Post-close: `E[ticks] = 0.75·4 + 0.25·6 = 4.5`,
`E[signed] = 0.75·50 + 0.25·(−205/6) = 28.958…`, so the next threshold is
`max(120, 4.5 · 28.958…) = 130.3125`. W07 (+80) and W08 (+55) reach 135 and close
bar 1 with overshoot `4.6875`. Every one of these numbers is asserted by **both**
language test suites — including that W01/W02 share a timestamp and retain input
order.

## API reference

| Purpose | Python | TypeScript |
|---|---|---|
| Batch construction | `construct_bars(trades, config)` | `constructBars(trades, config)` |
| Streaming builder | `StreamingVolumeImbalanceBarBuilder(config)` | `new StreamingVolumeImbalanceBarBuilder(config)` |
| Observable state | `.signed_volume`, `.threshold`, `.expected_ticks`, `.expected_signed_volume`, `.tick_sign` | `.signedVolume`, `.threshold`, `.expectedTicks`, `.expectedSignedVolume`, `.tickSign` |
| Load a trade tape | `load_trades(csv)` | `loadTrades(path)` |
| Errors | `VolumeImbalanceBarsValidationError` | `VolumeImbalanceBarsValidationError` |

## Edge cases & limitations

- **Seed sensitivity:** early bars are dominated by your seeds; treat them as burn-in.
- **Floor matters:** without `thresholdFloorShares`, an `E[signedVolume]` near zero
  drives the threshold to zero and emits a bar per trade.
- **Signed-volume seed may be negative** — it is a share quantity, not a ratio; the
  threshold uses its absolute value.
- **Not a predictor:** imbalance describes realized flow, not future direction.
- **Sessions reset everything** — previous price, tick sign, and both expectations.
- **Equal timestamps retain input order** (no `sequence` field required here).

## Testing

**Python** (36 tests)

```bash
cd python && pip install -e ".[dev]" && pytest
```

**TypeScript** (30 tests, zero runtime dependencies)

```bash
cd typescript && npm install && npm test && npm run build
```

## Related algorithms

- `D01-F01-A05` — [Tick-Imbalance Bars](https://github.com/IslamBaraka90/Fintech-Tick-Imbalance-Bars-Bar-Construction-algorithm) (the unweighted sibling)
- `D01-F01-A01…A04` — [Time](https://github.com/IslamBaraka90/Fintech-Time-Bars-Bar-Construction-algorithm) · [Tick](https://github.com/IslamBaraka90/Fintech-Tick-Bars-Bar-Construction-algorithm) · [Volume](https://github.com/IslamBaraka90/Fintech-Volume-Bars-Bar-Construction-algorithm) · [Dollar](https://github.com/IslamBaraka90/Fintech-Dollar-Bars-Bar-Construction-algorithm)
- `D01-F01-A07` — Tick-Run Bars
- `D07-F01-A02` — [EMA](https://github.com/IslamBaraka90/Fintech-EMA-Exponential-Moving-Average-algorithm) (the smoothing behind the adaptive threshold)

Full index: **[Awesome FinTech Algorithms](https://github.com/IslamBaraka90/Fintech-Algorithms-Awesome)**.

## License

[MIT](./LICENSE) © The Fintech Builder. Part of the
[100 FinTech Algorithms](https://thefintechbuilder.com) library.
