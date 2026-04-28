from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyConfig:
    symbol: str = "396500"
    initial_capital: float = 1_000_000.0
    fast_sma: int = 20
    slow_sma: int = 60
    long_sma: int = 120
    trend_slope_days: int = 10
    rsi_period: int = 14
    rsi_min: float = 35.0
    rsi_max: float = 84.0
    volume_sma: int = 20
    volume_factor: float = 0.5
    atr_period: int = 14
    max_atr_pct: float = 0.09
    max_price_extension_pct: float = 0.18
    min_edge_bps: float = 20.0
    risk_per_trade_pct: float = 0.024
    initial_allocation_pct: float = 0.55
    add_allocation_pct: float = 0.25
    max_position_pct: float = 0.90
    cash_reserve_pct: float = 0.10
    add_on_profit_pct: float = 0.04
    take_profit_pct: float = 0.12
    partial_sell_ratio: float = 0.50
    stop_loss_pct: float = 0.08
    trailing_stop_pct: float = 0.15
    atr_stop_multiplier: float = 2.2
    min_hold_days: int = 3
    cooldown_days_after_exit: int = 3
    monthly_stop_loss_pct: float = 0.05
    commission_bps: float = 1.5
    slippage_bps: float = 5.0
    sell_tax_bps: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyConfig":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        filtered = {key: value for key, value in data.items() if key in known}
        return cls(**filtered)

    @property
    def commission_rate(self) -> float:
        return self.commission_bps / 10_000.0

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0

    @property
    def sell_tax_rate(self) -> float:
        return self.sell_tax_bps / 10_000.0

    @property
    def round_trip_cost_rate(self) -> float:
        buy_cost = self.commission_rate + self.slippage_rate
        sell_cost = self.commission_rate + self.slippage_rate + self.sell_tax_rate
        return buy_cost + sell_cost

    @property
    def min_edge_rate(self) -> float:
        return self.min_edge_bps / 10_000.0
