from __future__ import annotations

from typing import Optional


def rolling_mean(values: list[float], window: int) -> list[Optional[float]]:
    if window <= 0:
        raise ValueError("window must be positive")

    result: list[Optional[float]] = [None] * len(values)
    running_sum = 0.0

    for idx, value in enumerate(values):
        running_sum += value
        if idx >= window:
            running_sum -= values[idx - window]
        if idx >= window - 1:
            result[idx] = running_sum / window

    return result


def average_true_range(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, and closes must have the same length")

    result: list[Optional[float]] = [None] * len(closes)
    true_ranges: list[float] = []
    for idx, close in enumerate(closes):
        if idx == 0:
            true_ranges.append(highs[idx] - lows[idx])
        else:
            previous_close = closes[idx - 1]
            true_ranges.append(
                max(
                    highs[idx] - lows[idx],
                    abs(highs[idx] - previous_close),
                    abs(lows[idx] - previous_close),
                )
            )

    if len(true_ranges) < period:
        return result

    atr_value = sum(true_ranges[:period]) / period
    result[period - 1] = atr_value
    for idx in range(period, len(true_ranges)):
        atr_value = ((atr_value * (period - 1)) + true_ranges[idx]) / period
        result[idx] = atr_value

    return result


def rsi(values: list[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("period must be positive")

    result: list[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, period + 1):
        change = values[idx] - values[idx - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for idx in range(period + 1, len(values)):
        change = values[idx] - values[idx - 1]
        gain = max(change, 0.0)
        loss = abs(min(change, 0.0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[idx] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
