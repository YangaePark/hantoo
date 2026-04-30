from __future__ import annotations

import csv
import json
import math
import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from semibot_backtester.stock_scanner import StockBar, StockScannerConfig, StockScannerBacktester

from .kis import KisClient, KisCredentials, parse_overseas_price_response, parse_price_response, parse_rank_rows, rank_row_symbol


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path(os.environ.get("SEMIBOT_STATE_ROOT", ROOT)).resolve()
DEFAULT_MARKET = "domestic"
OVERSEAS_MARKET = "overseas"
SUPPORTED_MARKETS = {DEFAULT_MARKET, OVERSEAS_MARKET}
LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.local.json"
KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.local.json"
LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading"
OVERSEAS_LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.overseas.local.json"
OVERSEAS_KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.overseas.local.json"
OVERSEAS_LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading_overseas"
NASDAQ_PRICE_EXCHANGE_CODE = "NAS"
NASDAQ_ORDER_EXCHANGE_CODE = "NASD"
OVERSEAS_MIN_PRICE = 5.0
OVERSEAS_MIN_TRADE_VALUE = 20_000_000.0
OVERSEAS_PREMARKET_MIN_TRADE_VALUE = 2_000_000.0
NEW_YORK_TZ = ZoneInfo("America/New_York")
OVERSEAS_FALLBACK_SYMBOLS = [
    "AAPL",
    "NVDA",
    "MSFT",
    "AMZN",
    "META",
    "GOOGL",
    "AVGO",
    "AMD",
    "TSLA",
    "NFLX",
    "COST",
    "ADBE",
    "INTC",
    "CSCO",
    "PEP",
    "QCOM",
    "AMAT",
    "TXN",
]
SESSION_PREMARKET = "premarket"
SESSION_REGULAR = "regular"
SESSION_CLOSED = "closed"


