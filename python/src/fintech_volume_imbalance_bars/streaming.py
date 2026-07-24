"""Stateful, streaming Volume-Imbalance-Bar builder.

:func:`~fintech_volume_imbalance_bars.core.construct_bars` aggregates a whole
tape at once. A live tape needs a builder that accepts one trade at a time and
emits a bar the instant ``abs(signedVolume) >= threshold``.

``StreamingVolumeImbalanceBarBuilder`` is that object, and — because this bar
type is *adaptive* — it also **exposes its state** while it runs:
:attr:`signed_volume`, :attr:`threshold` (the frozen snapshot the open bar is
being judged against), :attr:`expected_ticks`, :attr:`expected_signed_volume`,
and :attr:`tick_sign`. Watching those is how you tell a mis-seeded threshold from
a genuinely balanced tape.

Feed trades with :meth:`push` (returns any bars closed by that trade — zero or
one); call :meth:`flush` at end of stream. Bars are byte-identical to the batch
kernel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .core import (
    REQUIRED_TRADE_FIELDS,
    VolumeImbalanceBarsValidationError,
    _config,
    _finite_number,
    _round,
    _timestamp,
)

__all__ = ["StreamingVolumeImbalanceBarBuilder"]


class StreamingVolumeImbalanceBarBuilder:
    """Incremental Volume-Imbalance-Bar builder with observable adaptive state.

    Examples
    --------
    >>> builder = StreamingVolumeImbalanceBarBuilder(config)   # doctest: +SKIP
    >>> closed = builder.push_many(tape) + builder.flush()     # doctest: +SKIP
    >>> builder.signed_volume, builder.threshold               # doctest: +SKIP
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = _config(config)

        # validation state
        self._ids: set[str] = set()
        self._closed_sessions: set[str] = set()
        self._validation_session: str | None = None
        self._previous_time: datetime | None = None
        self._symbol: str | None = None
        self._currency: str | None = None

        # adaptive + aggregation state
        self._current: list[dict[str, Any]] = []
        self._session: str | None = None
        self._previous_price: float | None = None
        self._tick_sign = self._cfg["initial_sign"]
        self._expected_ticks = self._cfg["initial_expected_ticks"]
        self._expected_signed = self._cfg["initial_expected_signed"]
        self._signed_volume = 0.0
        self._frozen_threshold = 0.0
        self._frozen_expected_ticks = 0.0
        self._frozen_expected_signed = 0.0
        self._bar_count = 0
        self._flushed = False
        self._begin_bar()

    # -- observable state --------------------------------------------------- #
    @property
    def signed_volume(self) -> float:
        """Signed share imbalance accumulated in the open bar."""
        return self._signed_volume

    @property
    def threshold(self) -> float:
        """Frozen threshold (shares) the open bar is being judged against."""
        return self._frozen_threshold

    @property
    def expected_ticks(self) -> float:
        """Live EWMA estimate of ticks per bar (feeds the *next* bar's threshold)."""
        return self._expected_ticks

    @property
    def expected_signed_volume(self) -> float:
        """Live EWMA estimate of signed volume per tick, in shares."""
        return self._expected_signed

    @property
    def tick_sign(self) -> int:
        """Sign the next flat trade would carry (+1 or -1)."""
        return self._tick_sign

    @property
    def tick_count(self) -> int:
        """Trades currently held in the open bar."""
        return len(self._current)

    # -- internals ---------------------------------------------------------- #
    def _begin_bar(self) -> None:
        self._current = []
        self._signed_volume = 0.0
        self._frozen_expected_ticks = self._expected_ticks
        self._frozen_expected_signed = self._expected_signed
        raw = self._frozen_expected_ticks * abs(self._frozen_expected_signed)
        self._frozen_threshold = max(self._cfg["floor"], self._cfg["scale"] * raw)

    def _validate_trade(self, trade: object) -> None:
        if not isinstance(trade, dict) or any(field not in trade for field in REQUIRED_TRADE_FIELDS):
            raise VolumeImbalanceBarsValidationError("trade is missing a required field")
        for field in ("tradeId", "session", "symbol", "currency"):
            if not isinstance(trade[field], str) or not trade[field]:
                raise VolumeImbalanceBarsValidationError(f"{field} must be a non-empty string")
        current_time = _timestamp(trade["timestamp"])
        if self._previous_time is not None and current_time < self._previous_time:
            raise VolumeImbalanceBarsValidationError("trades must be globally chronological")
        self._previous_time = current_time
        if trade["tradeId"] in self._ids:
            raise VolumeImbalanceBarsValidationError(
                "tradeId must be unique after corrections are resolved"
            )
        self._ids.add(trade["tradeId"])
        _finite_number(trade["price"], "price", positive=True)
        _finite_number(trade["volume"], "volume", positive=True)
        if self._symbol is None:
            self._symbol, self._currency = trade["symbol"], trade["currency"]
        elif trade["symbol"] != self._symbol or trade["currency"] != self._currency:
            raise VolumeImbalanceBarsValidationError("one symbol and one currency are allowed per call")
        if self._validation_session is None:
            self._validation_session = trade["session"]
        elif trade["session"] != self._validation_session:
            self._closed_sessions.add(self._validation_session)
            if trade["session"] in self._closed_sessions:
                raise VolumeImbalanceBarsValidationError(
                    "a session may not reappear after a later session begins"
                )
            self._validation_session = trade["session"]

    def _emit(self, reason: str) -> dict[str, Any] | None:
        if not self._current:
            return None
        prices = [float(t["price"]) for t in self._current]
        volumes = [float(t["volume"]) for t in self._current]
        threshold_met = abs(self._signed_volume) >= self._frozen_threshold
        bar = {
            "barIndex": self._bar_count,
            "session": self._current[0]["session"],
            "startTime": self._current[0]["timestamp"],
            "endTime": self._current[-1]["timestamp"],
            "open": _round(prices[0]),
            "high": _round(max(prices)),
            "low": _round(min(prices)),
            "close": _round(prices[-1]),
            "volume": _round(sum(volumes)),
            "dollarValue": _round(sum(p * v for p, v in zip(prices, volumes))),
            "tickCount": len(self._current),
            "firstTradeId": self._current[0]["tradeId"],
            "lastTradeId": self._current[-1]["tradeId"],
            "closeReason": reason,
            "isComplete": reason == "threshold",
            "signedVolume": _round(self._signed_volume),
            "thresholdShares": _round(self._frozen_threshold),
            "expectedTicksBefore": _round(self._frozen_expected_ticks),
            "expectedSignedVolumeBefore": _round(self._frozen_expected_signed),
            "overshootShares": _round(max(abs(self._signed_volume) - self._frozen_threshold, 0.0)),
            "thresholdMet": threshold_met,
        }
        self._bar_count += 1
        if reason == "threshold":
            observed_ticks = len(self._current)
            observed_signed = self._signed_volume / observed_ticks
            self._expected_ticks = (
                (1 - self._cfg["alpha_ticks"]) * self._expected_ticks
                + self._cfg["alpha_ticks"] * observed_ticks
            )
            self._expected_signed = (
                (1 - self._cfg["alpha_signed"]) * self._expected_signed
                + self._cfg["alpha_signed"] * observed_signed
            )
        self._begin_bar()
        return bar

    # -- public API --------------------------------------------------------- #
    def push(self, trade: dict[str, Any]) -> list[dict[str, Any]]:
        """Accept one trade and return any bars it closes (zero or one)."""
        if self._flushed:
            raise VolumeImbalanceBarsValidationError("cannot push after flush()")
        self._validate_trade(trade)
        emitted: list[dict[str, Any]] = []

        if self._session is not None and trade["session"] != self._session:
            if self._current and self._cfg["close_partial"]:
                bar = self._emit("session_end")
                if bar is not None:
                    emitted.append(bar)
            else:
                self._begin_bar()
            self._expected_ticks = self._cfg["initial_expected_ticks"]
            self._expected_signed = self._cfg["initial_expected_signed"]
            self._previous_price = None
            self._tick_sign = self._cfg["initial_sign"]
            self._begin_bar()
        self._session = trade["session"]

        price = float(trade["price"])
        if self._previous_price is not None:
            if price > self._previous_price:
                self._tick_sign = 1
            elif price < self._previous_price:
                self._tick_sign = -1
        self._previous_price = price
        self._current.append(trade)
        self._signed_volume += self._tick_sign * float(trade["volume"])

        if abs(self._signed_volume) >= self._frozen_threshold:
            bar = self._emit("threshold")
            if bar is not None:
                emitted.append(bar)
        return emitted

    def push_many(self, trades: object) -> list[dict[str, Any]]:
        """Feed an iterable of trades, returning every bar closed along the way."""
        try:
            iterator = iter(trades)  # type: ignore[arg-type]
        except TypeError as error:
            raise VolumeImbalanceBarsValidationError("trades must be an iterable.") from error
        emitted: list[dict[str, Any]] = []
        for trade in iterator:
            emitted.extend(self.push(trade))
        return emitted

    def flush(self) -> list[dict[str, Any]]:
        """Close the final partial bar (if ``closePartial``) and end the stream."""
        self._flushed = True
        if self._current and self._cfg["close_partial"]:
            bar = self._emit("stream_end")
            return [bar] if bar is not None else []
        return []
