from __future__ import annotations

import csv
import math
from datetime import date, datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

from .indicators import average_true_range, rolling_mean, rsi
from .models import BacktestResult, Bar, Trade
from .strategy import StrategyConfig


def load_bars_csv(path: str | Path) -> list[Bar]:
    bars: list[Bar] = []
    with Path(path).open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            bars.append(
                Bar(
                    date=_parse_date(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row["volume"])),
                )
            )

    bars.sort(key=lambda bar: bar.date)
    return bars


class Backtester:
    def __init__(self, config: StrategyConfig):
        self.config = config

    def run(self, bars: list[Bar]) -> BacktestResult:
        min_bars = (
            max(
                self.config.long_sma + self.config.trend_slope_days,
                self.config.slow_sma,
                self.config.volume_sma,
                self.config.rsi_period,
                self.config.atr_period,
            )
            + 2
        )
        if len(bars) < min_bars:
            raise ValueError(f"Need at least {min_bars} bars, got {len(bars)}")

        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        volumes = [float(bar.volume) for bar in bars]
        fast = rolling_mean(closes, self.config.fast_sma)
        slow = rolling_mean(closes, self.config.slow_sma)
        long = rolling_mean(closes, self.config.long_sma)
        volume_avg = rolling_mean(volumes, self.config.volume_sma)
        rsi_values = rsi(closes, self.config.rsi_period)
        atr_values = average_true_range(highs, lows, closes, self.config.atr_period)

        cash = self.config.initial_capital
        shares = 0
        avg_cost = 0.0
        add_count = 0
        partial_taken = False
        entry_idx: Optional[int] = None
        highest_close_since_entry = 0.0
        cooldown_until_idx = -1
        month_key: Optional[tuple[int, int]] = None
        month_start_equity = self.config.initial_capital
        pause_new_entries = False
        trades: list[Trade] = []
        equity_curve: list[dict[str, float | int | str]] = []

        for idx, bar in enumerate(bars):
            current_month = (bar.date.year, bar.date.month)
            previous_close_equity = equity_curve[-1]["equity"] if equity_curve else self.config.initial_capital
            if current_month != month_key:
                month_key = current_month
                month_start_equity = float(previous_close_equity)
                pause_new_entries = False

            if idx > 0:
                signal_idx = idx - 1
                signal = self._entry_signal(signal_idx, bars, fast, slow, long, volume_avg, rsi_values, atr_values)
                open_equity = cash + shares * bar.open
                traded_today = False

                if shares > 0:
                    highest_close_since_entry = max(highest_close_since_entry, bars[signal_idx].close)

                if month_start_equity > 0:
                    month_drawdown = (open_equity / month_start_equity) - 1.0
                    if month_drawdown <= -self.config.monthly_stop_loss_pct:
                        pause_new_entries = True

                if shares > 0:
                    holding_days = 0 if entry_idx is None else idx - entry_idx
                    exit_reason = self._exit_reason(
                        signal_idx,
                        bars,
                        fast,
                        slow,
                        long,
                        atr_values,
                        avg_cost,
                        highest_close_since_entry,
                        holding_days,
                    )
                    if exit_reason:
                        cash, avg_cost = self._sell(
                            bar=bar,
                            action="SELL_ALL",
                            shares_to_sell=shares,
                            shares=shares,
                            cash=cash,
                            avg_cost=avg_cost,
                            trades=trades,
                            reason=exit_reason,
                        )
                        shares = 0
                        add_count = 0
                        partial_taken = False
                        entry_idx = None
                        highest_close_since_entry = 0.0
                        cooldown_until_idx = idx + self.config.cooldown_days_after_exit
                        traded_today = True
                    elif not partial_taken and bars[signal_idx].close >= avg_cost * (1.0 + self.config.take_profit_pct):
                        shares_to_sell = max(1, math.floor(shares * self.config.partial_sell_ratio))
                        cash, avg_cost = self._sell(
                            bar=bar,
                            action="SELL_PARTIAL",
                            shares_to_sell=shares_to_sell,
                            shares=shares,
                            cash=cash,
                            avg_cost=avg_cost,
                            trades=trades,
                            reason="take_profit",
                        )
                        shares -= shares_to_sell
                        partial_taken = True
                        traded_today = True

                can_enter = not pause_new_entries and idx > cooldown_until_idx and not traded_today

                if shares > 0 and add_count == 0 and can_enter:
                    signal_idx = idx - 1
                    if signal and bars[signal_idx].close >= avg_cost * (1.0 + self.config.add_on_profit_pct):
                        bought, cash, avg_cost = self._buy(
                            bar=bar,
                            action="ADD",
                            allocation_pct=self.config.add_allocation_pct,
                            shares=shares,
                            cash=cash,
                            avg_cost=avg_cost,
                            trades=trades,
                            reason="trend_add",
                        )
                        shares += bought
                        if bought:
                            add_count += 1
                            traded_today = True

                if shares == 0 and signal and can_enter:
                    bought, cash, avg_cost = self._buy(
                        bar=bar,
                        action="BUY",
                        allocation_pct=self.config.initial_allocation_pct,
                        shares=shares,
                        cash=cash,
                        avg_cost=avg_cost,
                        trades=trades,
                        reason="trend_entry",
                    )
                    shares += bought
                    if bought:
                        partial_taken = False
                        add_count = 0
                        entry_idx = idx
                        highest_close_since_entry = bars[signal_idx].close

            equity = cash + shares * bar.close
            peak = max([float(point["equity"]) for point in equity_curve], default=self.config.initial_capital)
            peak = max(peak, equity)
            drawdown = (equity / peak) - 1.0 if peak else 0.0
            equity_curve.append(
                {
                    "date": bar.date.isoformat(),
                    "cash": round(cash, 2),
                    "shares": shares,
                    "close": round(bar.close, 2),
                    "equity": round(equity, 2),
                    "drawdown": round(drawdown, 6),
                    "paused": int(pause_new_entries),
                }
            )

        metrics = self._metrics(bars, trades, equity_curve)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)

    def _entry_signal(
        self,
        idx: int,
        bars: list[Bar],
        fast: list[Optional[float]],
        slow: list[Optional[float]],
        long: list[Optional[float]],
        volume_avg: list[Optional[float]],
        rsi_values: list[Optional[float]],
        atr_values: list[Optional[float]],
    ) -> bool:
        if (
            fast[idx] is None
            or slow[idx] is None
            or long[idx] is None
            or volume_avg[idx] is None
            or rsi_values[idx] is None
            or atr_values[idx] is None
        ):
            return False
        slope_idx = idx - self.config.trend_slope_days
        if slope_idx < 0 or long[slope_idx] is None:
            return False

        close = bars[idx].close
        fast_value = float(fast[idx])
        slow_value = float(slow[idx])
        long_value = float(long[idx])
        trend_buffer = self.config.round_trip_cost_rate + self.config.min_edge_rate
        atr_pct = float(atr_values[idx]) / close
        price_extension = (close / fast_value) - 1.0
        trend_edge = ((fast_value / slow_value) - 1.0) + ((close / long_value) - 1.0)
        required_edge = self.config.round_trip_cost_rate + self.config.min_edge_rate

        return (
            close > long_value * (1.0 + trend_buffer)
            and fast_value > slow_value * (1.0 + trend_buffer)
            and slow_value >= long_value
            and long_value > float(long[slope_idx])
            and self.config.rsi_min <= float(rsi_values[idx]) <= self.config.rsi_max
            and bars[idx].volume >= float(volume_avg[idx]) * self.config.volume_factor
            and atr_pct <= self.config.max_atr_pct
            and price_extension <= self.config.max_price_extension_pct
            and trend_edge >= required_edge
        )

    def _exit_reason(
        self,
        idx: int,
        bars: list[Bar],
        fast: list[Optional[float]],
        slow: list[Optional[float]],
        long: list[Optional[float]],
        atr_values: list[Optional[float]],
        avg_cost: float,
        highest_close_since_entry: float,
        holding_days: int,
    ) -> Optional[str]:
        if bars[idx].close <= avg_cost * (1.0 - self.config.stop_loss_pct):
            return "stop_loss"
        if atr_values[idx] is not None:
            atr_stop = highest_close_since_entry - (float(atr_values[idx]) * self.config.atr_stop_multiplier)
            if bars[idx].close <= atr_stop and holding_days >= self.config.min_hold_days:
                return "atr_trailing_stop"
        if highest_close_since_entry > 0:
            trailing_stop = highest_close_since_entry * (1.0 - self.config.trailing_stop_pct)
            if bars[idx].close <= trailing_stop and holding_days >= self.config.min_hold_days:
                return "trailing_stop"
        if long[idx] is not None and bars[idx].close < float(long[idx]):
            return "long_sma_break"
        if slow[idx] is not None and holding_days >= self.config.min_hold_days:
            if bars[idx].close < float(slow[idx]) * (1.0 - self.config.round_trip_cost_rate):
                return "slow_sma_break"
        return None

    def _buy(
        self,
        bar: Bar,
        action: str,
        allocation_pct: float,
        shares: int,
        cash: float,
        avg_cost: float,
        trades: list[Trade],
        reason: str,
    ) -> tuple[int, float, float]:
        equity_at_open = cash + shares * bar.open
        reserve_cash = equity_at_open * self.config.cash_reserve_pct
        current_position_value = shares * bar.open
        max_position_value = equity_at_open * self.config.max_position_pct
        allocation_budget = equity_at_open * allocation_pct
        position_room = max(0.0, max_position_value - current_position_value)
        spendable_cash = max(0.0, cash - reserve_cash)
        budget = min(allocation_budget, position_room, spendable_cash)
        risk_budget = equity_at_open * self.config.risk_per_trade_pct
        stop_distance = self.config.stop_loss_pct
        risk_budget_cap = risk_budget / stop_distance if stop_distance > 0 else budget
        budget = min(budget, risk_budget_cap)

        price = bar.open * (1.0 + self.config.slippage_rate)
        cost_per_share = price * (1.0 + self.config.commission_rate)
        shares_to_buy = math.floor(budget / cost_per_share)
        if shares_to_buy <= 0:
            return 0, cash, avg_cost

        gross = shares_to_buy * price
        commission = gross * self.config.commission_rate
        total_cost = gross + commission
        new_cash = cash - total_cost
        new_shares = shares + shares_to_buy
        new_avg_cost = ((avg_cost * shares) + total_cost) / new_shares
        trades.append(
            Trade(
                date=bar.date,
                action=action,
                symbol=self.config.symbol,
                shares=shares_to_buy,
                price=round(price, 4),
                gross=round(gross, 2),
                cost=round(commission, 2),
                realized_pnl=0.0,
                cash_after=round(new_cash, 2),
                position_after=new_shares,
                reason=reason,
            )
        )
        return shares_to_buy, new_cash, new_avg_cost

    def _sell(
        self,
        bar: Bar,
        action: str,
        shares_to_sell: int,
        shares: int,
        cash: float,
        avg_cost: float,
        trades: list[Trade],
        reason: str,
    ) -> tuple[float, float]:
        shares_to_sell = min(shares_to_sell, shares)
        price = bar.open * (1.0 - self.config.slippage_rate)
        gross = shares_to_sell * price
        commission = gross * self.config.commission_rate
        tax = gross * self.config.sell_tax_rate
        net = gross - commission - tax
        realized_pnl = net - (avg_cost * shares_to_sell)
        new_cash = cash + net
        remaining = shares - shares_to_sell
        new_avg_cost = avg_cost if remaining > 0 else 0.0
        trades.append(
            Trade(
                date=bar.date,
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
        return new_cash, new_avg_cost

    def _metrics(
        self,
        bars: list[Bar],
        trades: list[Trade],
        equity_curve: list[dict[str, float | int | str]],
    ) -> dict[str, float | int | str]:
        start_equity = self.config.initial_capital
        final_equity = float(equity_curve[-1]["equity"])
        total_return = (final_equity / start_equity) - 1.0
        days = max(1, (bars[-1].date - bars[0].date).days)
        cagr = (final_equity / start_equity) ** (365.0 / days) - 1.0
        max_drawdown = min(float(point["drawdown"]) for point in equity_curve)
        sell_trades = [trade for trade in trades if trade.action.startswith("SELL")]
        winning_sells = [trade for trade in sell_trades if trade.realized_pnl > 0]
        exposure_days = sum(1 for point in equity_curve if int(point["shares"]) > 0)
        daily_returns = _daily_returns(equity_curve)
        sharpe = _sharpe(daily_returns)

        return {
            "symbol": self.config.symbol,
            "start_date": bars[0].date.isoformat(),
            "end_date": bars[-1].date.isoformat(),
            "initial_capital": round(start_equity, 2),
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100.0, 2),
            "cagr_pct": round(cagr * 100.0, 2),
            "max_drawdown_pct": round(max_drawdown * 100.0, 2),
            "buy_and_hold_return_pct": round(((bars[-1].close / bars[0].close) - 1.0) * 100.0, 2),
            "sharpe_approx": round(sharpe, 3),
            "trades": len(trades),
            "sell_trades": len(sell_trades),
            "sell_win_rate_pct": round((len(winning_sells) / len(sell_trades) * 100.0), 2) if sell_trades else 0.0,
            "realized_pnl": round(sum(trade.realized_pnl for trade in sell_trades), 2),
            "explicit_trade_cost": round(sum(trade.cost for trade in trades), 2),
            "round_trip_cost_pct": round(self.config.round_trip_cost_rate * 100.0, 3),
            "exposure_pct": round((exposure_days / len(equity_curve)) * 100.0, 2),
        }


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unsupported date format: {value}")


def _daily_returns(equity_curve: list[dict[str, float | int | str]]) -> list[float]:
    returns: list[float] = []
    for idx in range(1, len(equity_curve)):
        previous = float(equity_curve[idx - 1]["equity"])
        current = float(equity_curve[idx]["equity"])
        if previous > 0:
            returns.append((current / previous) - 1.0)
    return returns


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    volatility = stdev(returns)
    if volatility == 0:
        return 0.0
    return (mean(returns) / volatility) * math.sqrt(252.0)