@dataclass
class LiveConfig:
    market: str = DEFAULT_MARKET
    mode: str = "paper"
    account_no: str = ""
    product_code: str = "01"
    symbol: str = ""
    exchange_code: str = "NASD"
    price_exchange_code: str = "NAS"
    currency: str = "USD"
    seed_capital: float = 1_000_000.0
    seed_source: str = "manual"
    auto_start: bool = False
    auto_select: bool = True
    poll_interval_sec: int = 10
    bar_minutes: int = 5
    max_symbols: int = 20
    selection_refresh_sec: int = 300
    min_selection_hold_sec: int = 1800
    min_bars_before_evaluate: int = 20
    candidate_pool_size: int = 60
    clock_offset_hours: int = 0
    overseas_premarket_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveConfig":
        market = _market(data.get("market", DEFAULT_MARKET))
        default_clock_offset = -7 if market == OVERSEAS_MARKET else 0
        default_seed_capital = 10_000.0 if market == OVERSEAS_MARKET else 1_000_000.0
        return cls(
            market=market,
            mode=data.get("mode", "paper"),
            account_no=data.get("account_no", ""),
            product_code=data.get("product_code", "01"),
            symbol="",
            exchange_code=NASDAQ_ORDER_EXCHANGE_CODE,
            price_exchange_code=NASDAQ_PRICE_EXCHANGE_CODE,
            currency=str(data.get("currency", "USD")).strip().upper() or "USD",
            seed_capital=_positive_float(data.get("seed_capital"), default_seed_capital),
            seed_source=_seed_source(data.get("seed_source", "manual")),
            auto_start=_truthy(data.get("auto_start")),
            auto_select=True,
            poll_interval_sec=int(data.get("poll_interval_sec", 10)),
            bar_minutes=int(data.get("bar_minutes", 5)),
            max_symbols=int(data.get("max_symbols", 20)),
            selection_refresh_sec=max(300, int(data.get("selection_refresh_sec", 300))),
            min_selection_hold_sec=max(1800, int(data.get("min_selection_hold_sec", 1800))),
            min_bars_before_evaluate=max(1, int(data.get("min_bars_before_evaluate", 20))),
            candidate_pool_size=int(data.get("candidate_pool_size", 60)),
            clock_offset_hours=int(data.get("clock_offset_hours", default_clock_offset)),
            overseas_premarket_enabled=_truthy(data.get("overseas_premarket_enabled")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "mode": self.mode,
            "account_no": self.account_no,
            "product_code": self.product_code,
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "price_exchange_code": self.price_exchange_code,
            "currency": self.currency,
            "seed_capital": self.seed_capital,
            "seed_source": self.seed_source,
            "auto_start": self.auto_start,
            "auto_select": self.auto_select,
            "poll_interval_sec": self.poll_interval_sec,
            "bar_minutes": self.bar_minutes,
            "max_symbols": self.max_symbols,
            "selection_refresh_sec": self.selection_refresh_sec,
            "min_selection_hold_sec": self.min_selection_hold_sec,
            "min_bars_before_evaluate": self.min_bars_before_evaluate,
            "candidate_pool_size": self.candidate_pool_size,
            "clock_offset_hours": self.clock_offset_hours,
            "overseas_premarket_enabled": self.overseas_premarket_enabled,
        }


class LiveTrader:
    def __init__(
        self,
        config: LiveConfig,
        strategy: StockScannerConfig,
        *,
        keys_path: Path | None = None,
        report_dir: Path | None = None,
    ):
        self.config = config
        self.market = _market(config.market)
        self.strategy = strategy
        self.keys_path = keys_path or kis_keys_path(self.market)
        self.report_dir = report_dir or live_report_dir(self.market)
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.status: dict[str, Any] = {
            "running": False,
            "market": self.market,
            "mode": config.mode,
            "message": "대기 중",
            "last_tick": "",
            "last_error": "",
            "orders": 0,
            "active_symbols": [],
            "selector": _selector_label(self.market),
            "selector_message": "",
            "seed_capital": strategy.initial_capital,
            "seed_source": config.seed_source,
            "auto_start": config.auto_start,
            "symbol": config.symbol,
            "exchange_code": config.exchange_code,
            "price_exchange_code": config.price_exchange_code,
            "currency": config.currency,
            "session": "",
            "session_label": "",
            "overseas_premarket_enabled": config.overseas_premarket_enabled,
            "trade_message": "매수 조건 대기",
        }
        self.bars: list[StockBar] = []
        self.seeded_previous_close: set[str] = set()
        self.active_symbols: list[str] = []
        self.selected_since: dict[str, float] = {}
        self.last_selection_at = 0.0
        self.regular_reset_dates: set[object] = set()
        self.position: dict[str, Any] | None = None
        self.cash = strategy.initial_capital
        self.day_start_cash = strategy.initial_capital
        ensure_live_report(self.report_dir, strategy_name=_strategy_name(self.market))

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            data = dict(self.status)
            data["position"] = self.position or {}
            data["cash"] = round(self.cash, 2)
            data["seed_capital"] = round(self.strategy.initial_capital, 2)
            data["seed_source"] = self.config.seed_source
            data["auto_start"] = self.config.auto_start
            data["active_symbols"] = list(self.active_symbols)
            return data

    def _loop(self) -> None:
        with self.lock:
            self.status.update({"running": True, "message": "실행 중"})
        try:
            client = KisClient(KisCredentials.from_file(self.keys_path), credentials_path=self.keys_path)
            while self.running:
                now = datetime.now()
                try:
                    self._run_cycle(client, now)
                    time.sleep(max(1, self.config.poll_interval_sec))
                except Exception as exc:  # noqa: BLE001
                    self._record_retriable_error(exc, now)
                    time.sleep(max(5, min(60, self.config.poll_interval_sec * 2)))
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.status.update({"last_error": str(exc), "message": "오류"})
        finally:
            with self.lock:
                self.status["running"] = False
            self.running = False

    def _run_cycle(self, client: KisClient, now: datetime) -> None:
        strategy_now = self._strategy_now(now)
        session = self._market_session(strategy_now)
        if self.market == OVERSEAS_MARKET and session == SESSION_CLOSED:
            self._set_market_wait_status(now, strategy_now)
            return
        self._reset_premarket_bars_for_regular_if_flat(strategy_now, session)

        should_select = not self.active_symbols or (
            self.config.auto_select and time.time() - self.last_selection_at >= self.config.selection_refresh_sec
        )
        if should_select:
            self.active_symbols = self._select_symbols(client)
        for symbol in self.active_symbols:
            parsed = self._fetch_price(client, symbol)
            if parsed["price"] <= 0:
                continue
            self._add_tick(symbol, strategy_now, parsed)
        self._evaluate(client, strategy_now)
        with self.lock:
            self.status.update(
                {
                    "last_tick": now.isoformat(sep=" ", timespec="seconds"),
                    "message": "실행 중",
                    "last_error": "",
                    "active_symbols": list(self.active_symbols),
                    "session": session,
                    "session_label": _session_label(session),
                }
            )

    def _set_market_wait_status(self, now: datetime, strategy_now: datetime) -> None:
        message = "프리장 비활성화: 09:30 본장 대기"
        if self.config.overseas_premarket_enabled:
            message = "해외장 대기: 프리장 04:00 시작"
            if strategy_now.time() >= clock_time(16, 0):
                message = "해외장 종료: 다음 프리장 대기"
        with self.lock:
            self.status.update(
                {
                    "last_tick": now.isoformat(sep=" ", timespec="seconds"),
                    "message": "해외장 대기",
                    "last_error": "",
                    "selector_message": message,
                    "active_symbols": list(self.active_symbols),
                    "session": SESSION_CLOSED,
                    "session_label": "해외장 대기",
                }
            )
        self._set_trade_message(message)

    def _record_retriable_error(self, exc: Exception, now: datetime) -> None:
        with self.lock:
            self.status.update(
                {
                    "running": True,
                    "last_error": str(exc),
                    "last_tick": now.isoformat(sep=" ", timespec="seconds"),
                    "message": "통신 오류 재시도 대기",
                    "active_symbols": list(self.active_symbols),
                }
            )
        self._set_trade_message("통신 오류로 다음 주기에 재시도")

    def _initial_symbols(self, client: KisClient) -> list[str]:
        if self.market == OVERSEAS_MARKET:
            return self._select_symbols(client)
        return self._select_symbols(client)

    def _select_symbols(self, client: KisClient) -> list[str]:
        now_ts = time.time()
        self.last_selection_at = now_ts
        candidates = self._candidate_symbols(client)
        ranked: list[tuple[float, str]] = []
        candidate_items = sorted(candidates.items(), key=lambda item: _source_priority(item[1]), reverse=True)
        for symbol, row in candidate_items[: self.config.candidate_pool_size]:
            parsed = self._fetch_price(client, symbol)
            if not self._passes_live_candidate(parsed, row):
                continue
            score = self._live_candidate_score(parsed, row)
            ranked.append((score, symbol))
            time.sleep(0.08 if self.market == OVERSEAS_MARKET else 0.04)
        ranked.sort(reverse=True)
        fresh_selected = [symbol for _, symbol in ranked[: self.config.max_symbols]]
        selected = self._merge_selected_symbols(fresh_selected, now_ts)
        with self.lock:
            market_label = "NASDAQ 자동선별" if self.market == OVERSEAS_MARKET else "자동선별"
            if self.market == OVERSEAS_MARKET and self._market_session(self._strategy_now(datetime.now())) == SESSION_PREMARKET:
                market_label = "프리장 NASDAQ 자동선별"
            hold_minutes = max(1, round(self.config.min_selection_hold_sec / 60))
            self.status["selector_message"] = f"{market_label} {len(selected)}종목 / 후보 {len(candidates)}종목 / 유지 {hold_minutes}분"
            self.status["active_symbols"] = selected
        return selected

    def _fetch_price(self, client: KisClient, symbol: str) -> dict[str, float]:
        if self.market == OVERSEAS_MARKET:
            price_data = client.inquire_overseas_price(self.config.price_exchange_code, symbol)
            return parse_overseas_price_response(price_data)
        price_data = client.inquire_price(symbol)
        return parse_price_response(price_data)

    def _strategy_now(self, now: datetime) -> datetime:
        if self.market == OVERSEAS_MARKET:
            return datetime.now(NEW_YORK_TZ).replace(tzinfo=None)
        if not self.config.clock_offset_hours:
            return now
        return now + timedelta(hours=self.config.clock_offset_hours)

    def _market_session(self, now: datetime) -> str:
        if self.market != OVERSEAS_MARKET:
            return SESSION_REGULAR
        current = now.time()
        if clock_time(9, 30) <= current < clock_time(16, 0):
            return SESSION_REGULAR
        if self.config.overseas_premarket_enabled and clock_time(4, 0) <= current < clock_time(9, 30):
            return SESSION_PREMARKET
        return SESSION_CLOSED

    def _reset_premarket_bars_for_regular_if_flat(self, now: datetime, session: str) -> None:
        if self.market != OVERSEAS_MARKET or not self.config.overseas_premarket_enabled:
            return
        if session != SESSION_REGULAR or self.position:
            return
        if now.date() in self.regular_reset_dates:
            return
        cutoff = clock_time(9, 30)
        self.bars = [bar for bar in self.bars if bar.session != now.date() or bar.timestamp.time() >= cutoff]
        self.regular_reset_dates.add(now.date())

    def _merge_selected_symbols(self, fresh_selected: list[str], now_ts: float) -> list[str]:
        kept = [
            symbol
            for symbol in self.active_symbols
            if now_ts - self.selected_since.get(symbol, now_ts) < self.config.min_selection_hold_sec
        ]
        selected: list[str] = []
        for symbol in kept + fresh_selected:
            if symbol not in selected and len(selected) < self.config.max_symbols:
                selected.append(symbol)
        for symbol in selected:
            self.selected_since.setdefault(symbol, now_ts)
        self.selected_since = {symbol: since for symbol, since in self.selected_since.items() if symbol in selected}
        return selected

    def _candidate_symbols(self, client: KisClient) -> dict[str, dict[str, Any]]:
        if self.market == OVERSEAS_MARKET:
            return self._overseas_candidate_symbols(client)
        rows: list[tuple[str, dict[str, Any]]] = []
        responses = [
            ("trade_value", client.volume_rank(sort_code="3", min_volume="0")),
            ("volume_surge", client.volume_rank(sort_code="1", min_volume="0")),
            ("gap_up", client.fluctuation_rank(min_rate=str(int(self.strategy.gap_min_pct * 100)), max_rate="30", count="80")),
            ("strength", client.volume_power_rank()),
        ]
        for source, response in responses:
            rows.extend((source, row) for row in parse_rank_rows(response))

        candidates: dict[str, dict[str, Any]] = {}
        for source, row in rows:
            symbol = rank_row_symbol(row)
            if not _valid_stock_symbol(symbol):
                continue
            if _excluded_name(str(row.get("hts_kor_isnm", ""))):
                continue
            if symbol not in candidates:
                candidates[symbol] = dict(row)
                candidates[symbol]["_sources"] = [source]
                continue
            candidates[symbol].update({key: value for key, value in row.items() if value not in {"", None}})
            candidates[symbol].setdefault("_sources", []).append(source)
        return candidates

    def _overseas_candidate_symbols(self, client: KisClient) -> dict[str, dict[str, Any]]:
        exchange_code = NASDAQ_PRICE_EXCHANGE_CODE
        rows: list[tuple[str, dict[str, Any]]] = []
        responses = [
            ("trade_value", client.overseas_trade_value_rank(exchange_code=exchange_code)),
            ("volume", client.overseas_trade_volume_rank(exchange_code=exchange_code)),
            ("gap_up", client.overseas_updown_rate_rank(exchange_code=exchange_code, gubn="1")),
            ("volume_surge", client.overseas_volume_surge_rank(exchange_code=exchange_code)),
            ("strength", client.overseas_volume_power_rank(exchange_code=exchange_code)),
        ]
        for source, response in responses:
            rows.extend((source, row) for row in parse_rank_rows(response))

        candidates: dict[str, dict[str, Any]] = {}
        for source, row in rows:
            symbol = _normalize_overseas_symbol(rank_row_symbol(row))
            if not _valid_overseas_symbol(symbol):
                continue
            name = _row_name(row)
            if _excluded_overseas_name(name, symbol):
                continue
            if symbol not in candidates:
                candidates[symbol] = dict(row)
                candidates[symbol]["_sources"] = [source]
                continue
            candidates[symbol].update({key: value for key, value in row.items() if value not in {"", None}})
            candidates[symbol].setdefault("_sources", []).append(source)
        if not candidates and self.config.overseas_premarket_enabled:
            for symbol in OVERSEAS_FALLBACK_SYMBOLS:
                candidates[symbol] = {
                    "symb": symbol,
                    "_sources": ["fallback"],
                    "vol_inrt": "220",
                }
        return candidates

    def _passes_live_candidate(self, parsed: dict[str, float], row: dict[str, Any]) -> bool:
        strategy = self._active_strategy(self._strategy_now(datetime.now()))
        price = parsed["price"]
        if price <= 0:
            return False
        if self.market == OVERSEAS_MARKET and price < OVERSEAS_MIN_PRICE:
            return False
        gap = parsed["prev_rate_pct"] / 100.0
        if not (strategy.gap_min_pct <= gap <= strategy.gap_max_pct):
            return False
        day_range = ((parsed["high"] - parsed["low"]) / price) if price else 0.0
        if day_range < strategy.min_atr_pct:
            return False
        avg_volume = _float(row.get("avrg_vol"))
        volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else _float(row.get("vol_inrt")) / 100.0
        sources = set(row.get("_sources", []))
        if volume_surge < strategy.volume_factor and "volume_surge" not in sources:
            return False
        trade_value = parsed["value"] or _row_trade_value(row)
        threshold = self._trade_value_threshold()
        return trade_value >= threshold or "trade_value" in sources

    def _live_candidate_score(self, parsed: dict[str, float], row: dict[str, Any]) -> float:
        price = parsed["price"] or 1.0
        day_range = max(0.0, (parsed["high"] - parsed["low"]) / price)
        gap = max(0.0, parsed["prev_rate_pct"] / 100.0)
        trade_value = max(parsed["value"], _row_trade_value(row), 1.0)
        avg_volume = _row_average_volume(row)
        volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else max(0.0, _row_volume_surge(row))
        strength = max(0.0, _row_strength(row))
        source_bonus = _source_priority(row) * (0.35 if self.market == OVERSEAS_MARKET else 0.0)
        return (math.log10(trade_value) * 1.5) + (gap * 100.0) + (day_range * 120.0) + min(volume_surge, 8.0) + strength + source_bonus

    def _trade_value_threshold(self) -> float:
        if self.market != OVERSEAS_MARKET:
            return 1_000_000_000
        if self._market_session(self._strategy_now(datetime.now())) == SESSION_PREMARKET:
            return OVERSEAS_PREMARKET_MIN_TRADE_VALUE
        return OVERSEAS_MIN_TRADE_VALUE

    def _add_tick(self, symbol: str, now: datetime, parsed: dict[str, float]) -> None:
        self._seed_previous_close(symbol, now, parsed)
        minute_bucket = now.replace(minute=(now.minute // self.config.bar_minutes) * self.config.bar_minutes, second=0, microsecond=0)
        existing = next((bar for bar in reversed(self.bars) if bar.symbol == symbol and bar.timestamp == minute_bucket), None)
        volume = int(parsed["volume"])
        if existing:
            self.bars.remove(existing)
            volume = max(existing.volume, volume)
            bar = StockBar(
                symbol=symbol,
                timestamp=minute_bucket,
                open=existing.open,
                high=max(existing.high, parsed["price"]),
                low=min(existing.low, parsed["price"]),
                close=parsed["price"],
                volume=volume,
            )
        else:
            bar = StockBar(
                symbol=symbol,
                timestamp=minute_bucket,
                open=parsed["open"] or parsed["price"],
                high=max(parsed["high"], parsed["price"]),
                low=min(parsed["low"] or parsed["price"], parsed["price"]),
                close=parsed["price"],
                volume=volume,
            )
        self.bars.append(bar)
        self.bars = self.bars[-5000:]

    def _seed_previous_close(self, symbol: str, now: datetime, parsed: dict[str, float]) -> None:
        if symbol in self.seeded_previous_close:
            return
        prev_rate = parsed.get("prev_rate_pct", 0.0)
        price = parsed.get("price", 0.0)
        if price <= 0 or prev_rate <= -99.0:
            return
        previous_close = price / (1.0 + (prev_rate / 100.0)) if prev_rate else price
        previous_timestamp = datetime.combine(now.date() - timedelta(days=1), clock_time(15, 30))
        self.bars.append(
            StockBar(
                symbol=symbol,
                timestamp=previous_timestamp,
                open=previous_close,
                high=previous_close,
                low=previous_close,
                close=previous_close,
                volume=1,
            )
        )
        self.seeded_previous_close.add(symbol)

    def _evaluate(self, client: KisClient, now: datetime) -> None:
        if len(self.bars) < self.config.min_bars_before_evaluate:
            self._set_trade_message(f"5분봉 데이터 수집 중 ({len(self.bars)}/{self.config.min_bars_before_evaluate})")
            return
        strategy = self._active_strategy(now)
        result = StockScannerBacktester(strategy).run(self.bars)
        latest_trade = result.trades[-1] if result.trades else None
        if not latest_trade:
            self._set_trade_message(self._entry_wait_message(now))
            _write_live_metrics(result.metrics, self.report_dir)
            return
        last_recorded = _last_trade_key(self.report_dir)
        trade_key = f"{latest_trade.timestamp}|{latest_trade.action}|{latest_trade.symbol}|{latest_trade.shares}|{latest_trade.reason}"
        if trade_key == last_recorded:
            self._set_trade_message("최근 신호는 이미 기록됨")
            return
        live = self.config.mode == "live"
        if latest_trade.action == "BUY":
            response = self._place_order(client, "buy", latest_trade.symbol, latest_trade.shares, live, latest_trade.price)
            if not _order_succeeded(response, live):
                self._set_trade_message(f"주문 실패: BUY {latest_trade.symbol} ({_order_message(response)})")
                return
            self.position = {"symbol": latest_trade.symbol, "shares": latest_trade.shares, "entry_price": latest_trade.price}
        else:
            response = self._place_order(client, "sell", latest_trade.symbol, latest_trade.shares, live, latest_trade.price)
            if not _order_succeeded(response, live):
                self._set_trade_message(f"주문 실패: SELL {latest_trade.symbol} ({_order_message(response)})")
                return
            self.position = None
        self.cash = float(latest_trade.cash_after)
        _append_live_trade(latest_trade, response, self.config.mode, trade_key, self.report_dir)
        _write_live_equity(result.equity_curve, self.report_dir)
        _write_live_metrics(result.metrics, self.report_dir)
        with self.lock:
            self.status["orders"] = int(self.status.get("orders", 0)) + 1
            self.status["trade_message"] = f"최근 주문: {latest_trade.action} {latest_trade.symbol} {latest_trade.shares}주 ({latest_trade.reason})"

    def _set_trade_message(self, message: str) -> None:
        with self.lock:
            self.status["trade_message"] = message

    def _entry_wait_message(self, now: datetime) -> str:
        if not self.active_symbols:
            return "자동선별 종목 없음"
        strategy = self._active_strategy(now)
        if self.market == OVERSEAS_MARKET and self._market_session(now) == SESSION_PREMARKET:
            prefix = "프리장 "
        else:
            prefix = ""
        if now.time() >= strategy.force_exit_clock:
            return f"{strategy.force_exit_time} 이후 신규 진입 중단"

        messages: list[str] = []
        for symbol in self.active_symbols[:3]:
            reason = self._symbol_entry_reason(symbol, now)
            if reason:
                messages.append(f"{symbol}: {reason}")
        return f"{prefix}{' / '.join(messages)}" if messages else f"{prefix}매수 조건 대기"

    def _active_strategy(self, now: datetime) -> StockScannerConfig:
        if self.market == OVERSEAS_MARKET and self._market_session(now) == SESSION_PREMARKET:
            return replace(
                self.strategy,
                observation_minutes=30,
                top_value_rank=max(3, self.strategy.top_value_rank),
                gap_min_pct=0.015,
                gap_max_pct=0.12,
                volume_sma=5,
                volume_factor=2.2,
                min_atr_pct=0.006,
                max_atr_pct=0.08,
                max_spread_pct=0.006,
                min_edge_bps=50.0,
                max_extension_pct=0.035,
                risk_per_trade_pct=min(self.strategy.risk_per_trade_pct, 0.006),
                max_position_pct=min(self.strategy.max_position_pct, 0.5),
                stop_loss_pct=max(self.strategy.stop_loss_pct, 0.015),
                take_profit_pct=max(self.strategy.take_profit_pct, 0.03),
                trailing_stop_pct=max(self.strategy.trailing_stop_pct, 0.014),
                daily_stop_loss_pct=min(self.strategy.daily_stop_loss_pct, 0.025),
                max_trades_per_day=min(self.strategy.max_trades_per_day, 3),
            )
        return self.strategy

    def _symbol_entry_reason(self, symbol: str, now: datetime) -> str:
        strategy = self._active_strategy(now)
        symbol_bars = sorted((bar for bar in self.bars if bar.symbol == symbol), key=lambda bar: bar.timestamp)
        if not symbol_bars:
            return "현재가 수집 대기"
        current_bars = [bar for bar in symbol_bars if bar.session == now.date()]
        if not current_bars:
            return "오늘 5분봉 수집 대기"

        latest = current_bars[-1]
        previous_close = _previous_close_for(symbol_bars, latest)
        if previous_close <= 0:
            return "전일 종가 기준값 대기"

        session_start = current_bars[0].timestamp
        if latest.timestamp < session_start + timedelta(minutes=strategy.observation_minutes):
            elapsed_minutes = max(0, int((latest.timestamp - session_start).total_seconds() // 60))
            return f"진입 전 관찰 중 ({elapsed_minutes}/{strategy.observation_minutes}분)"

        gap = (current_bars[0].open / previous_close) - 1.0
        if gap < strategy.gap_min_pct:
            return f"갭 {gap * 100:.1f}% < {strategy.gap_min_pct * 100:.1f}%"
        if gap > strategy.gap_max_pct:
            return f"갭 {gap * 100:.1f}% > {strategy.gap_max_pct * 100:.1f}%"

        previous_volumes = [float(bar.volume) for bar in current_bars[:-1]]
        if len(previous_volumes) < strategy.volume_sma:
            return f"거래량 평균 계산용 봉 부족 ({len(previous_volumes)}/{strategy.volume_sma})"
        volume_avg = sum(previous_volumes[-strategy.volume_sma :]) / strategy.volume_sma
        volume_ratio = latest.volume / volume_avg if volume_avg else 0.0
        if volume_ratio < strategy.volume_factor:
            return f"거래량 {volume_ratio:.1f}배 < {strategy.volume_factor:.1f}배"

        atr_pct = _latest_atr_pct(current_bars, strategy.atr_period)
        if atr_pct is None:
            return "ATR 계산용 봉 부족"
        if atr_pct < strategy.min_atr_pct:
            return f"변동성 {atr_pct * 100:.1f}% < {strategy.min_atr_pct * 100:.1f}%"
        if atr_pct > strategy.max_atr_pct:
            return f"변동성 {atr_pct * 100:.1f}% > {strategy.max_atr_pct * 100:.1f}%"

        vwap = _latest_vwap(current_bars)
        if vwap <= 0:
            return "VWAP 계산 대기"
        if latest.close <= vwap:
            return "VWAP 아래"

        edge = strategy.round_trip_cost_rate + strategy.min_edge_rate
        opening_cutoff = session_start + timedelta(minutes=strategy.observation_minutes)
        opening_bars = [bar for bar in current_bars if bar.timestamp < opening_cutoff]
        if not opening_bars:
            return "관찰구간 고가 기준 대기"
        opening_high = max(bar.high for bar in opening_bars)
        if latest.close <= opening_high * (1.0 + edge):
            return "관찰구간 고가 미돌파"

        extension = (latest.close / vwap) - 1.0
        if extension > strategy.max_extension_pct:
            return f"VWAP 이격 {extension * 100:.1f}% > {strategy.max_extension_pct * 100:.1f}%"

        lookback_idx = max(0, len(current_bars) - 4)
        if latest.close <= current_bars[lookback_idx].close:
            return "최근 모멘텀 부족"
        return "매수 직전 조건 대기"

    def _place_order(self, client: KisClient, side: str, symbol: str, quantity: int, live: bool, price: float) -> dict[str, Any]:
        if self.config.mode == "paper":
            return {"rt_cd": "0", "msg1": "paper order recorded"}
        if not self.config.account_no:
            return {"rt_cd": "-1", "msg1": "account_no is required"}
        if self.market == OVERSEAS_MARKET:
            return client.order_overseas(
                account_no=self.config.account_no,
                product_code=self.config.product_code,
                exchange_code=self.config.exchange_code,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                live=live,
            )
        return client.order_cash(
            account_no=self.config.account_no,
            product_code=self.config.product_code,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=0,
            order_division="01",
            live=live,
        )


_TRADERS: dict[str, LiveTrader] = {}


def load_live_config(market: str = DEFAULT_MARKET) -> LiveConfig:
    market = _market(market)
    path = live_config_path(market)
    if not path.exists():
        return LiveConfig.from_dict({"market": market})
    data = json.loads(path.read_text(encoding="utf-8"))
    data["market"] = market
    return LiveConfig.from_dict(data)


def save_live_config(config: LiveConfig, market: str | None = None) -> None:
    market = _market(market or config.market)
    config = LiveConfig.from_dict({**config.to_dict(), "market": market})
    path = live_config_path(market)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def start_live_trader(strategy: StockScannerConfig, market: str = DEFAULT_MARKET) -> dict[str, Any]:
    market = _market(market)
    config = load_live_config(market)
    if config.mode == "live" and (not config.account_no or not config.product_code):
        return {"running": False, "message": "LIVE 모드는 계좌번호와 상품코드가 필요합니다."}
    keys_path = kis_keys_path(market)
    if not keys_path.exists():
        return {"running": False, "message": f"{_market_label(market)} KIS 키가 저장되어 있지 않습니다."}
    existing = _TRADERS.get(market)
    if existing:
        existing.stop()
    trader = LiveTrader(config, strategy, keys_path=keys_path, report_dir=live_report_dir(market))
    _TRADERS[market] = trader
    trader.start()
    return trader.snapshot()


def stop_live_trader(market: str = DEFAULT_MARKET) -> dict[str, Any]:
    market = _market(market)
    trader = _TRADERS.get(market)
    if trader:
        trader.stop()
        return trader.snapshot()
    return _idle_status(market)


def live_status(market: str = DEFAULT_MARKET) -> dict[str, Any]:
    market = _market(market)
    trader = _TRADERS.get(market)
    if trader:
        return trader.snapshot()
    return _idle_status(market)


def ensure_live_report(report_dir: Path | None = None, *, strategy_name: str = "live_volatile_stock_scanner") -> None:
    report_dir = report_dir or LIVE_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    trades_path = report_dir / "trades.csv"
    if not trades_path.exists():
        with trades_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["timestamp", "action", "symbol", "shares", "price", "gross", "cost", "realized_pnl", "cash_after", "reason", "mode", "order_response", "trade_key"])
    metrics_path = report_dir / "metrics.json"
    if not metrics_path.exists():
        metrics_path.write_text(
            json.dumps(
                {
                    "strategy": strategy_name,
                    "initial_capital": 1_000_000,
                    "final_equity": 1_000_000,
                    "total_return_pct": 0.0,
                    "max_drawdown_pct": 0.0,
                    "trades": 0,
                    "sell_trades": 0,
                    "sell_win_rate_pct": 0.0,
                    "explicit_trade_cost": 0.0,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _append_live_trade(trade, response: dict[str, Any], mode: str, trade_key: str, report_dir: Path) -> None:
    ensure_live_report(report_dir)
    with (report_dir / "trades.csv").open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([
            trade.timestamp.isoformat(sep=" "),
            trade.action,
            trade.symbol,
            trade.shares,
            trade.price,
            trade.gross,
            trade.cost,
            trade.realized_pnl,
            trade.cash_after,
            trade.reason,
            mode,
            json.dumps(response, ensure_ascii=False),
            trade_key,
        ])


def _last_trade_key(report_dir: Path) -> str:
    path = report_dir / "trades.csv"
    if not path.exists():
        return ""
    with path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    return rows[-1].get("trade_key", "") if rows else ""


def _write_live_equity(rows: list[dict[str, Any]], report_dir: Path) -> None:
    if not rows:
        return
    with (report_dir / "equity_curve.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["datetime", "cash", "symbol", "shares", "mark_price", "equity", "drawdown", "paused"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_live_metrics(metrics: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def _idle_status(market: str = DEFAULT_MARKET) -> dict[str, Any]:
    market = _market(market)
    config = load_live_config(market)
    return {
        "running": False,
        "market": market,
        "message": "대기 중",
        "mode": config.mode,
        "selector": _selector_label(market),
        "selector_message": "시장 자동선별 대기" if market == DEFAULT_MARKET else "NASDAQ 자동선별 대기",
        "active_symbols": [],
        "orders": 0,
        "seed_capital": config.seed_capital,
        "seed_source": config.seed_source,
        "auto_start": config.auto_start,
        "symbol": config.symbol,
        "exchange_code": config.exchange_code,
        "price_exchange_code": config.price_exchange_code,
        "currency": config.currency,
        "session": "",
        "session_label": "",
        "overseas_premarket_enabled": config.overseas_premarket_enabled,
        "trade_message": "자동매매 시작 전",
    }


def _valid_stock_symbol(symbol: str) -> bool:
    return len(symbol) == 6 and symbol.isdigit()


def _valid_overseas_symbol(symbol: str) -> bool:
    symbol = str(symbol or "").strip().upper()
    return bool(symbol) and len(symbol) <= 15 and all(ch.isalnum() or ch in {".", "-"} for ch in symbol)


def _normalize_overseas_symbol(symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    for prefix in ("DNAS", "DNYS", "DAMS"):
        if symbol.startswith(prefix) and len(symbol) > len(prefix):
            return symbol[len(prefix) :]
    return symbol


def _selector_label(market: str) -> str:
    return "NASDAQ 자동선별" if _market(market) == OVERSEAS_MARKET else "자동선별"


def _session_label(session: str) -> str:
    labels = {
        SESSION_PREMARKET: "프리장",
        SESSION_REGULAR: "본장",
        SESSION_CLOSED: "해외장 대기",
    }
    return labels.get(session, "")


def _market(value: object) -> str:
    market = str(value or DEFAULT_MARKET).strip().lower()
    return market if market in SUPPORTED_MARKETS else DEFAULT_MARKET


def _market_label(market: str) -> str:
    return "해외" if _market(market) == OVERSEAS_MARKET else "국내"


def _strategy_name(market: str) -> str:
    return "live_overseas_stock_scanner" if _market(market) == OVERSEAS_MARKET else "live_volatile_stock_scanner"


def live_config_path(market: str = DEFAULT_MARKET) -> Path:
    return OVERSEAS_LIVE_CONFIG_PATH if _market(market) == OVERSEAS_MARKET else LIVE_CONFIG_PATH


def kis_keys_path(market: str = DEFAULT_MARKET) -> Path:
    return OVERSEAS_KIS_KEYS_PATH if _market(market) == OVERSEAS_MARKET else KIS_KEYS_PATH


def live_report_dir(market: str = DEFAULT_MARKET) -> Path:
    return OVERSEAS_LIVE_REPORT_DIR if _market(market) == OVERSEAS_MARKET else LIVE_REPORT_DIR


def _excluded_name(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in ("ETF", "ETN", "스팩", "SPAC"))


def _excluded_overseas_name(name: str, symbol: str) -> bool:
    upper_name = name.upper()
    upper_symbol = symbol.upper()
    name_tokens = (
        " ETF",
        " ETN",
        " FUND",
        " TRUST",
        " INDEX",
        " LEVERAGE",
        " LEVERAGED",
        " INVERSE",
        " ULTRA",
        " SHORT",
        " 2X",
        " 3X",
    )
    symbol_tokens = ("TQQQ", "SQQQ", "QQQ", "PSQ", "QLD", "QID")
    return any(token in upper_name for token in name_tokens) or upper_symbol in symbol_tokens


def _source_priority(row: dict[str, Any]) -> int:
    weights = {"trade_value": 4, "volume_surge": 4, "volume": 3, "gap_up": 3, "strength": 2, "fallback": 1}
    return sum(weights.get(source, 0) for source in set(row.get("_sources", [])))


def _row_name(row: dict[str, Any]) -> str:
    return str(
        row.get("hts_kor_isnm")
        or row.get("ovrs_item_name")
        or row.get("name")
        or row.get("knam")
        or row.get("enam")
        or row.get("prdt_name")
        or row.get("prdt_abrv_name")
        or ""
    )


def _row_trade_value(row: dict[str, Any]) -> float:
    return _first_row_float(row, ("acml_tr_pbmn", "tamt", "tr_pbmn", "trade_pbmn", "ovrs_tr_pbmn", "acml_vol_amt"))


def _row_average_volume(row: dict[str, Any]) -> float:
    return _first_row_float(row, ("avrg_vol", "avg_vol", "eavg", "vol_avg", "avol"))


def _row_volume_surge(row: dict[str, Any]) -> float:
    value = _first_row_float(row, ("vol_inrt", "vol_icdc_rate", "trdvol_inrt", "rate"))
    return value / 100.0 if value > 20.0 else value


def _row_strength(row: dict[str, Any]) -> float:
    value = _first_row_float(row, ("tday_rltv", "volume_power", "powr", "pbid_rate"))
    return value / 100.0 if value > 20.0 else value


def _order_succeeded(response: dict[str, Any], live: bool) -> bool:
    if not live:
        return True
    return str(response.get("rt_cd", "")) in {"0", ""}


def _order_message(response: dict[str, Any]) -> str:
    return str(response.get("msg1") or response.get("msg_cd") or response)


def _first_row_float(row: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        number = _float(row.get(key))
        if number:
            return number
    return 0.0


def _float(value: object) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _positive_float(value: object, default: float) -> float:
    number = _float(value)
    return number if number > 0 else default


def _seed_source(value: object) -> str:
    return "balance_max" if str(value) == "balance_max" else "manual"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _previous_close_for(symbol_bars: list[StockBar], latest: StockBar) -> float:
    previous = [bar for bar in symbol_bars if bar.session < latest.session]
    return previous[-1].close if previous else 0.0


def _latest_vwap(bars: list[StockBar]) -> float:
    value = sum(((bar.high + bar.low + bar.close) / 3.0) * bar.volume for bar in bars)
    volume = sum(bar.volume for bar in bars)
    return value / volume if volume else 0.0


def _latest_atr_pct(bars: list[StockBar], period: int) -> float | None:
    if len(bars) < period:
        return None
    true_ranges: list[float] = []
    for idx, bar in enumerate(bars):
        previous_close = bars[idx - 1].close if idx else bar.close
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    atr = sum(true_ranges[-period:]) / period
    close = bars[-1].close
    return (atr / close) if close > 0 else None
