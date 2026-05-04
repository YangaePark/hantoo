from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Optional

from .indicators import average_true_range, rolling_mean


@dataclass(frozen=True)
class StockScannerConfig:
    initial_capital: float = 1_000_000.0
    entry_start_time: str = ""
    entry_cutoff_time: str = ""
    adaptive_market_regime: bool = False
    stop_loss_reentry_block_minutes: int = 0
    observation_minutes: int = 20
    top_value_rank: int = 5
    gap_min_pct: float = 0.02
    gap_max_pct: float = 0.08
    volume_sma: int = 12
    volume_factor: float = 2.0
    atr_period: int = 6
    min_atr_pct: float = 0.006
    max_atr_pct: float = 0.05
    max_spread_pct: float = 0.002
    require_spread: bool = False
    min_edge_bps: float = 30.0
    max_extension_pct: float = 0.04
    risk_per_trade_pct: float = 0.012
    max_position_pct: float = 1.0
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.025
    partial_take_profit_pct: float = 0.0
    partial_sell_ratio: float = 0.5
    trailing_stop_pct: float = 0.012
    daily_take_profit_pct: float = 0.0
    daily_stop_loss_pct: float = 0.035
    loss_cooldown_trades: int = 0
    loss_cooldown_minutes: int = 30
    max_consecutive_losses: int = 0
    max_trades_per_day: int = 6
    cooldown_bars: int = 2
    min_hold_bars: int = 1
    force_exit_time: str = "15:15"
    exclude_warning: bool = True
    vi_proxy_move_pct: float = 0.05
    vi_cooldown_bars: int = 2
    commission_bps: float = 1.5
    slippage_bps: float = 8.0
    sell_tax_bps: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StockScannerConfig":
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

    @property
    def entry_start_clock(self) -> time:
        return _parse_clock(self.entry_start_time, time.min)

    @property
    def entry_cutoff_clock(self) -> time:
        return _parse_clock(self.entry_cutoff_time, self.force_exit_clock)


@dataclass(frozen=True)
class StockBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_pct: Optional[float] = None
    warning: bool = False

    @property
    def session(self) -> date:
        return self.timestamp.date()

    @property
    def value(self) -> float:
        return self.close * self.volume


@dataclass(frozen=True)
class ScannerTrade:
    timestamp: datetime
    action: str
    symbol: str
    shares: int
    price: float
    gross: float
    cost: float
    realized_pnl: float
    cash_after: float
    reason: str


@dataclass(frozen=True)
class ScannerResult:
    metrics: dict[str, Any]
    trades: list[ScannerTrade]
    equity_curve: list[dict[str, Any]]


def load_stock_scanner_csv(path: str | Path) -> list[StockBar]:
    bars: list[StockBar] = []
    with Path(path).open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"symbol", "datetime", "open", "high", "low", "close", "volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            bid = _optional_float(row.get("bid"))
            ask = _optional_float(row.get("ask"))
            spread = _optional_float(row.get("spread_pct"))
            if spread is None and bid and ask and bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0
                spread = (ask - bid) / mid if mid else None
            bars.append(
                StockBar(
                    symbol=row["symbol"].strip(),
                    timestamp=_parse_datetime(row["datetime"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row["volume"])),
                    bid=bid,
                    ask=ask,
                    spread_pct=spread,
                    warning=_truthy(row.get("warning") or row.get("is_warning") or row.get("exclude")),
                )
            )
    bars.sort(key=lambda bar: (bar.timestamp, bar.symbol))
    return bars


