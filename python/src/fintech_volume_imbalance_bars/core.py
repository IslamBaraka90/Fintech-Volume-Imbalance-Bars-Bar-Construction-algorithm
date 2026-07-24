"""Causal Volume-Imbalance Bars under an explicit, disclosed convention.

Faithful to the reference algorithm published at The Fintech Builder (topic
``D01-F01-A06``). Volume-imbalance bars extend the tick-imbalance idea by
weighting each signed trade by **how much size** it carried:

    signedVolume = sum over trades of (tickSign_i * volume_i)
    close the bar when abs(signedVolume) >= threshold

so one 10,000-share sweep counts far more than ten 10-share prints in the same
direction. The tick rule is unchanged: uptick ``+1``, downtick ``-1``, and a flat
trade carries the **preceding** sign (a session's first trade uses
``initialTickSign``).

The threshold adapts through two EWMAs, updated only after a **complete**
(threshold-closed) bar:

    E[ticks]        <- (1 - alphaTicks)        * E[ticks]        + alphaTicks        * observedTicks
    E[signedVolume] <- (1 - alphaSignedVolume) * E[signedVolume] + alphaSignedVolume * (signedVolume / observedTicks)

    threshold = max(thresholdFloorShares, thresholdScale * E[ticks] * abs(E[signedVolume]))

**Frozen threshold.** The threshold and both expectations are snapshotted when a
bar *opens*, and every emitted bar reports the snapshot it was actually judged
against (``thresholdShares``, ``expectedTicksBefore``,
``expectedSignedVolumeBefore``) alongside its ``overshootShares``. A bar is
therefore fully auditable after the fact — you never have to re-derive which
threshold applied.

The caller supplies an already corrected, deduplicated, eligible, ordered trade
stream. Equal timestamps retain input order. A trade is never split.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

__all__ = ["VolumeImbalanceBarsValidationError", "REQUIRED_TRADE_FIELDS", "construct_bars"]

REQUIRED_TRADE_FIELDS = ("tradeId", "timestamp", "session", "symbol", "price", "volume", "currency")


class VolumeImbalanceBarsValidationError(ValueError):
    """Raised when trades or config violate the Volume-Imbalance Bars contract."""


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise VolumeImbalanceBarsValidationError("timestamp must be an ISO-8601 UTC string ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise VolumeImbalanceBarsValidationError("timestamp must be valid ISO-8601") from exc
    return parsed.astimezone(timezone.utc)


def _finite_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VolumeImbalanceBarsValidationError(f"{name} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise VolumeImbalanceBarsValidationError(f"{name} must be a finite number")
    if positive and number <= 0:
        raise VolumeImbalanceBarsValidationError(f"{name} must be positive")
    return number


def _config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize config, applying the package defaults for anything omitted."""
    if not isinstance(config, dict):
        raise VolumeImbalanceBarsValidationError("config must be an object")
    close_partial = config.get("closePartial", True)
    if not isinstance(close_partial, bool):
        raise VolumeImbalanceBarsValidationError("closePartial must be boolean")
    initial_sign = config.get("initialTickSign", 1)
    if isinstance(initial_sign, bool) or initial_sign not in (-1, 1):
        raise VolumeImbalanceBarsValidationError("initialTickSign must be -1 or 1")
    alpha_ticks = _finite_number(config.get("alphaTicks", 0.2), "alphaTicks", positive=True)
    alpha_signed = _finite_number(
        config.get("alphaSignedVolume", 0.2), "alphaSignedVolume", positive=True
    )
    if alpha_ticks > 1 or alpha_signed > 1:
        raise VolumeImbalanceBarsValidationError("EMA coefficients must be in (0, 1]")
    return {
        "close_partial": close_partial,
        "initial_sign": int(initial_sign),
        "initial_expected_ticks": _finite_number(
            config.get("initialExpectedTicks", 16), "initialExpectedTicks", positive=True
        ),
        # Signed volume is in shares and may legitimately be negative.
        "initial_expected_signed": _finite_number(
            config.get("initialExpectedSignedVolume", 35), "initialExpectedSignedVolume"
        ),
        "alpha_ticks": alpha_ticks,
        "alpha_signed": alpha_signed,
        "floor": _finite_number(
            config.get("thresholdFloorShares", 300), "thresholdFloorShares", positive=True
        ),
        "scale": _finite_number(config.get("thresholdScale", 1), "thresholdScale", positive=True),
    }


