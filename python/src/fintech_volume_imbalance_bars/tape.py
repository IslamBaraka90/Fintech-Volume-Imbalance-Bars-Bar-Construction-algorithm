"""Trade-tape loader for Volume-Imbalance Bars.

Imbalance bars need each execution's **price** (to assign a tick sign) and its
**volume** (to weight that sign), so they are built from a trade tape. Yahoo
Finance does not expose tick data — only pre-aggregated bars, where the per-trade
signs are already lost — so there is no live Yahoo source for this algorithm.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

__all__ = ["load_trades"]

_TRADE_FIELDS = ("tradeId", "timestamp", "session", "symbol", "currency")


def load_trades(csv_path: str | Path) -> list[dict[str, Any]]:
    """Read a trade tape from CSV into trade dicts for :func:`construct_bars`.

    Expected columns: ``tradeId,timestamp,session,symbol,price,volume,currency``.
    ``price`` / ``volume`` become floats.
    """
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    trades: list[dict[str, Any]] = []
    for row in rows:
        trade: dict[str, Any] = {field: row[field] for field in _TRADE_FIELDS if field in row}
        trade["price"] = float(row["price"])
        trade["volume"] = float(row["volume"])
        trades.append(trade)
    return trades
