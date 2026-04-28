from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class Trade:
    date: date
    action: str
    symbol: str
    shares: int
    price: float
    gross: float
    cost: float
    realized_pnl: float
    cash_after: float
    position_after: int
    reason: str


@dataclass(frozen=True)
class BacktestResult:
    metrics: dict[str, Any]
    trades: list[Trade]
    equity_curve: list[dict[str, Any]]
