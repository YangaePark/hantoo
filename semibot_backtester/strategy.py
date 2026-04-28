from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyConfig:
    symbol: str = "396500"
    initial_capital: float = 1_000_000.0
    fast_sma: int = 20
    slow_sma: int = 60
    rsi_period: int = 14
    rsi_min: float = 45.0
    rsi_max: float = 70.0
    volume_sma: int = 20
    volume_factor: float = 1.0
    initial_allocation_pct: float = 0.30
    add_allocation_pct: float = 0.25
    max_position_pct: float = 0.70
    cash_reserve_pct: float = 0.30
    add_on_profit_pct: float = 0.03
    take_profit_pct: float = 0.07
    partial_sell_ratio: float = 0.50
    stop_loss_pct: float = 0.04
    monthly_stop_loss_pct: float = 0.06
    commission_bps: float = 1.5
    slippage_bps: float = 3.0
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
