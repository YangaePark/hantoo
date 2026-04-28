from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Optional

from .indicators import rolling_mean


@dataclass(frozen=True)
class IntradayConfig:
    symbol: str = "396500"
    initial_capital: float = 1_000_000.0
    opening_range_minutes: int = 20
    fast_sma: int = 6
    slow_sma: int = 18
    volume_sma: int = 12
    volume_factor: float = 0.85
    min_edge_bps: float = 25.0
    max_extension_pct: float = 0.025
    risk_per_trade_pct: float = 0.009
    max_position_pct: float = 1.00
    stop_loss_pct: float = 0.006
    take_profit_pct: float = 0.015
    trailing_stop_pct: float = 0.007
    daily_stop_loss_pct: float = 0.018
    max_trades_per_day: int = 4
    cooldown_bars: int = 3
    min_hold_bars: int = 2
    force_exit_time: str = "15:15"
    commission_bps: float = 1.5
    slippage_bps: float = 5.0
    sell_tax_bps: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntradayConfig":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in known})

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

    @property
    def force_exit_clock(self) -> time:
        return datetime.strptime(self.force_exit_time, "%H:%M").time()


@dataclass(frozen=True)
class IntradayBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def session(self) -> date:
        return self.timestamp.date()


@dataclass(frozen=True)
class IntradayTrade:
    timestamp: datetime
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
class IntradayBacktestResult:
    metrics: dict[str, Any]
    trades: list[IntradayTrade]
    equity_curve: list[dict[str, Any]]


def load_intraday_csv(path: str | Path) -> list[IntradayBar]:
    bars: list[IntradayBar] = []
    with Path(path).open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"datetime", "open", "high", "low", "close", "volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            bars.append(
                IntradayBar(
                    timestamp=_parse_datetime(row["datetime"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row["volume"])),
                )
            )
    bars.sort(key=lambda bar: bar.timestamp)
    return bars