def _validate_trades(trades: list[dict[str, Any]]) -> None:
    if not isinstance(trades, list):
        raise VolumeImbalanceBarsValidationError("trades must be a list")
    previous_time: datetime | None = None
    ids: set[str] = set()
    closed_sessions: set[str] = set()
    current_session: str | None = None
    symbol: str | None = None
    currency: str | None = None
    for trade in trades:
        if not isinstance(trade, dict) or any(field not in trade for field in REQUIRED_TRADE_FIELDS):
            raise VolumeImbalanceBarsValidationError("trade is missing a required field")
        for field in ("tradeId", "session", "symbol", "currency"):
            if not isinstance(trade[field], str) or not trade[field]:
                raise VolumeImbalanceBarsValidationError(f"{field} must be a non-empty string")
        current_time = _timestamp(trade["timestamp"])
        if previous_time is not None and current_time < previous_time:
            raise VolumeImbalanceBarsValidationError("trades must be globally chronological")
        previous_time = current_time
        if trade["tradeId"] in ids:
            raise VolumeImbalanceBarsValidationError("tradeId must be unique after corrections are resolved")
        ids.add(trade["tradeId"])
        _finite_number(trade["price"], "price", positive=True)
        _finite_number(trade["volume"], "volume", positive=True)
        if symbol is None:
            symbol, currency = trade["symbol"], trade["currency"]
        elif trade["symbol"] != symbol or trade["currency"] != currency:
            raise VolumeImbalanceBarsValidationError("one symbol and one currency are allowed per call")
        if current_session is None:
            current_session = trade["session"]
        elif trade["session"] != current_session:
            closed_sessions.add(current_session)
            if trade["session"] in closed_sessions:
                raise VolumeImbalanceBarsValidationError(
                    "a session may not reappear after a later session begins"
                )
            current_session = trade["session"]


def _round(value: float) -> float:
    return round(value + 0.0, 8)


def construct_bars(trades: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic session-local volume-imbalance bars."""
    cfg = _config(config)
    _validate_trades(trades)
    if not trades:
        return []

    result: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    session: str | None = None
    previous_price: float | None = None
    tick_sign = cfg["initial_sign"]
    expected_ticks = cfg["initial_expected_ticks"]
    expected_signed = cfg["initial_expected_signed"]
    signed_volume = 0.0
    frozen_threshold = 0.0
    frozen_expected_ticks = 0.0
    frozen_expected_signed = 0.0

    def begin_bar() -> None:
        # Snapshot the expectations at bar open so the bar can be audited against
        # exactly the threshold it was judged by.
        nonlocal current, signed_volume, frozen_threshold
        nonlocal frozen_expected_ticks, frozen_expected_signed
        current = []
        signed_volume = 0.0
        frozen_expected_ticks = expected_ticks
        frozen_expected_signed = expected_signed
        raw = frozen_expected_ticks * abs(frozen_expected_signed)
        frozen_threshold = max(cfg["floor"], cfg["scale"] * raw)

    def emit(reason: str) -> None:
        nonlocal expected_ticks, expected_signed
        if not current:
            return
        prices = [float(t["price"]) for t in current]
        volumes = [float(t["volume"]) for t in current]
        threshold_met = abs(signed_volume) >= frozen_threshold
        result.append(
            {
                "barIndex": len(result),
                "session": current[0]["session"],
                "startTime": current[0]["timestamp"],
                "endTime": current[-1]["timestamp"],
                "open": _round(prices[0]),
                "high": _round(max(prices)),
                "low": _round(min(prices)),
                "close": _round(prices[-1]),
                "volume": _round(sum(volumes)),
                "dollarValue": _round(sum(p * v for p, v in zip(prices, volumes))),
                "tickCount": len(current),
                "firstTradeId": current[0]["tradeId"],
                "lastTradeId": current[-1]["tradeId"],
                "closeReason": reason,
                "isComplete": reason == "threshold",
                "signedVolume": _round(signed_volume),
                "thresholdShares": _round(frozen_threshold),
                "expectedTicksBefore": _round(frozen_expected_ticks),
                "expectedSignedVolumeBefore": _round(frozen_expected_signed),
                "overshootShares": _round(max(abs(signed_volume) - frozen_threshold, 0.0)),
                "thresholdMet": threshold_met,
            }
        )
        # Only a complete bar is evidence about the process.
        if reason == "threshold":
            observed_ticks = len(current)
            observed_signed = signed_volume / observed_ticks
            expected_ticks = (
                (1 - cfg["alpha_ticks"]) * expected_ticks + cfg["alpha_ticks"] * observed_ticks
            )
            expected_signed = (
                (1 - cfg["alpha_signed"]) * expected_signed + cfg["alpha_signed"] * observed_signed
            )
        begin_bar()

    begin_bar()
    for trade in trades:
        if session is not None and trade["session"] != session:
            if current and cfg["close_partial"]:
                emit("session_end")
            else:
                begin_bar()
            expected_ticks = cfg["initial_expected_ticks"]
            expected_signed = cfg["initial_expected_signed"]
            previous_price = None
            tick_sign = cfg["initial_sign"]
            begin_bar()
        session = trade["session"]

        price = float(trade["price"])
        if previous_price is not None:
            if price > previous_price:
                tick_sign = 1
            elif price < previous_price:
                tick_sign = -1
            # A flat trade deliberately carries the preceding sign.
        previous_price = price
        current.append(trade)
        signed_volume += tick_sign * float(trade["volume"])
        if abs(signed_volume) >= frozen_threshold:
            emit("threshold")

    if current and cfg["close_partial"]:
        emit("stream_end")
    return result
