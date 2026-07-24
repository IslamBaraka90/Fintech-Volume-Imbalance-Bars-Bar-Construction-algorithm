"""Fintech Volume-Imbalance Bars — size-weighted information-driven bars.

A small, well-specified, cross-language reference implementation of
Volume-Imbalance Bars: a bar closes when the *size-weighted* signed order flow
inside it exceeds a threshold that adapts, via EWMA, to recent bar length and
signed volume. Every bar reports the frozen threshold it was judged against.

Companion article (canonical): https://thefintechbuilder.com/market-data-engineering/bar-construction/volume-imbalance-bars/
Catalog topic id: D01-F01-A06  (Domain D01 — Market Data Engineering / Family D01-F01 — Bar Construction)
"""

from __future__ import annotations

from .core import VolumeImbalanceBarsValidationError, construct_bars
from .streaming import StreamingVolumeImbalanceBarBuilder
from .tape import load_trades

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "VolumeImbalanceBarsValidationError",
    "construct_bars",
    "StreamingVolumeImbalanceBarBuilder",
    "load_trades",
]