class StockScannerBacktester:
    def __init__(self, config: StockScannerConfig):
        self.config = config

    def run(self, bars: list[StockBar]) -> ScannerResult:
        if not bars:
            raise ValueError("No bars to backtest")

        by_symbol = _group_by_symbol(bars)
        by_time = _group_by_time(bars)
        prev_close = _previous_session_close(by_symbol)
        cash = self.config.initial_capital
        position_symbol: Optional[str] = None
        shares = 0
        avg_cost = 0.0
        entry_index: Optional[int] = None
        highest_close = 0.0
        partial_stages = 0
        current_session: Optional[date] = None
        day_start_equity = self.config.initial_capital
        day_trades = 0
        day_paused = False
        cooldown_until: dict[str, int] = {}
        vi_until: dict[str, int] = {}
        trades: list[ScannerTrade] = []
        equity_curve: list[dict[str, Any]] = []

        ordered_times = sorted(by_time)
        latest_close: dict[str, float] = {}

        for time_idx, timestamp in enumerate(ordered_times):
            session = timestamp.date()
            current_bars = by_time[timestamp]
            bar_by_symbol = {bar.symbol: bar for bar in current_bars}

            if current_session != session:
                if position_symbol and shares > 0:
                    last_bar = _last_bar_before_or_at(by_symbol[position_symbol], timestamp)
                    cash, avg_cost = self._sell(last_bar, "SELL_ALL", shares, cash, avg_cost, trades, "session_close", "close")
                    position_symbol = None
                    shares = 0
                    entry_index = None
                    highest_close = 0.0
                    partial_stages = 0
                current_session = session
                day_start_equity = cash
                day_trades = 0
                day_paused = False

            for bar in current_bars:
                latest_close[bar.symbol] = bar.close
                if abs((bar.close / bar.open) - 1.0) >= self.config.vi_proxy_move_pct:
                    vi_until[bar.symbol] = time_idx + self.config.vi_cooldown_bars

            mark_price = latest_close.get(position_symbol, 0.0) if position_symbol else 0.0
            open_equity = cash + shares * mark_price
            if day_start_equity > 0 and (open_equity / day_start_equity) - 1.0 <= -self.config.daily_stop_loss_pct:
                day_paused = True

            traded = False
            if position_symbol and shares > 0:
                current_bar = bar_by_symbol.get(position_symbol)
                if current_bar:
                    symbol_bars = by_symbol[position_symbol]
                    signal_idx = _bar_index_before_time(symbol_bars, timestamp)
                    holding_bars = 0 if entry_index is None else time_idx - entry_index
                    if timestamp.time() >= self.config.force_exit_clock:
                        exit_reason = "force_exit"
                    elif signal_idx is not None:
                        signal_bar = symbol_bars[signal_idx]
                        highest_close = max(highest_close, signal_bar.close)
                        # 우선 부분익절 체크 (다단 2회까지)
                        if (
                            self.config.partial_take_profit_pct > 0
                            and partial_stages < 2
                            and shares > 1
                            and holding_bars >= self.config.min_hold_bars
                            and signal_bar.high >= avg_cost * (1.0 + self.config.partial_take_profit_pct * (partial_stages + 1))
                        ):
                            partial_shares = max(1, min(shares - 1, math.floor(shares * self.config.partial_sell_ratio)))
                            cash, avg_cost = self._sell(current_bar, "SELL_PARTIAL", partial_shares, cash, avg_cost, trades, "partial_take_profit")
                            shares -= partial_shares
                            partial_stages += 1
                            traded = True
                            exit_reason = None
                        else:
                            exit_reason = self._exit_reason(signal_bar, avg_cost, highest_close, holding_bars)
                    else:
                        exit_reason = None
                    if exit_reason:
                        cash, avg_cost = self._sell(current_bar, "SELL_ALL", shares, cash, avg_cost, trades, exit_reason)
                        cooldown_until[position_symbol] = time_idx + self.config.cooldown_bars
                        position_symbol = None
                        shares = 0
                        entry_index = None
                        highest_close = 0.0
                        partial_stages = 0
                        traded = True

            can_enter = (
                position_symbol is None
                and not traded
                and not day_paused
                and day_trades < self.config.max_trades_per_day
                and self.config.entry_start_clock <= timestamp.time() < self.config.entry_cutoff_clock
            )
            if can_enter:
                candidate = self._best_candidate(
                    timestamp,
                    time_idx,
                    by_symbol,
                    prev_close,
                    cooldown_until,
                    vi_until,
                )
                if candidate and candidate.symbol in bar_by_symbol:
                    current_bar = bar_by_symbol[candidate.symbol]
                    bought, cash, avg_cost = self._buy(current_bar, cash, trades, "scanner_breakout")
                    if bought:
                        position_symbol = candidate.symbol
                        shares = bought
                        entry_index = time_idx
                        highest_close = current_bar.open
                        partial_stages = 0
                        day_trades += 1

            mark_price = latest_close.get(position_symbol, 0.0) if position_symbol else 0.0
            equity = cash + shares * mark_price
            peak = max([float(point["equity"]) for point in equity_curve], default=self.config.initial_capital)
            peak = max(peak, equity)
            equity_curve.append(
                {
                    "datetime": timestamp.isoformat(sep=" "),
                    "cash": round(cash, 2),
                    "symbol": position_symbol or "",
                    "shares": shares,
                    "mark_price": round(mark_price, 2),
                    "equity": round(equity, 2),
                    "drawdown": round((equity / peak) - 1.0 if peak else 0.0, 6),
                    "paused": int(day_paused),
                }
            )

        if position_symbol and shares > 0:
            last_bar = by_symbol[position_symbol][-1]
            cash, avg_cost = self._sell(last_bar, "SELL_ALL", shares, cash, avg_cost, trades, "final_close", "close")
            equity_curve[-1]["cash"] = round(cash, 2)
            equity_curve[-1]["symbol"] = ""
            equity_curve[-1]["shares"] = 0
            equity_curve[-1]["equity"] = round(cash, 2)

        return ScannerResult(metrics=self._metrics(bars, trades, equity_curve), trades=trades, equity_curve=equity_curve)

    def _best_candidate(
        self,
        timestamp: datetime,
        time_idx: int,
        by_symbol: dict[str, list[StockBar]],
        prev_close: dict[tuple[str, date], float],
        cooldown_until: dict[str, int],
        vi_until: dict[str, int],
    ) -> Optional[StockBar]:
        candidates: list[tuple[float, StockBar]] = []
        session = timestamp.date()
        top_symbols = self._top_value_symbols(timestamp, by_symbol)
        for symbol in top_symbols:
            if time_idx <= cooldown_until.get(symbol, -1) or time_idx <= vi_until.get(symbol, -1):
                continue
            symbol_bars = by_symbol[symbol]
            signal_idx = _bar_index_before_time(symbol_bars, timestamp)
            if signal_idx is None:
                continue
            signal_bar = symbol_bars[signal_idx]
            if signal_bar.session != session:
                continue
            session_bars = _session_bars_until(symbol_bars, signal_idx)
            if not self._passes_filters(signal_bar, session_bars, prev_close.get((symbol, session))):
                continue
            atr_pct = _atr_pct(session_bars, self.config.atr_period) or 0.0
            value_score = sum(bar.value for bar in session_bars)
            momentum = (signal_bar.close / session_bars[0].open) - 1.0
            score = (momentum * 100.0) + (atr_pct * 10.0) + math.log10(max(value_score, 1.0))
            candidates.append((score, signal_bar))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _top_value_symbols(self, timestamp: datetime, by_symbol: dict[str, list[StockBar]]) -> list[str]:
        values: list[tuple[float, str]] = []
        session = timestamp.date()
        for symbol, symbol_bars in by_symbol.items():
            total = 0.0
            for bar in symbol_bars:
                if bar.timestamp >= timestamp:
                    break
                if bar.session == session:
                    total += bar.value
            if total > 0:
                values.append((total, symbol))
        values.sort(reverse=True)
        return [symbol for _, symbol in values[: self.config.top_value_rank]]

    def _passes_filters(self, bar: StockBar, session_bars: list[StockBar], previous_close: Optional[float]) -> bool:
        if self.config.exclude_warning and bar.warning:
            return False
        if previous_close is None or previous_close <= 0:
            return False
        session_start = session_bars[0].timestamp
        if bar.timestamp < session_start + timedelta(minutes=self.config.observation_minutes):
            return False

        setup_move = (bar.close / previous_close) - 1.0
        if not (self.config.gap_min_pct <= setup_move <= self.config.gap_max_pct):
            return False

        spread = bar.spread_pct
        if spread is None:
            if self.config.require_spread:
                return False
        elif spread > self.config.max_spread_pct:
            return False

        closes = [item.close for item in session_bars]
        previous_volumes = [float(item.volume) for item in session_bars[:-1]]
        if len(previous_volumes) < self.config.volume_sma:
            return False
        volume_avg = rolling_mean(previous_volumes, self.config.volume_sma)
        if volume_avg[-1] is None or bar.volume < float(volume_avg[-1]) * self.config.volume_factor:
            return False

        atr_pct = _atr_pct(session_bars, self.config.atr_period)
        if atr_pct is None or not (self.config.min_atr_pct <= atr_pct <= self.config.max_atr_pct):
            return False

        vwap = _vwap(session_bars)[-1]
        if vwap is None:
            return False
        extension = (bar.close / vwap) - 1.0
        required_edge = self.config.round_trip_cost_rate + self.config.min_edge_rate
        opening_high = max(item.high for item in session_bars if item.timestamp < session_start + timedelta(minutes=self.config.observation_minutes))
        return (
            bar.close > opening_high * (1.0 + required_edge)
            and bar.close > vwap
            and extension <= self.config.max_extension_pct
            and closes[-1] > closes[max(0, len(closes) - 4)]
        )

    def _exit_reason(self, bar: StockBar, avg_cost: float, highest_close: float, holding_bars: int) -> Optional[str]:
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

    def _buy(self, bar: StockBar, cash: float, trades: list[ScannerTrade], reason: str) -> tuple[int, float, float]:
        risk_budget = cash * self.config.risk_per_trade_pct
        risk_cap = risk_budget / self.config.stop_loss_pct
        position_cap = cash * self.config.max_position_pct
        budget = min(cash, risk_cap, position_cap)
        price = bar.open * (1.0 + self.config.slippage_rate)
        cost_per_share = price * (1.0 + self.config.commission_rate)
        shares = math.floor(budget / cost_per_share)
        if shares <= 0:
            return 0, cash, 0.0
        gross = shares * price
        commission = gross * self.config.commission_rate
        total_cost = gross + commission
        new_cash = cash - total_cost
        avg_cost = total_cost / shares
        trades.append(
            ScannerTrade(
                timestamp=bar.timestamp,
                action="BUY",
                symbol=bar.symbol,
                shares=shares,
                price=round(price, 4),
                gross=round(gross, 2),
                cost=round(commission, 2),
                realized_pnl=0.0,
                cash_after=round(new_cash, 2),
                reason=reason,
            )
        )
        return shares, new_cash, avg_cost

    def _sell(
        self,
        bar: StockBar,
        action: str,
        shares: int,
        cash: float,
        avg_cost: float,
        trades: list[ScannerTrade],
        reason: str,
        price_source: str = "open",
    ) -> tuple[float, float]:
        raw_price = bar.close if price_source == "close" else bar.open
        price = raw_price * (1.0 - self.config.slippage_rate)
        gross = shares * price
        commission = gross * self.config.commission_rate
        tax = gross * self.config.sell_tax_rate
        net = gross - commission - tax
        realized_pnl = net - (avg_cost * shares)
        new_cash = cash + net
        trades.append(
            ScannerTrade(
                timestamp=bar.timestamp,
                action=action,
                symbol=bar.symbol,
                shares=shares,
                price=round(price, 4),
                gross=round(gross, 2),
                cost=round(commission + tax, 2),
                realized_pnl=round(realized_pnl, 2),
                cash_after=round(new_cash, 2),
                reason=reason,
            )
        )
        return new_cash, 0.0

    def _metrics(self, bars: list[StockBar], trades: list[ScannerTrade], equity_curve: list[dict[str, Any]]) -> dict[str, Any]:
        final_equity = float(equity_curve[-1]["equity"])
        total_return = (final_equity / self.config.initial_capital) - 1.0
        max_drawdown = min(float(point["drawdown"]) for point in equity_curve)
        sell_trades = [trade for trade in trades if trade.action.startswith("SELL")]
        winning_sells = [trade for trade in sell_trades if trade.realized_pnl > 0]
        daily_returns = _daily_close_returns(equity_curve)
        return {
            "strategy": "volatile_stock_scanner",
            "symbols": len({bar.symbol for bar in bars}),
            "sessions": len({bar.session for bar in bars}),
            "start_datetime": bars[0].timestamp.isoformat(sep=" "),
            "end_datetime": bars[-1].timestamp.isoformat(sep=" "),
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


def _parse_clock(value: str, fallback: time) -> time:
    value = str(value or "").strip()
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return fallback


def _optional_float(value: Optional[str]) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y"}


def _group_by_symbol(bars: list[StockBar]) -> dict[str, list[StockBar]]:
    grouped: dict[str, list[StockBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    return grouped


def _group_by_time(bars: list[StockBar]) -> dict[datetime, list[StockBar]]:
    grouped: dict[datetime, list[StockBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.timestamp, []).append(bar)
    return grouped


def _previous_session_close(by_symbol: dict[str, list[StockBar]]) -> dict[tuple[str, date], float]:
    result: dict[tuple[str, date], float] = {}
    for symbol, bars in by_symbol.items():
        last_by_session: dict[date, float] = {}
        for bar in bars:
            last_by_session[bar.session] = bar.close
        sessions = sorted(last_by_session)
        for idx in range(1, len(sessions)):
            result[(symbol, sessions[idx])] = last_by_session[sessions[idx - 1]]
    return result


def _bar_index_before_time(bars: list[StockBar], timestamp: datetime) -> Optional[int]:
    index = None
    for idx, bar in enumerate(bars):
        if bar.timestamp >= timestamp:
            break
        index = idx
    return index


def _last_bar_before_or_at(bars: list[StockBar], timestamp: datetime) -> StockBar:
    previous = bars[0]
    for bar in bars:
        if bar.timestamp > timestamp:
            break
        previous = bar
    return previous


def _session_bars_until(bars: list[StockBar], idx: int) -> list[StockBar]:
    session = bars[idx].session
    start = idx
    while start > 0 and bars[start - 1].session == session:
        start -= 1
    return bars[start : idx + 1]


def _vwap(bars: list[StockBar]) -> list[Optional[float]]:
    values: list[Optional[float]] = []
    cumulative_value = 0.0
    cumulative_volume = 0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        cumulative_value += typical * bar.volume
        cumulative_volume += bar.volume
        values.append(cumulative_value / cumulative_volume if cumulative_volume else None)
    return values


def _atr_pct(bars: list[StockBar], period: int) -> Optional[float]:
    if len(bars) < period:
        return None
    atr = average_true_range(
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
        period,
    )[-1]
    if atr is None or bars[-1].close <= 0:
        return None
    return atr / bars[-1].close


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