class IntradayBacktester:
    def __init__(self, config: IntradayConfig):
        self.config = config

    def run(self, bars: list[IntradayBar]) -> IntradayBacktestResult:
        if len(bars) < max(self.config.slow_sma, self.config.volume_sma) + 2:
            raise ValueError("Not enough bars for intraday backtest")

        cash = self.config.initial_capital
        shares = 0
        avg_cost = 0.0
        entry_bar_idx: Optional[int] = None
        highest_close = 0.0
        cooldown_until = -1
        current_session: Optional[date] = None
        day_start_equity = self.config.initial_capital
        day_trades = 0
        day_paused = False
        trades: list[IntradayTrade] = []
        equity_curve: list[dict[str, Any]] = []

        for idx, bar in enumerate(bars):
            if bar.session != current_session:
                if shares > 0 and idx > 0:
                    previous_bar = bars[idx - 1]
                    cash, avg_cost = self._sell(
                        previous_bar,
                        "SELL_ALL",
                        shares,
                        shares,
                        cash,
                        avg_cost,
                        trades,
                        "session_close",
                        price_source="close",
                    )
                    shares = 0
                    entry_bar_idx = None
                    highest_close = 0.0

                current_session = bar.session
                day_start_equity = cash
                day_trades = 0
                day_paused = False
                cooldown_until = -1

            session_bars = self._session_bars_until(bars, idx)
            closes = [session_bar.close for session_bar in session_bars]
            volumes = [float(session_bar.volume) for session_bar in session_bars]
            fast = rolling_mean(closes, self.config.fast_sma)
            slow = rolling_mean(closes, self.config.slow_sma)
            volume_avg = rolling_mean(volumes, self.config.volume_sma)
            vwap_values = _vwap(session_bars)
            signal_idx = len(session_bars) - 2

            open_equity = cash + shares * bar.open
            if day_start_equity > 0 and (open_equity / day_start_equity) - 1.0 <= -self.config.daily_stop_loss_pct:
                day_paused = True

            traded = False
            if shares > 0:
                holding_bars = 0 if entry_bar_idx is None else idx - entry_bar_idx
                if bar.timestamp.time() >= self.config.force_exit_clock:
                    exit_reason = "force_exit"
                elif signal_idx >= 0:
                    signal_bar = session_bars[signal_idx]
                    highest_close = max(highest_close, signal_bar.close)
                    exit_reason = self._exit_reason(signal_bar, avg_cost, highest_close, holding_bars)
                else:
                    exit_reason = None

                if exit_reason:
                    cash, avg_cost = self._sell(bar, "SELL_ALL", shares, shares, cash, avg_cost, trades, exit_reason)
                    shares = 0
                    entry_bar_idx = None
                    highest_close = 0.0
                    cooldown_until = idx + self.config.cooldown_bars
                    traded = True

            can_enter = (
                shares == 0
                and not traded
                and not day_paused
                and day_trades < self.config.max_trades_per_day
                and idx > cooldown_until
                and signal_idx >= 0
            )
            if can_enter and self._entry_signal(session_bars, signal_idx, fast, slow, volume_avg, vwap_values):
                bought, cash, avg_cost = self._buy(bar, shares, cash, avg_cost, trades, "opening_range_breakout")
                if bought:
                    shares += bought
                    entry_bar_idx = idx
                    highest_close = bar.open
                    day_trades += 1

            equity = cash + shares * bar.close
            peak = max([float(point["equity"]) for point in equity_curve], default=self.config.initial_capital)
            peak = max(peak, equity)
            equity_curve.append(
                {
                    "datetime": bar.timestamp.isoformat(sep=" "),
                    "cash": round(cash, 2),
                    "shares": shares,
                    "close": round(bar.close, 2),
                    "equity": round(equity, 2),
                    "drawdown": round((equity / peak) - 1.0 if peak else 0.0, 6),
                    "paused": int(day_paused),
                }
            )

        if shares > 0:
            last_bar = bars[-1]
            cash, avg_cost = self._sell(
                last_bar,
                "SELL_ALL",
                shares,
                shares,
                cash,
                avg_cost,
                trades,
                "final_close",
                price_source="close",
            )
            shares = 0
            equity_curve[-1]["cash"] = round(cash, 2)
            equity_curve[-1]["shares"] = shares
            equity_curve[-1]["equity"] = round(cash, 2)

        return IntradayBacktestResult(metrics=self._metrics(bars, trades, equity_curve), trades=trades, equity_curve=equity_curve)

    def _entry_signal(
        self,
        session_bars: list[IntradayBar],
        idx: int,
        fast: list[Optional[float]],
        slow: list[Optional[float]],
        volume_avg: list[Optional[float]],
        vwap_values: list[Optional[float]],
    ) -> bool:
        bar = session_bars[idx]
        session_start = session_bars[0].timestamp
        if bar.timestamp < session_start + timedelta(minutes=self.config.opening_range_minutes):
            return False
        if fast[idx] is None or slow[idx] is None or volume_avg[idx] is None or vwap_values[idx] is None:
            return False

        opening_bars = [
            item
            for item in session_bars[: idx + 1]
            if item.timestamp < session_start + timedelta(minutes=self.config.opening_range_minutes)
        ]
        if not opening_bars:
            return False

        opening_high = max(item.high for item in opening_bars)
        required_break = self.config.round_trip_cost_rate + self.config.min_edge_rate
        extension = (bar.close / float(vwap_values[idx])) - 1.0
        return (
            bar.close > opening_high * (1.0 + required_break)
            and bar.close > float(vwap_values[idx])
            and float(fast[idx]) > float(slow[idx])
            and bar.volume >= float(volume_avg[idx]) * self.config.volume_factor
            and extension <= self.config.max_extension_pct
        )

    def _exit_reason(self, bar: IntradayBar, avg_cost: float, highest_close: float, holding_bars: int) -> Optional[str]:
        if bar.timestamp.time() >= self.config.force_exit_clock:
            return "force_exit"
        if bar.close <= avg_cost * (1.0 - self.config.stop_loss_pct):
            return "stop_loss"
        if holding_bars >= self.config.min_hold_bars and bar.close >= avg_cost * (1.0 + self.config.take_profit_pct):
            return "take_profit"
        if holding_bars >= self.config.min_hold_bars and highest_close > 0:
            if bar.close <= highest_close * (1.0 - self.config.trailing_stop_pct):
                return "trailing_stop"
        return None

    def _buy(
        self,
        bar: IntradayBar,
        shares: int,
        cash: float,
        avg_cost: float,
        trades: list[IntradayTrade],
        reason: str,
    ) -> tuple[int, float, float]:
        equity = cash + shares * bar.open
        risk_budget = equity * self.config.risk_per_trade_pct
        risk_cap = risk_budget / self.config.stop_loss_pct
        position_cap = equity * self.config.max_position_pct
        budget = min(cash, risk_cap, position_cap)
        price = bar.open * (1.0 + self.config.slippage_rate)
        cost_per_share = price * (1.0 + self.config.commission_rate)
        shares_to_buy = math.floor(budget / cost_per_share)
        if shares_to_buy <= 0:
            return 0, cash, avg_cost

        gross = shares_to_buy * price
        commission = gross * self.config.commission_rate
        total_cost = gross + commission
        new_cash = cash - total_cost
        new_avg_cost = ((avg_cost * shares) + total_cost) / (shares + shares_to_buy)
        trades.append(
            IntradayTrade(
                timestamp=bar.timestamp,
                action="BUY",
                symbol=self.config.symbol,
                shares=shares_to_buy,
                price=round(price, 4),
                gross=round(gross, 2),
                cost=round(commission, 2),
                realized_pnl=0.0,
                cash_after=round(new_cash, 2),
                position_after=shares + shares_to_buy,
                reason=reason,
            )
        )
        return shares_to_buy, new_cash, new_avg_cost

    def _sell(
        self,
        bar: IntradayBar,
        action: str,
        shares_to_sell: int,
        shares: int,
        cash: float,
        avg_cost: float,
        trades: list[IntradayTrade],
        reason: str,
        price_source: str = "open",
    ) -> tuple[float, float]:
        shares_to_sell = min(shares_to_sell, shares)
        raw_price = bar.close if price_source == "close" else bar.open
        price = raw_price * (1.0 - self.config.slippage_rate)
        gross = shares_to_sell * price
        commission = gross * self.config.commission_rate
        tax = gross * self.config.sell_tax_rate
        net = gross - commission - tax
        realized_pnl = net - (avg_cost * shares_to_sell)
        new_cash = cash + net
        remaining = shares - shares_to_sell
        trades.append(
            IntradayTrade(
                timestamp=bar.timestamp,
                action=action,
                symbol=self.config.symbol,
                shares=shares_to_sell,
                price=round(price, 4),
                gross=round(gross, 2),
                cost=round(commission + tax, 2),
                realized_pnl=round(realized_pnl, 2),
                cash_after=round(new_cash, 2),
                position_after=remaining,
                reason=reason,
            )
        )
        return new_cash, avg_cost if remaining > 0 else 0.0

    def _session_bars_until(self, bars: list[IntradayBar], idx: int) -> list[IntradayBar]:
        session = bars[idx].session
        start = idx
        while start > 0 and bars[start - 1].session == session:
            start -= 1
        return bars[start : idx + 1]

    def _metrics(
        self,
        bars: list[IntradayBar],
        trades: list[IntradayTrade],
        equity_curve: list[dict[str, Any]],
    ) -> dict[str, Any]:
        final_equity = float(equity_curve[-1]["equity"])
        total_return = (final_equity / self.config.initial_capital) - 1.0
        max_drawdown = min(float(point["drawdown"]) for point in equity_curve)
        sell_trades = [trade for trade in trades if trade.action.startswith("SELL")]
        winning_sells = [trade for trade in sell_trades if trade.realized_pnl > 0]
        session_count = len({bar.session for bar in bars})
        daily_returns = _daily_close_returns(equity_curve)
        return {
            "symbol": self.config.symbol,
            "start_datetime": bars[0].timestamp.isoformat(sep=" "),
            "end_datetime": bars[-1].timestamp.isoformat(sep=" "),
            "sessions": session_count,
            "initial_capital": round(self.config.initial_capital, 2),
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100.0, 2),
            "max_drawdown_pct": round(max_drawdown * 100.0, 2),
            "sharpe_approx": round(_sharpe(daily_returns), 3),
            "trades": len(trades),
            "sell_trades": len(sell_trades),
            "sell_win_rate_pct": round((len(winning_sells) / len(sell_trades) * 100.0), 2) if sell_trades else 0.0,
            "realized_pnl": round(sum(trade.realized_pnl for trade in sell_trades), 2),
            "explicit_trade_cost": round(sum(trade.cost for trade in trades), 2),
            "round_trip_cost_pct": round(self.config.round_trip_cost_rate * 100.0, 3),
            "exposure_pct": round((sum(1 for point in equity_curve if int(point["shares"]) > 0) / len(equity_curve)) * 100.0, 2),
        }


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(value)


def _vwap(bars: list[IntradayBar]) -> list[Optional[float]]:
    values: list[Optional[float]] = []
    cumulative_value = 0.0
    cumulative_volume = 0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        cumulative_value += typical * bar.volume
        cumulative_volume += bar.volume
        values.append(cumulative_value / cumulative_volume if cumulative_volume else None)
    return values


def _daily_close_returns(equity_curve: list[dict[str, Any]]) -> list[float]:
    closes: dict[str, float] = {}
    for point in equity_curve:
        closes[str(point["datetime"])[:10]] = float(point["equity"])
    values = list(closes.values())
    return [(values[idx] / values[idx - 1]) - 1.0 for idx in range(1, len(values)) if values[idx - 1] > 0]


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    volatility = stdev(returns)
    if volatility == 0:
        return 0.0
    return (mean(returns) / volatility) * math.sqrt(252.0)
