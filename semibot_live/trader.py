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

from semibot_backtester.stock_scanner import ScannerTrade, StockBar, StockScannerConfig, StockScannerBacktester

from .kis import KisClient, KisCredentials, parse_balance_response, parse_order_response, parse_overseas_balance_response, parse_overseas_price_response, parse_price_response, parse_rank_rows, rank_row_symbol


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path(os.environ.get("SEMIBOT_STATE_ROOT", ROOT)).resolve()
DEFAULT_MARKET = "domestic"
OVERSEAS_MARKET = "overseas"
NASDAQ_SURGE_MARKET = "nasdaq_surge"
DOMESTIC_SURGE_MARKET = "domestic_surge"
DOMESTIC_ETF_MARKET = "domestic_etf"
SUPPORTED_MARKETS = {DEFAULT_MARKET, OVERSEAS_MARKET, NASDAQ_SURGE_MARKET, DOMESTIC_SURGE_MARKET, DOMESTIC_ETF_MARKET}
LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.local.json"
KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.local.json"
LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading"
OVERSEAS_LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.overseas.local.json"
OVERSEAS_KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.overseas.local.json"
OVERSEAS_LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading_overseas"
NASDAQ_SURGE_LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.nasdaq_surge.local.json"
NASDAQ_SURGE_KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.nasdaq_surge.local.json"
NASDAQ_SURGE_LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading_nasdaq_surge"
DOMESTIC_SURGE_LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.domestic_surge.local.json"
DOMESTIC_SURGE_KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.domestic_surge.local.json"
DOMESTIC_SURGE_LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading_domestic_surge"
DOMESTIC_ETF_LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.domestic_etf.local.json"
DOMESTIC_ETF_KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.domestic_etf.local.json"
DOMESTIC_ETF_LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading_domestic_etf"
NASDAQ_PRICE_EXCHANGE_CODE = "NAS"
NASDAQ_ORDER_EXCHANGE_CODE = "NASD"
NASDAQ_SURGE_MIN_TRADE_VALUE = 10_000_000.0
NASDAQ_SURGE_PREMARKET_MIN_TRADE_VALUE = 1_000_000.0
NASDAQ_SURGE_MIN_RECENT_TRADE_VALUE = 2_000_000.0
NASDAQ_SURGE_PREMARKET_MIN_RECENT_TRADE_VALUE = 300_000.0
NASDAQ_SURGE_MIN_STRENGTH = 1.3
DOMESTIC_SURGE_MIN_RECENT_TRADE_VALUE = 1_000_000_000.0
DOMESTIC_SURGE_MIN_STRENGTH = 1.3
DOMESTIC_ETF_MIN_TRADE_VALUE = 1_000_000_000.0
# 종목별 차등화된 거래대금 최소입계 (KRW). 코스피200/200은 높게, 세터 ETF는 낮게.
DOMESTIC_ETF_TRADE_VALUE_BY_SYMBOL: dict[str, float] = {
    "069500": 5_000_000_000.0,  # KODEX 200
    "102110": 2_000_000_000.0,  # TIGER 200
    "229200": 1_000_000_000.0,  # KODEX 코스닥150
    "232080": 800_000_000.0,    # TIGER 코스닥150
    "091160": 500_000_000.0,    # KODEX 반도체
    "091230": 300_000_000.0,    # TIGER 반도체
    "396500": 300_000_000.0,    # TIGER Fn반도체TOP10
    "305720": 500_000_000.0,    # KODEX 2차전지
    "305540": 500_000_000.0,    # TIGER 2차전지
    "091170": 300_000_000.0,    # KODEX 은행
    "091220": 200_000_000.0,    # TIGER 은행
    "091180": 300_000_000.0,    # KODEX 자동차
    "157510": 200_000_000.0,    # TIGER 자동차
    "244580": 300_000_000.0,    # KODEX 바이오
    "364970": 200_000_000.0,    # TIGER 바이오TOP10
}
DOMESTIC_ETF_DEFAULT_TRADE_VALUE = 200_000_000.0
OVERSEAS_MIN_PRICE = 5.0
OVERSEAS_MIN_TRADE_VALUE = 20_000_000.0
OVERSEAS_PREMARKET_MIN_TRADE_VALUE = 2_000_000.0
DEFAULT_POLL_INTERVAL_SEC = 15
DEFAULT_MAX_SYMBOLS = 12
NEW_YORK_TZ = ZoneInfo("America/New_York")
SEOUL_TZ = ZoneInfo("Asia/Seoul")
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
DOMESTIC_ETF_UNIVERSE = {
    "069500": "KODEX 200",
    "102110": "TIGER 200",
    "229200": "KODEX 코스닥150",
    "232080": "TIGER 코스닥150",
    "091160": "KODEX 반도체",
    "091230": "TIGER 반도체",
    "396500": "TIGER Fn반도체TOP10",
    "305720": "KODEX 2차전지산업",
    "305540": "TIGER 2차전지테마",
    "091170": "KODEX 은행",
    "091220": "TIGER 은행",
    "091180": "KODEX 자동차",
    "157510": "TIGER 자동차",
    "244580": "KODEX 바이오",
    "364970": "TIGER 바이오TOP10",
}
DOMESTIC_ETF_INDEX_PROXIES = ("069500", "102110", "229200", "232080")
SESSION_PREMARKET = "premarket"
SESSION_REGULAR = "regular"
SESSION_CLOSED = "closed"
TONE_MIN_HOLD_SECONDS = 10 * 60
TONE_AGGRESSIVE_CONFIRM_SECONDS = 10 * 60
TONE_CONSERVATIVE_CONFIRM_SECONDS = 4 * 60
TONE_NEUTRAL_CONFIRM_SECONDS = 6 * 60
TONE_URGENT_STOP_RATIO = 0.75
TONE_EXTREME_WEAK_MOVE = -0.006
TONE_EXTREME_WEAK_BREADTH = 0.25


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
    poll_interval_sec: int = DEFAULT_POLL_INTERVAL_SEC
    bar_minutes: int = 5
    max_symbols: int = DEFAULT_MAX_SYMBOLS
    max_positions: int = 3
    selection_refresh_sec: int = 300
    min_selection_hold_sec: int = 1800
    min_bars_before_evaluate: int = 20
    candidate_pool_size: int = 60
    clock_offset_hours: int = 0
    overseas_premarket_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveConfig":
        market = _market(data.get("market", DEFAULT_MARKET))
        overseas_market = _is_overseas_market(market)
        surge_market = _is_surge_market(market)
        default_clock_offset = -7 if overseas_market else 0
        default_seed_capital = 10_000.0 if overseas_market else 1_000_000.0
        currency = "USD" if overseas_market else "KRW"
        default_poll_interval = 5 if surge_market else DEFAULT_POLL_INTERVAL_SEC
        min_poll_interval = 5 if surge_market else DEFAULT_POLL_INTERVAL_SEC
        default_bar_minutes = 1 if surge_market else 5
        default_max_positions = 1 if surge_market else 3
        default_selection_refresh = 60 if surge_market else 300
        min_selection_refresh = 60 if surge_market else 300
        default_min_selection_hold = 180 if surge_market else 1800
        min_selection_hold = 60 if surge_market else 1800
        default_min_bars = 4 if surge_market else 20
        default_candidate_pool = 80 if surge_market else 60
        return cls(
            market=market,
            mode=data.get("mode", "paper"),
            account_no=data.get("account_no", ""),
            product_code=data.get("product_code", "01"),
            symbol="",
            exchange_code=NASDAQ_ORDER_EXCHANGE_CODE,
            price_exchange_code=NASDAQ_PRICE_EXCHANGE_CODE,
            currency=currency,
            seed_capital=_positive_float(data.get("seed_capital"), default_seed_capital),
            seed_source=_seed_source(data.get("seed_source", "manual")),
            auto_start=_truthy(data.get("auto_start")),
            auto_select=True,
            poll_interval_sec=max(min_poll_interval, int(data.get("poll_interval_sec", default_poll_interval))),
            bar_minutes=max(1, int(data.get("bar_minutes", default_bar_minutes))),
            max_symbols=max(1, min(DEFAULT_MAX_SYMBOLS, int(data.get("max_symbols", DEFAULT_MAX_SYMBOLS)))),
            max_positions=max(1, int(data.get("max_positions", default_max_positions))),
            selection_refresh_sec=max(min_selection_refresh, int(data.get("selection_refresh_sec", default_selection_refresh))),
            min_selection_hold_sec=max(min_selection_hold, int(data.get("min_selection_hold_sec", default_min_selection_hold))),
            min_bars_before_evaluate=max(1, int(data.get("min_bars_before_evaluate", default_min_bars))),
            candidate_pool_size=int(data.get("candidate_pool_size", default_candidate_pool)),
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
            "max_positions": self.max_positions,
            "selection_refresh_sec": self.selection_refresh_sec,
            "min_selection_hold_sec": self.min_selection_hold_sec,
            "min_bars_before_evaluate": self.min_bars_before_evaluate,
            "candidate_pool_size": self.candidate_pool_size,
            "clock_offset_hours": self.clock_offset_hours,
            "overseas_premarket_enabled": self.overseas_premarket_enabled,
        }


@dataclass(frozen=True)
class DirectEntryProfile:
    min_bars: int = 3
    min_volume_ratio: float = 0.8
    min_vwap_ratio: float = 0.995
    min_lookback_move: float = 0.001
    require_opening_breakout: bool = False
    max_setup_move: float | None = None
    max_extension_pct: float | None = None
    reason: str = "live_momentum_entry"


@dataclass(frozen=True)
class MarketToneSignal:
    tone: str = "neutral"
    avg_move: float = 0.0
    breadth: float = 0.0
    sample_count: int = 0


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
            "max_positions": config.max_positions,
            "exchange_code": config.exchange_code,
            "price_exchange_code": config.price_exchange_code,
            "currency": config.currency,
            "session": "",
            "session_label": "",
            "overseas_premarket_enabled": config.overseas_premarket_enabled,
            "bar_count": 0,
            "bar_minutes": config.bar_minutes,
            "bar_ready_symbols": 0,
            "bar_min_ready": 0,
            "bar_counts": {},
            "price_error_count": 0,
            "token_status": "대기",
            "token_expires_at": "",
            "trade_message": "매수 조건 대기",
            "strategy_tone": "neutral",
            "strategy_profile_mode": "auto" if strategy.adaptive_market_regime else "fixed",
        }
        self.bars: list[StockBar] = []
        self.seeded_previous_close: dict[str, object] = {}
        self.last_cumulative_volume: dict[tuple[str, object], int] = {}
        self._error_streak: int = 0
        self._tone_current: str = "neutral"
        self._tone_current_since: datetime | None = None
        self._tone_pending: str = "neutral"
        self._tone_pending_since: datetime | None = None
        self._tone_pending_count: int = 0
        self.active_symbols: list[str] = []
        self.selected_since: dict[str, float] = {}
        self.last_selection_at = 0.0
        self.regular_reset_dates: set[object] = set()
        self.startup_token_checked = False
        self.positions: list[dict[str, Any]] = []
        self.cash = strategy.initial_capital
        self.day_start_cash = strategy.initial_capital
        self.day_state_date: object | None = None
        ensure_live_report(self.report_dir, strategy_name=_strategy_name(self.market))
        restored_positions, restored_cash = _open_positions_from_trades(self.report_dir)
        if restored_positions:
            self.positions = restored_positions
            if restored_cash > 0:
                self.cash = restored_cash
            self.status["trade_message"] = f"기존 보유 복원: {_positions_summary(restored_positions)}"

    @property
    def position(self) -> dict[str, Any] | None:
        return self.positions[0] if self.positions else None

    @position.setter
    def position(self, value: dict[str, Any] | None) -> None:
        self.positions = [value] if value else []

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
            positions = [dict(position) for position in self.positions]
            data["position"] = positions[0] if positions else {}
            data["positions"] = positions
            data["cash"] = round(self.cash, 2)
            data["seed_capital"] = round(self.strategy.initial_capital, 2)
            data["seed_source"] = self.config.seed_source
            data["auto_start"] = self.config.auto_start
            data["max_positions"] = self.config.max_positions
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
                    self._ensure_startup_token(client, now)
                    self._run_cycle(client, now)
                    time.sleep(max(1, self.config.poll_interval_sec))
                except Exception as exc:  # noqa: BLE001
                    backoff = self._record_retriable_error(exc, now)
                    time.sleep(backoff)
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.status.update({"last_error": str(exc), "message": "오류"})
        finally:
            with self.lock:
                self.status["running"] = False
            self.running = False

    def _ensure_startup_token(self, client: KisClient, now: datetime) -> None:
        if self.startup_token_checked:
            return
        client.ensure_token()
        self.startup_token_checked = True
        token_expires_at = getattr(client, "access_token_expires_at", "")
        with self.lock:
            self.status.update(
                {
                    "token_status": "확인 완료",
                    "token_expires_at": token_expires_at,
                }
            )
        self._log_decision("token_ready", now, token_expires_at=token_expires_at)

    def _run_cycle(self, client: KisClient, now: datetime) -> None:
        strategy_now = self._strategy_now(now)
        self._sync_daily_state(strategy_now)
        session = self._market_session(strategy_now)
        if session == SESSION_CLOSED:
            self._set_market_wait_status(now, strategy_now)
            return
        self._reset_premarket_bars_for_regular_if_flat(strategy_now, session)

        selection_elapsed = time.time() - self.last_selection_at if self.last_selection_at else float("inf")
        should_select = (not self.active_symbols) if self.last_selection_at <= 0 else (
            self.config.auto_select and selection_elapsed >= self.config.selection_refresh_sec
        )
        if should_select:
            self.active_symbols = self._select_symbols(client)
        price_errors = []
        updated_symbols: set[str] = set()
        for symbol in self._symbols_to_poll():
            try:
                parsed = self._fetch_price(client, symbol)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                price_errors.append({"symbol": symbol, "error": error_text})
                if _is_rate_limit_error(error_text):
                    # API 초당 제한이 감지되면 즉시 텀을 늘려 호출 밀도를 낮춘다.
                    time.sleep(0.25 if _is_overseas_market(self.market) else 0.15)
                continue
            if parsed["price"] <= 0:
                price_errors.append(_price_error_payload(symbol, "price<=0", parsed))
                continue
            self._add_tick(symbol, strategy_now, parsed)
            updated_symbols.add(symbol)
            time.sleep(0.09 if _is_overseas_market(self.market) else 0.05)
        self._evaluate(client, strategy_now, updated_symbols)
        if self.config.mode == "live":
            self._write_live_state_report(strategy_now)
        self._error_streak = 0
        bar_status = self._bar_collection_status(strategy_now)
        self._log_decision(
            "cycle",
            strategy_now,
            session=session,
            strategy_tone=str(self.status.get("strategy_tone", "neutral")),
            active_symbols=list(self.active_symbols),
            position=self.position or {},
            positions=[dict(position) for position in self.positions],
            cash=round(self.cash, 2),
            trade_message=str(self.status.get("trade_message", "")),
            bar_collection=bar_status,
            price_errors=price_errors[:12],
        )
        with self.lock:
            self.status.update(
                {
                    "last_tick": now.isoformat(sep=" ", timespec="seconds"),
                    "market_time": strategy_now.isoformat(sep=" ", timespec="seconds"),
                    "message": "실행 중",
                    "last_error": "",
                    "active_symbols": list(self.active_symbols),
                    "session": session,
                    "session_label": _session_label(session, self.market),
                    "bar_count": bar_status["total"],
                    "bar_ready_symbols": bar_status["ready_symbols"],
                    "bar_min_ready": bar_status["min_ready"],
                    "bar_counts": bar_status["by_symbol"],
                    "price_error_count": len(price_errors),
                }
            )

    def _set_market_wait_status(self, now: datetime, strategy_now: datetime) -> None:
        message = _market_wait_message(self.market, strategy_now, self.config.overseas_premarket_enabled)
        label = _session_label(SESSION_CLOSED, self.market)
        with self.lock:
            self.status.update(
                {
                    "last_tick": now.isoformat(sep=" ", timespec="seconds"),
                    "market_time": strategy_now.isoformat(sep=" ", timespec="seconds"),
                    "message": label,
                    "last_error": "",
                    "selector_message": message,
                    "active_symbols": list(self.active_symbols),
                    "session": SESSION_CLOSED,
                    "session_label": label,
                    "price_error_count": 0,
                }
            )
        self._set_trade_message(message)
        self._log_decision(
            "market_wait",
            strategy_now,
            session=SESSION_CLOSED,
            reason=message,
            active_symbols=list(self.active_symbols),
            position=self.position or {},
            positions=[dict(position) for position in self.positions],
        )

    def _record_retriable_error(self, exc: Exception, now: datetime) -> int:
        msg = str(exc).lower()
        if any(token in msg for token in ("token", "401", "403", "unauthor")):
            kind = "token"
        elif _is_rate_limit_error(msg):
            kind = "rate_limit"
        elif any(token in msg for token in ("timeout", "timed out")):
            kind = "timeout"
        else:
            kind = "network"
        self._error_streak = min(self._error_streak + 1, 8)
        if kind == "token":
            self.startup_token_checked = False
            backoff = 5
        elif kind == "rate_limit":
            backoff = min(120, 10 * (2 ** (self._error_streak - 1)))
        elif kind == "timeout":
            backoff = min(60, max(10, self.config.poll_interval_sec * self._error_streak))
        else:
            backoff = max(5, min(60, self.config.poll_interval_sec * 2))
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
        self._set_trade_message(f"통신 오류({kind})로 {backoff}초 후 재시도")
        self._log_decision("error", now, error=str(exc), kind=kind, backoff=backoff, streak=self._error_streak, active_symbols=list(self.active_symbols))
        return backoff

    def _initial_symbols(self, client: KisClient) -> list[str]:
        if self.market == OVERSEAS_MARKET:
            return self._select_symbols(client)
        return self._select_symbols(client)

    def _select_symbols(self, client: KisClient) -> list[str]:
        now_ts = time.time()
        self.last_selection_at = now_ts
        candidates = self._candidate_symbols(client)
        ranked: list[tuple[float, str]] = []
        rejected: list[dict[str, Any]] = []
        candidate_items = sorted(candidates.items(), key=lambda item: _source_priority(item[1]), reverse=True)
        tracking_symbols = [symbol for symbol, _ in candidate_items[: self.config.candidate_pool_size]]
        for symbol, row in candidate_items[: self.config.candidate_pool_size]:
            try:
                parsed = self._fetch_price(client, symbol)
            except Exception as exc:  # noqa: BLE001
                if len(rejected) < 12:
                    rejected.append({"symbol": symbol, "reason": f"price_error {exc}", "price": 0})
                continue
            if parsed["price"] <= 0:
                if len(rejected) < 12:
                    rejected.append(_price_error_payload(symbol, "price<=0", parsed, reason_key="reason", price=0))
                continue
            passed, reject_reason = self._live_candidate_filter(parsed, row)
            if not passed:
                if len(rejected) < 12:
                    rejected.append({"symbol": symbol, "reason": reject_reason, "price": parsed.get("price", 0)})
                continue
            score = self._live_candidate_score(parsed, row)
            ranked.append((score, symbol))
            time.sleep(0.08 if _is_overseas_market(self.market) else 0.04)
        ranked.sort(reverse=True)
        fresh_selected = [symbol for _, symbol in ranked[: self.config.max_symbols]]
        if self.market == DOMESTIC_ETF_MARKET:
            fresh_selected = _prepend_symbols(fresh_selected, [symbol for symbol in DOMESTIC_ETF_INDEX_PROXIES if symbol in candidates], self.config.max_symbols)
        if self.market == OVERSEAS_MARKET and len(fresh_selected) < self.config.max_symbols:
            for symbol in tracking_symbols:
                if symbol not in fresh_selected:
                    fresh_selected.append(symbol)
                if len(fresh_selected) >= self.config.max_symbols:
                    break
        selected = self._merge_selected_symbols(fresh_selected, now_ts)
        with self.lock:
            market_label = _selector_label(self.market)
            if _is_overseas_market(self.market) and self._market_session(self._strategy_now(datetime.now())) == SESSION_PREMARKET:
                market_label = "프리장 NASDAQ 자동선별" if self.market == OVERSEAS_MARKET else "프리장 나스닥 급등주 자동선별"
            hold_minutes = max(1, round(self.config.min_selection_hold_sec / 60))
            self.status["selector_message"] = f"{market_label} {len(selected)}종목 / 후보 {len(candidates)}종목 / 유지 {hold_minutes}분"
            self.status["active_symbols"] = selected
        self._log_decision(
            "selection",
            self._strategy_now(datetime.now()),
            candidate_count=len(candidates),
            selected=selected,
            ranked=[{"symbol": symbol, "score": round(score, 4)} for score, symbol in ranked[: self.config.max_symbols]],
            rejected=rejected,
        )
        return selected

    def _fetch_price(self, client: KisClient, symbol: str) -> dict[str, Any]:
        if _is_overseas_market(self.market):
            price_data = client.inquire_overseas_price(self.config.price_exchange_code, symbol)
            parsed = parse_overseas_price_response(price_data)
            parsed["kis_response"] = _kis_response_summary(price_data)
            return parsed
        price_data = client.inquire_price(symbol)
        parsed = parse_price_response(price_data)
        parsed["kis_response"] = _kis_response_summary(price_data)
        return parsed

    def _strategy_now(self, now: datetime) -> datetime:
        if _is_overseas_market(self.market):
            return _as_market_time(now, NEW_YORK_TZ)
        if not self.config.clock_offset_hours:
            return _as_market_time(now, SEOUL_TZ)
        return now + timedelta(hours=self.config.clock_offset_hours)

    def _market_session(self, now: datetime) -> str:
        if not _is_overseas_market(self.market):
            if now.weekday() >= 5:
                return SESSION_CLOSED
            current = now.time()
            if clock_time(9, 0) <= current < clock_time(15, 30):
                return SESSION_REGULAR
            return SESSION_CLOSED
        current = now.time()
        if now.weekday() >= 5:
            return SESSION_CLOSED
        if clock_time(9, 30) <= current < clock_time(16, 0):
            return SESSION_REGULAR
        if self.config.overseas_premarket_enabled and clock_time(4, 0) <= current < clock_time(9, 30):
            return SESSION_PREMARKET
        return SESSION_CLOSED

    def _reset_premarket_bars_for_regular_if_flat(self, now: datetime, session: str) -> None:
        if not _is_overseas_market(self.market) or not self.config.overseas_premarket_enabled:
            return
        if session != SESSION_REGULAR or self.positions:
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
        if self.market == NASDAQ_SURGE_MARKET:
            return self._nasdaq_surge_candidate_symbols(client)
        if self.market == DOMESTIC_SURGE_MARKET:
            return self._domestic_surge_candidate_symbols(client)
        if self.market == DOMESTIC_ETF_MARKET:
            return self._domestic_etf_candidate_symbols(client)
        rows = self._domestic_rank_rows(client)

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

    def _domestic_rank_rows(self, client: KisClient) -> list[tuple[str, dict[str, Any]]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        responses = [
            ("trade_value", client.volume_rank(sort_code="3", min_volume="0")),
            ("volume_surge", client.volume_rank(sort_code="1", min_volume="0")),
            ("gap_up", client.fluctuation_rank(min_rate=str(int(self.strategy.gap_min_pct * 100)), max_rate="30", count="80")),
            ("strength", client.volume_power_rank()),
        ]
        for source, response in responses:
            rows.extend((source, row) for row in parse_rank_rows(response))
        return rows

    def _domestic_surge_rank_rows(self, client: KisClient) -> list[tuple[str, dict[str, Any]]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        responses = [
            ("trade_value", client.volume_rank(sort_code="3", min_volume="0")),
            ("volume_surge", client.volume_rank(sort_code="1", min_volume="0")),
            ("gap_up", client.fluctuation_rank(min_rate="3", max_rate="15", count="50")),
            ("strength", client.volume_power_rank()),
        ]
        for source, response in responses:
            rows.extend((source, row) for row in parse_rank_rows(response))
        return rows

    def _domestic_surge_candidate_symbols(self, client: KisClient) -> dict[str, dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for source, row in self._domestic_surge_rank_rows(client):
            symbol = rank_row_symbol(row)
            if not _valid_stock_symbol(symbol):
                continue
            if _excluded_name(str(row.get("hts_kor_isnm", ""))) or _excluded_domestic_warning_row(row):
                continue
            if symbol not in candidates:
                candidates[symbol] = dict(row)
                candidates[symbol]["_sources"] = [source]
                continue
            candidates[symbol].update({key: value for key, value in row.items() if value not in {"", None}})
            candidates[symbol].setdefault("_sources", []).append(source)
        return candidates

    def _domestic_etf_candidate_symbols(self, client: KisClient) -> dict[str, dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for source, row in self._domestic_rank_rows(client):
            symbol = rank_row_symbol(row)
            if not _valid_stock_symbol(symbol):
                continue
            if not _included_domestic_etf(row, symbol):
                continue
            if symbol not in candidates:
                candidates[symbol] = dict(row)
                candidates[symbol]["_sources"] = [source]
                continue
            candidates[symbol].update({key: value for key, value in row.items() if value not in {"", None}})
            candidates[symbol].setdefault("_sources", []).append(source)
        for symbol, name in DOMESTIC_ETF_UNIVERSE.items():
            if _excluded_domestic_etf_name(name):
                continue
            candidates.setdefault(symbol, {"stck_shrn_iscd": symbol, "hts_kor_isnm": name, "_sources": []})
            candidates[symbol].setdefault("_sources", []).append("etf_universe")
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
                    "vol_inrt": "110",
                }
        return candidates

    def _nasdaq_surge_candidate_symbols(self, client: KisClient) -> dict[str, dict[str, Any]]:
        exchange_code = NASDAQ_PRICE_EXCHANGE_CODE
        rows: list[tuple[str, dict[str, Any]]] = []
        responses = [
            ("trade_value", client.overseas_trade_value_rank(exchange_code=exchange_code, price_min="5")),
            ("volume", client.overseas_trade_volume_rank(exchange_code=exchange_code, price_min="5")),
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
            if _excluded_overseas_name(_row_name(row), symbol):
                continue
            if symbol not in candidates:
                candidates[symbol] = dict(row)
                candidates[symbol]["_sources"] = [source]
                continue
            candidates[symbol].update({key: value for key, value in row.items() if value not in {"", None}})
            candidates[symbol].setdefault("_sources", []).append(source)
        return candidates

    def _passes_live_candidate(self, parsed: dict[str, float], row: dict[str, Any]) -> bool:
        passed, _ = self._live_candidate_filter(parsed, row)
        return passed

    def _live_candidate_filter(self, parsed: dict[str, float], row: dict[str, Any]) -> tuple[bool, str]:
        strategy = self._active_strategy(self._strategy_now(datetime.now()))
        price = parsed["price"]
        if price <= 0:
            return False, "price<=0"
        if _is_overseas_market(self.market) and price < OVERSEAS_MIN_PRICE:
            return False, f"price<{OVERSEAS_MIN_PRICE}"
        setup_move = parsed["prev_rate_pct"] / 100.0
        if not (strategy.gap_min_pct <= setup_move <= strategy.gap_max_pct):
            return False, f"setup_move {setup_move * 100:.2f}%"
        range_available = parsed["high"] > 0 and parsed["low"] > 0 and parsed["high"] > parsed["low"]
        day_range = ((parsed["high"] - parsed["low"]) / price) if price and range_available else 0.0
        if day_range < strategy.min_atr_pct and (range_available or not _is_overseas_market(self.market)):
            return False, f"range {day_range * 100:.2f}%"
        sources = set(row.get("_sources", []))
        symbol_for_threshold = str(row.get("stck_shrn_iscd") or row.get("symb") or "").strip().upper()
        trade_value = parsed["value"] or _row_trade_value(row)
        threshold = self._trade_value_threshold(symbol_for_threshold)
        if self.market == NASDAQ_SURGE_MARKET:
            if range_available and day_range > strategy.max_atr_pct:
                return False, f"range {day_range * 100:.2f}%"
            volume_surge = _row_volume_surge(row)
            if volume_surge < strategy.volume_factor and "volume_surge" not in sources:
                return False, f"volume {volume_surge:.2f}x"
            strength = _row_strength(row)
            if strength < NASDAQ_SURGE_MIN_STRENGTH and "strength" not in sources:
                return False, f"strength {strength * 100:.0f}<130"
            if trade_value >= threshold or "trade_value" in sources:
                return True, ""
            return False, f"value {trade_value:.0f}<{threshold:.0f}"
        if self.market == DOMESTIC_SURGE_MARKET:
            if _excluded_domestic_warning_row(row):
                return False, "warning_stock"
            if day_range > strategy.max_atr_pct:
                return False, f"range {day_range * 100:.2f}%"
            spread_reason = _spread_reject_reason(parsed.get("spread_pct"), strategy)
            if spread_reason:
                return False, spread_reason
            avg_volume = _float(row.get("avrg_vol"))
            volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else _row_volume_surge(row)
            strength = _row_strength(row)
            volume_ok = volume_surge >= strategy.volume_factor or "volume_surge" in sources
            strength_ok = strength >= DOMESTIC_SURGE_MIN_STRENGTH or "strength" in sources
            liquidity_ok = trade_value >= threshold or "trade_value" in sources
            if not liquidity_ok:
                return False, f"value {trade_value:.0f}<{threshold:.0f}"
            if volume_ok or strength_ok or len(sources) >= 2:
                return True, ""
            return False, f"activity volume {volume_surge:.2f}x strength {strength * 100:.0f}<130"
        if self.market == DOMESTIC_ETF_MARKET:
            if trade_value >= threshold or "trade_value" in sources:
                return True, ""
            return False, f"value {trade_value:.0f}<{threshold:.0f}"
        avg_volume = _float(row.get("avrg_vol"))
        volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else _float(row.get("vol_inrt")) / 100.0
        if volume_surge < strategy.volume_factor and "volume_surge" not in sources:
            return False, f"volume {volume_surge:.2f}x"
        if trade_value >= threshold or "trade_value" in sources:
            return True, ""
        return False, f"value {trade_value:.0f}<{threshold:.0f}"

    def _live_candidate_score(self, parsed: dict[str, float], row: dict[str, Any]) -> float:
        price = parsed["price"] or 1.0
        day_range = max(0.0, (parsed["high"] - parsed["low"]) / price)
        gap = max(0.0, parsed["prev_rate_pct"] / 100.0)
        trade_value = max(parsed["value"], _row_trade_value(row), 1.0)
        avg_volume = _row_average_volume(row)
        volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else max(0.0, _row_volume_surge(row))
        strength = max(0.0, _row_strength(row))
        source_bonus = _source_priority(row) * (0.35 if _is_overseas_market(self.market) else 0.0)
        return (math.log10(trade_value) * 1.5) + (gap * 100.0) + (day_range * 120.0) + min(volume_surge, 8.0) + strength + source_bonus

    def _trade_value_threshold(self, symbol: str | None = None) -> float:
        if self.market == DOMESTIC_ETF_MARKET:
            if symbol and symbol in DOMESTIC_ETF_TRADE_VALUE_BY_SYMBOL:
                return DOMESTIC_ETF_TRADE_VALUE_BY_SYMBOL[symbol]
            return DOMESTIC_ETF_DEFAULT_TRADE_VALUE
        if self.market == NASDAQ_SURGE_MARKET:
            if self._market_session(self._strategy_now(datetime.now())) == SESSION_PREMARKET:
                return NASDAQ_SURGE_PREMARKET_MIN_TRADE_VALUE
            return NASDAQ_SURGE_MIN_TRADE_VALUE
        if self.market == DOMESTIC_SURGE_MARKET:
            return DOMESTIC_SURGE_MIN_RECENT_TRADE_VALUE
        if not _is_overseas_market(self.market):
            return 1_000_000_000
        if self._market_session(self._strategy_now(datetime.now())) == SESSION_PREMARKET:
            return OVERSEAS_PREMARKET_MIN_TRADE_VALUE
        return OVERSEAS_MIN_TRADE_VALUE

    def _add_tick(self, symbol: str, now: datetime, parsed: dict[str, float]) -> None:
        self._seed_previous_close(symbol, now, parsed)
        price = parsed["price"]
        volume_delta = self._volume_delta(symbol, now.date(), int(parsed["volume"]))
        minute_bucket = now.replace(minute=(now.minute // self.config.bar_minutes) * self.config.bar_minutes, second=0, microsecond=0)
        with self.lock:
            existing = next((bar for bar in reversed(self.bars) if bar.symbol == symbol and bar.timestamp == minute_bucket), None)
            if existing:
                self.bars.remove(existing)
                bar = StockBar(
                    symbol=symbol,
                    timestamp=minute_bucket,
                    open=existing.open,
                    high=max(existing.high, price),
                    low=min(existing.low, price),
                    close=price,
                    volume=existing.volume + volume_delta,
                    bid=parsed.get("bid") or existing.bid,
                    ask=parsed.get("ask") or existing.ask,
                    spread_pct=parsed.get("spread_pct") if parsed.get("spread_pct") else existing.spread_pct,
                )
            else:
                bar = StockBar(
                    symbol=symbol,
                    timestamp=minute_bucket,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume_delta,
                    bid=parsed.get("bid") or None,
                    ask=parsed.get("ask") or None,
                    spread_pct=parsed.get("spread_pct") or None,
                )
            self.bars.append(bar)
            self.bars = self.bars[-5000:]

    def _volume_delta(self, symbol: str, session: object, cumulative_volume: int) -> int:
        # 세션 전환 시 이전 다른 날짜 키는 점진적으로 제거 (메모리 누수 방지)
        for stale_key in [k for k in self.last_cumulative_volume if k[0] == symbol and k[1] != session]:
            self.last_cumulative_volume.pop(stale_key, None)
        key = (symbol, session)
        previous = self.last_cumulative_volume.get(key)
        cumulative_volume = max(0, cumulative_volume)
        self.last_cumulative_volume[key] = cumulative_volume
        if previous is None:
            return 0
        if cumulative_volume < previous:
            return 0
        return cumulative_volume - previous

    def _symbols_to_poll(self) -> list[str]:
        symbols = list(self.active_symbols)
        for position in reversed(self.positions):
            position_symbol = str(position.get("symbol") or "")
            if position_symbol and position_symbol not in symbols:
                symbols.insert(0, position_symbol)
        if self.market == DOMESTIC_ETF_MARKET:
            for proxy in DOMESTIC_ETF_INDEX_PROXIES:
                if proxy not in symbols:
                    symbols.append(proxy)
        return symbols

    def _bar_collection_status(self, now: datetime) -> dict[str, Any]:
        strategy = self._active_strategy(now)
        min_ready = self._direct_entry_profile(now, strategy).min_bars
        by_symbol: dict[str, int] = {}
        latest_by_symbol: dict[str, str] = {}
        for symbol in self._symbols_to_poll():
            current_bars = sorted(
                (bar for bar in self.bars if bar.symbol == symbol and bar.session == now.date()),
                key=lambda bar: bar.timestamp,
            )
            by_symbol[symbol] = len(current_bars)
            if current_bars:
                latest_by_symbol[symbol] = current_bars[-1].timestamp.isoformat(sep=" ", timespec="minutes")
        return {
            "total": sum(by_symbol.values()),
            "ready_symbols": sum(1 for count in by_symbol.values() if count >= min_ready),
            "min_ready": min_ready,
            "by_symbol": by_symbol,
            "latest_by_symbol": latest_by_symbol,
        }

    def _seed_previous_close(self, symbol: str, now: datetime, parsed: dict[str, float]) -> None:
        if self.seeded_previous_close.get(symbol) == now.date():
            return
        prev_rate = parsed.get("prev_rate_pct", 0.0)
        price = parsed.get("price", 0.0)
        if price <= 0 or prev_rate <= -99.0:
            return
        previous_close = price / (1.0 + (prev_rate / 100.0)) if prev_rate else price
        seed_close_time = clock_time(16, 0) if _is_overseas_market(self.market) else clock_time(15, 30)
        previous_timestamp = datetime.combine(now.date() - timedelta(days=1), seed_close_time)
        with self.lock:
            self.bars = [
                bar for bar in self.bars
                if not (bar.symbol == symbol and bar.session == previous_timestamp.date())
            ]
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
        self.seeded_previous_close[symbol] = now.date()

    def _evaluate(self, client: KisClient, now: datetime, fresh_symbols: set[str] | None = None) -> None:
        strategy = self._active_strategy(now)
        if self._try_live_direct_exit(client, now, strategy, fresh_symbols):
            return
        if len(self.bars) < self.config.min_bars_before_evaluate:
            if self._try_live_direct_entry(client, now, strategy, {}, [], fresh_symbols):
                return
            self._set_trade_message(f"{self.config.bar_minutes}분봉 데이터 수집 중 ({len(self.bars)}/{self.config.min_bars_before_evaluate})")
            return
        result = StockScannerBacktester(strategy).run(self.bars)
        if self.config.mode == "live" and self._try_live_direct_entry(
            client,
            now,
            strategy,
            result.metrics,
            result.equity_curve,
            fresh_symbols,
        ):
            return
        latest_trade = result.trades[-1] if result.trades else None
        if not latest_trade:
            self._set_trade_message(self._entry_wait_message(now))
            if self.config.mode != "live":
                _write_live_metrics(result.metrics, self.report_dir)
            return
        if fresh_symbols is not None and latest_trade.symbol not in fresh_symbols:
            self._set_trade_message(f"{latest_trade.symbol}: 현재가 갱신 대기")
            return
        last_recorded = _last_trade_key(self.report_dir)
        trade_key = f"{latest_trade.timestamp}|{latest_trade.action}|{latest_trade.symbol}|{latest_trade.shares}|{latest_trade.reason}"
        if trade_key == last_recorded or _trade_key_exists(self.report_dir, trade_key):
            self._set_trade_message("최근 신호는 이미 기록됨")
            return
        live = self.config.mode == "live"
        if latest_trade.action == "BUY":
            entry_count = _live_buy_count_for_session(self.report_dir, now.date())
            if live and entry_count >= strategy.max_trades_per_day:
                self._set_trade_message(_daily_entry_limit_message(entry_count, strategy.max_trades_per_day))
                self._log_decision(
                    "entry_skip",
                    now,
                    symbol=latest_trade.symbol,
                    reason="daily_trade_limit",
                    entries=entry_count,
                    max_trades_per_day=strategy.max_trades_per_day,
                )
                return
            if live:
                if not self._can_open_position(latest_trade.symbol, now, strategy):
                    return
                bar = _latest_symbol_bar(self.bars, latest_trade.symbol, now.date()) or StockBar(
                    latest_trade.symbol,
                    latest_trade.timestamp,
                    latest_trade.price,
                    latest_trade.price,
                    latest_trade.price,
                    latest_trade.price,
                    1,
                )
                shares = _live_order_shares(
                    self.cash,
                    bar.close,
                    strategy,
                    self.config.max_positions,
                    self.strategy.initial_capital,
                )
                if self._submit_live_buy(
                    client,
                    now,
                    strategy,
                    bar,
                    shares,
                    latest_trade.reason,
                    result.metrics,
                    result.equity_curve,
                    trade_timestamp=latest_trade.timestamp,
                ):
                    return
                return
            response = self._place_order(client, "buy", latest_trade.symbol, latest_trade.shares, live, latest_trade.price)
            if not _order_succeeded(response, live):
                self._set_trade_message(f"주문 실패: BUY {latest_trade.symbol} ({_order_message(response)})")
                return
            self.position = {
                "symbol": latest_trade.symbol,
                "shares": latest_trade.shares,
                "entry_price": latest_trade.price,
                "highest_price": latest_trade.price,
                "entry_time": latest_trade.timestamp.isoformat(sep=" "),
            }
        else:
            if live:
                position = self._position_for_symbol(latest_trade.symbol)
                if not position:
                    self._set_trade_message(f"{latest_trade.symbol}: 매도 신호가 있으나 보유 없음")
                    return
                bar = _latest_symbol_bar(self.bars, latest_trade.symbol, now.date()) or StockBar(
                    latest_trade.symbol,
                    latest_trade.timestamp,
                    latest_trade.price,
                    latest_trade.price,
                    latest_trade.price,
                    latest_trade.price,
                    1,
                )
                if self._submit_live_sell(
                    client,
                    now,
                    strategy,
                    position,
                    bar,
                    latest_trade.reason,
                    trade_timestamp=latest_trade.timestamp,
                ):
                    if self.config.mode != "live":
                        _write_live_equity(result.equity_curve, self.report_dir)
                        _write_live_metrics(result.metrics, self.report_dir)
                return
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

    def _write_live_state_report(self, now: datetime) -> None:
        row = self._live_equity_row(now)
        _write_live_state_equity(row, self.report_dir, self.strategy.initial_capital)
        metrics = _live_metrics_from_report(
            self.report_dir,
            strategy_name=_strategy_name(self.market),
            fallback_initial=self.strategy.initial_capital,
        )
        _write_live_metrics(metrics, self.report_dir)

    def _live_equity_row(self, now: datetime) -> dict[str, Any]:
        with self.lock:
            cash = float(self.cash)
            positions = [dict(position) for position in self.positions]
        total_shares = 0
        total_position_value = 0.0
        symbols = []
        mark_price = 0.0
        for position in positions:
            symbol = str(position.get("symbol") or "")
            shares = int(position.get("shares") or 0)
            if not symbol or shares <= 0:
                continue
            latest_bar = _latest_symbol_bar(self.bars, symbol, now.date())
            price = float(latest_bar.close) if latest_bar else float(position.get("entry_price") or 0.0)
            if price <= 0:
                price = float(position.get("entry_price") or 0.0)
            symbols.append(symbol)
            total_shares += shares
            total_position_value += shares * price
            mark_price = price if len(symbols) == 1 else 0.0
        equity = cash + total_position_value
        return {
            "datetime": now.replace(second=0, microsecond=0).isoformat(sep=" ", timespec="minutes"),
            "cash": round(cash, 2),
            "symbol": ",".join(symbols),
            "shares": total_shares,
            "mark_price": round(mark_price, 4),
            "equity": round(equity, 2),
            "drawdown": 0.0,
            "paused": 0,
        }

    def _try_live_direct_entry(
        self,
        client: KisClient,
        now: datetime,
        strategy: StockScannerConfig,
        metrics: dict[str, Any],
        equity_curve: list[dict[str, Any]],
        fresh_symbols: set[str] | None = None,
    ) -> bool:
        if self.config.mode != "live":
            return False
        risk_block = self._entry_risk_block(now, strategy)
        if risk_block:
            self._set_trade_message(risk_block)
            self._log_decision("entry_skip", now, reason="risk_control", detail=risk_block)
            return False
        entry_count = _live_buy_count_for_session(self.report_dir, now.date())
        if entry_count >= strategy.max_trades_per_day:
            self._set_trade_message(_daily_entry_limit_message(entry_count, strategy.max_trades_per_day))
            self._log_decision(
                "entry_skip",
                now,
                reason="daily_trade_limit",
                entries=entry_count,
                max_trades_per_day=strategy.max_trades_per_day,
            )
            return False
        if len(self.positions) >= self.config.max_positions:
            self._set_trade_message(_max_positions_message(len(self.positions), self.config.max_positions))
            self._log_decision(
                "entry_skip",
                now,
                reason="max_positions",
                positions=len(self.positions),
                max_positions=self.config.max_positions,
            )
            return False
        held_symbols = self._held_symbols()
        symbols = []
        for symbol in self.active_symbols:
            if symbol in held_symbols:
                continue
            if fresh_symbols is not None and symbol not in fresh_symbols:
                continue
            if strategy.stop_loss_reentry_block_minutes > 0:
                blocked_until = _live_symbol_stop_loss_reentry_block_until(
                    self.report_dir,
                    symbol,
                    now.date(),
                    strategy.stop_loss_reentry_block_minutes,
                )
                if blocked_until and now < blocked_until:
                    self._set_trade_message(
                        f"{symbol}: 손절 후 재진입 대기 ({blocked_until.strftime('%H:%M')}까지)"
                    )
                    self._log_decision(
                        "entry_skip",
                        now,
                        symbol=symbol,
                        reason="stop_loss_reentry_cooldown",
                        blocked_until=blocked_until.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    continue
            symbols.append(symbol)
        candidates = [
            candidate
            for symbol in symbols
            if (candidate := self._live_direct_entry_candidate(symbol, now, strategy)) is not None
        ]
        if not candidates:
            self._log_direct_entry_rejections(now, strategy)
            return False
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, bar, reason = candidates[0]
        shares = _live_order_shares(
            self.cash,
            bar.close,
            strategy,
            self.config.max_positions,
            self.strategy.initial_capital,
        )
        return self._submit_live_buy(client, now, strategy, bar, shares, reason, metrics, equity_curve)

    def _can_open_position(self, symbol: str, now: datetime, strategy: StockScannerConfig) -> bool:
        risk_block = self._entry_risk_block(now, strategy)
        if risk_block:
            self._set_trade_message(risk_block)
            self._log_decision("entry_skip", now, symbol=symbol, reason="risk_control", detail=risk_block)
            return False
        if symbol in self._held_symbols():
            self._set_trade_message(f"{symbol}: 이미 보유 중")
            self._log_decision("entry_skip", now, symbol=symbol, reason="already_held")
            return False
        if len(self.positions) >= self.config.max_positions:
            self._set_trade_message(_max_positions_message(len(self.positions), self.config.max_positions))
            self._log_decision(
                "entry_skip",
                now,
                symbol=symbol,
                reason="max_positions",
                positions=len(self.positions),
                max_positions=self.config.max_positions,
            )
            return False
        if strategy.stop_loss_reentry_block_minutes > 0:
            blocked_until = _live_symbol_stop_loss_reentry_block_until(
                self.report_dir,
                symbol,
                now.date(),
                strategy.stop_loss_reentry_block_minutes,
            )
            if blocked_until and now < blocked_until:
                self._set_trade_message(f"{symbol}: 손절 후 재진입 대기 ({blocked_until.strftime('%H:%M')}까지)")
                self._log_decision(
                    "entry_skip",
                    now,
                    symbol=symbol,
                    reason="stop_loss_reentry_cooldown",
                    blocked_until=blocked_until.strftime("%Y-%m-%d %H:%M:%S"),
                )
                return False
        entry_count = _live_buy_count_for_session(self.report_dir, now.date())
        if entry_count >= strategy.max_trades_per_day:
            self._set_trade_message(_daily_entry_limit_message(entry_count, strategy.max_trades_per_day))
            self._log_decision(
                "entry_skip",
                now,
                symbol=symbol,
                reason="daily_trade_limit",
                entries=entry_count,
                max_trades_per_day=strategy.max_trades_per_day,
            )
            return False
        return True

    def _held_symbols(self) -> set[str]:
        return {str(position.get("symbol") or "") for position in self.positions if position.get("symbol")}

    def _entry_risk_block(self, now: datetime, strategy: StockScannerConfig) -> str:
        self._sync_daily_state(now)
        if now.time() < strategy.entry_start_clock:
            return f"{strategy.entry_start_time} 전 신규 진입 대기"
        if now.time() >= strategy.entry_cutoff_clock:
            return f"{strategy.entry_cutoff_time or strategy.force_exit_time} 이후 신규 진입 중단"
        daily_return = self._daily_return(now)
        if strategy.daily_take_profit_pct > 0 and daily_return >= strategy.daily_take_profit_pct:
            return f"일일 목표 도달 ({daily_return * 100:.2f}%)"
        if strategy.daily_stop_loss_pct > 0 and daily_return <= -strategy.daily_stop_loss_pct:
            return f"일일 손실한도 도달 ({daily_return * 100:.2f}%)"
        losses, last_loss_at = _live_consecutive_losses(self.report_dir, now.date())
        if strategy.max_consecutive_losses > 0 and losses >= strategy.max_consecutive_losses:
            return f"연속 손절 한도 도달 ({losses}/{strategy.max_consecutive_losses}회)"
        if strategy.loss_cooldown_trades > 0 and losses >= strategy.loss_cooldown_trades and last_loss_at:
            cooldown_until = last_loss_at + timedelta(minutes=max(1, strategy.loss_cooldown_minutes))
            if now < cooldown_until:
                return f"{losses}연속 손절 후 쿨다운 ({cooldown_until.strftime('%H:%M')}까지)"
        return ""

    def _sync_daily_state(self, now: datetime) -> None:
        if self.day_state_date == now.date():
            return
        self.day_state_date = now.date()
        # 장중 재기동 대비: 오늘 이미 실현된 손익을 빼서 일중 시작점을 추정
        current_equity = self._mark_to_market_equity(now.date())
        realized_today = _live_realized_today(self.report_dir, now.date())
        baseline = current_equity - realized_today
        self.day_start_cash = max(1.0, baseline)

    def _daily_return(self, now: datetime) -> float:
        if self.day_start_cash <= 0:
            return 0.0
        return (self._mark_to_market_equity(now.date()) / self.day_start_cash) - 1.0

    def _mark_to_market_equity(self, session: object) -> float:
        equity = float(self.cash)
        for position in self.positions:
            symbol = str(position.get("symbol") or "")
            latest = _latest_symbol_bar(self.bars, symbol, session)
            mark_price = latest.close if latest else float(position.get("entry_price") or 0.0)
            equity += int(position.get("shares") or 0) * mark_price
        return equity

    def _position_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        symbol = str(symbol)
        for position in self.positions:
            if str(position.get("symbol") or "") == symbol:
                return position
        return None

    def _try_live_direct_exit(
        self,
        client: KisClient,
        now: datetime,
        strategy: StockScannerConfig,
        fresh_symbols: set[str] | None = None,
    ) -> bool:
        if self.config.mode != "live" or not self.positions:
            return False
        sold_any = False
        for position in list(self.positions):
            if self._try_live_direct_exit_position(client, now, strategy, position, fresh_symbols):
                sold_any = True
        return sold_any

    def _try_live_direct_exit_position(
        self,
        client: KisClient,
        now: datetime,
        strategy: StockScannerConfig,
        position: dict[str, Any],
        fresh_symbols: set[str] | None = None,
    ) -> bool:
        symbol = str(position.get("symbol") or "")
        shares = int(position.get("shares") or 0)
        entry_price = float(position.get("entry_price") or 0.0)
        if not symbol or shares <= 0 or entry_price <= 0:
            return False
        if fresh_symbols is not None and symbol not in fresh_symbols:
            return False
        latest = _latest_symbol_bar(self.bars, symbol, now.date())
        if not latest:
            return False
        highest_price = max(float(position.get("highest_price") or entry_price), latest.high)
        position["highest_price"] = highest_price
        stages = int(position.get("partial_stages") or 0)
        partial_threshold = strategy.partial_take_profit_pct * (stages + 1)
        reason = ""
        entry_date = _position_entry_date(position)
        if entry_date and latest.session > entry_date:
            reason = "live_overnight_force_exit"
        elif now.time() >= strategy.force_exit_clock:
            reason = "live_force_exit"
        elif latest.low <= entry_price * (1.0 - strategy.stop_loss_pct):
            reason = "live_stop_loss"
        elif (
            strategy.partial_take_profit_pct > 0
            and stages < 2
            and shares > 1
            and latest.high >= entry_price * (1.0 + partial_threshold)
        ):
            partial_shares = max(1, min(shares - 1, math.floor(shares * strategy.partial_sell_ratio)))
            return self._submit_live_sell(client, now, strategy, position, latest, "live_partial_take_profit", shares_to_sell=partial_shares)
        elif latest.high >= entry_price * (1.0 + strategy.take_profit_pct):
            reason = "live_take_profit"
        elif highest_price > entry_price and latest.low <= highest_price * (1.0 - strategy.trailing_stop_pct):
            reason = "live_trailing_stop"
        elif strategy.time_stop_minutes > 0 and _position_held_minutes(position, now) >= strategy.time_stop_minutes:
            reason = "live_time_stop"
        if not reason:
            return False
        return self._submit_live_sell(client, now, strategy, position, latest, reason)

    def _submit_live_buy(
        self,
        client: KisClient,
        now: datetime,
        strategy: StockScannerConfig,
        bar: StockBar,
        shares: int,
        reason: str,
        metrics: dict[str, Any] | None = None,
        equity_curve: list[dict[str, Any]] | None = None,
        *,
        trade_timestamp: datetime | None = None,
    ) -> bool:
        if shares <= 0:
            self._set_trade_message(f"{bar.symbol}: 주문 가능 수량 없음")
            self._log_decision("entry_skip", now, symbol=bar.symbol, reason="no_orderable_shares", price=bar.close)
            return False
        response = self._place_order(client, "buy", bar.symbol, shares, live=True, price=bar.close)
        if not _order_succeeded(response, True):
            self._set_trade_message(f"주문 실패: BUY {bar.symbol} ({_order_message(response)})")
            self._log_decision("order_failed", now, side="buy", symbol=bar.symbol, shares=shares, price=bar.close, response=response)
            return False
        order_meta = parse_order_response(response)
        gross = shares * bar.close
        cost = gross * (strategy.commission_rate + strategy.slippage_rate)
        with self.lock:
            self.cash = round(max(0.0, self.cash - gross - cost), 2)
            self.positions.append(
                {
                    "symbol": bar.symbol,
                    "shares": shares,
                    "entry_price": bar.close,
                    "highest_price": bar.close,
                    "entry_time": (trade_timestamp or now).isoformat(sep=" "),
                    "order_no": order_meta.get("order_no", ""),
                }
            )
        # 라이브 모드: KIS 잔고 조회로 실제 체결가/수량 보정
        actual_fill = self._reconcile_after_order(client, bar.symbol, "buy", now)
        actual_position = next((pos for pos in self.positions if str(pos.get("symbol") or "") == bar.symbol), None)
        actual_shares = int(actual_position.get("shares") or 0) if actual_position else shares
        actual_price = float(actual_position.get("entry_price") or 0.0) if actual_position else bar.close
        if actual_shares <= 0:
            actual_shares = shares
            actual_price = bar.close
        gross = actual_shares * actual_price
        cost = gross * (strategy.commission_rate + strategy.slippage_rate)
        trade = ScannerTrade(
            timestamp=trade_timestamp or now,
            action="BUY",
            symbol=bar.symbol,
            shares=actual_shares,
            price=round(actual_price, 4),
            gross=round(gross, 2),
            cost=round(cost, 2),
            realized_pnl=0.0,
            cash_after=round(self.cash, 2),
            reason=reason,
        )
        trade_key = f"{trade.timestamp}|{trade.action}|{trade.symbol}|{trade.shares}|{trade.reason}"
        _append_live_trade(trade, response, self.config.mode, trade_key, self.report_dir)
        self._log_decision(
            "order_submitted",
            now,
            side="buy",
            symbol=bar.symbol,
            shares=actual_shares,
            price=actual_price,
            reason=reason,
            response=response,
            cash_after=self.cash,
            positions=[dict(position) for position in self.positions],
        )
        if equity_curve and self.config.mode != "live":
            _write_live_equity(equity_curve, self.report_dir)
        if metrics and self.config.mode != "live":
            _write_live_metrics(metrics, self.report_dir)
        with self.lock:
            self.status["orders"] = int(self.status.get("orders", 0)) + 1
            self.status["trade_message"] = f"최근 주문: BUY {trade.symbol} {trade.shares}주 ({trade.reason})"
        return True

    def _submit_live_sell(
        self,
        client: KisClient,
        now: datetime,
        strategy: StockScannerConfig,
        position: dict[str, Any],
        latest: StockBar,
        reason: str,
        *,
        trade_timestamp: datetime | None = None,
        shares_to_sell: int | None = None,
    ) -> bool:
        symbol = str(position.get("symbol") or "")
        shares = int(position.get("shares") or 0)
        entry_price = float(position.get("entry_price") or 0.0)
        order_shares = max(0, min(shares, shares_to_sell or shares))
        if order_shares <= 0:
            return False
        response = self._place_order(client, "sell", symbol, order_shares, live=True, price=latest.close)
        if not _order_succeeded(response, True):
            self._set_trade_message(f"주문 실패: SELL {symbol} ({_order_message(response)})")
            self._log_decision("order_failed", now, side="sell", symbol=symbol, shares=order_shares, price=latest.close, response=response)
            return False
        order_meta = parse_order_response(response)
        gross = order_shares * latest.close
        cost = gross * (strategy.commission_rate + strategy.sell_tax_rate + strategy.slippage_rate)
        realized_pnl = gross - cost - (entry_price * order_shares)
        remaining_shares = shares - order_shares
        action = "SELL_PARTIAL" if remaining_shares > 0 else "SELL_ALL"
        cash_before = self.cash
        with self.lock:
            self.cash = round(self.cash + gross - cost, 2)
            if remaining_shares > 0:
                position["shares"] = remaining_shares
                position["partial_taken"] = True
                position["partial_stages"] = int(position.get("partial_stages") or 0) + 1
            else:
                self.positions = [current for current in self.positions if current is not position and current.get("symbol") != symbol]
        # 라이브 모드: KIS 잔고 조회로 실제 체결 결과 보정
        actual_fill = self._reconcile_after_order(client, symbol, "sell", now)
        if actual_fill is not None:
            actual_remaining = int(actual_fill.get("quantity") or 0)
            # 보수적 보정: 잔고에 의해 실제 처분된 수량 추정
            estimated_filled = max(0, shares - actual_remaining)
            if estimated_filled > 0 and estimated_filled != order_shares:
                order_shares = estimated_filled
                gross = order_shares * latest.close
                cost = gross * (strategy.commission_rate + strategy.sell_tax_rate + strategy.slippage_rate)
                realized_pnl = gross - cost - (entry_price * order_shares)
                action = "SELL_PARTIAL" if actual_remaining > 0 else "SELL_ALL"
            cash_diff = self.cash - cash_before
            if abs(cash_diff) < 1.0 and self.cash <= cash_before:
                # reconcile에서 실제 cash 갱신을 못한 경우 추정치 유지
                pass
        _ = order_meta
        trade = ScannerTrade(
            timestamp=trade_timestamp or now,
            action=action,
            symbol=symbol,
            shares=order_shares,
            price=round(latest.close, 4),
            gross=round(gross, 2),
            cost=round(cost, 2),
            realized_pnl=round(realized_pnl, 2),
            cash_after=round(self.cash, 2),
            reason=reason,
        )
        trade_key = f"{trade.timestamp}|{trade.action}|{trade.symbol}|{trade.shares}|{trade.reason}"
        _append_live_trade(trade, response, self.config.mode, trade_key, self.report_dir)
        self._log_decision(
            "order_submitted",
            now,
            side="sell",
            symbol=symbol,
            shares=order_shares,
            price=latest.close,
            reason=reason,
            response=response,
            cash_after=self.cash,
            positions=[dict(position) for position in self.positions],
        )
        with self.lock:
            self.status["orders"] = int(self.status.get("orders", 0)) + 1
            self.status["trade_message"] = f"최근 주문: {trade.action} {trade.symbol} {trade.shares}주 ({trade.reason})"
        return True

    def _live_direct_entry_candidate(
        self,
        symbol: str,
        now: datetime,
        strategy: StockScannerConfig,
    ) -> tuple[float, StockBar, str] | None:
        profile = self._direct_entry_profile(now, strategy)
        symbol_bars = sorted((bar for bar in self.bars if bar.symbol == symbol), key=lambda bar: bar.timestamp)
        current_bars = [bar for bar in symbol_bars if bar.session == now.date()]
        if len(current_bars) < profile.min_bars:
            return None
        latest = current_bars[-1]
        previous_close = _previous_close_for(symbol_bars, latest)
        if previous_close <= 0:
            return None
        session_start = current_bars[0].timestamp
        if latest.timestamp < session_start + timedelta(minutes=strategy.observation_minutes):
            return None
        setup_move = (latest.close / previous_close) - 1.0
        if not (strategy.gap_min_pct <= setup_move <= strategy.gap_max_pct):
            return None
        if profile.max_setup_move is not None and setup_move > profile.max_setup_move:
            return None
        if latest.volume <= 0:
            return None
        if self.market == NASDAQ_SURGE_MARKET:
            recent_bars = current_bars[-3:]
            if len(recent_bars) < 3:
                return None
            recent_value = sum(bar.value for bar in recent_bars)
            if recent_value < self._nasdaq_surge_recent_trade_value_threshold(now):
                return None
        if self.market == DOMESTIC_SURGE_MARKET:
            spread_reason = _spread_reject_reason(latest.spread_pct, strategy)
            if spread_reason:
                return None
            recent_bars = current_bars[-3:]
            if len(recent_bars) < 3:
                return None
            recent_value = sum(bar.value for bar in recent_bars)
            if recent_value < DOMESTIC_SURGE_MIN_RECENT_TRADE_VALUE:
                return None
            if _recent_vi_proxy_blocked(current_bars, strategy):
                return None
        # 직전 봉 고점을 넘지 못하면 모멘텀 지속 신호로 보지 않는다.
        if len(current_bars) >= 2:
            prev_bar = current_bars[-2]
            if latest.close <= prev_bar.high * (1.0 + (strategy.min_edge_rate * 0.5)):
                return None
        previous_volumes = [float(bar.volume) for bar in current_bars[:-1] if bar.volume > 0]
        volume_avg = sum(previous_volumes[-strategy.volume_sma :]) / min(len(previous_volumes), strategy.volume_sma) if previous_volumes else 0.0
        volume_ratio = latest.volume / volume_avg if volume_avg else 1.0
        if volume_ratio < profile.min_volume_ratio:
            return None
        vwap = _latest_vwap(current_bars)
        if vwap > 0 and latest.close < vwap * profile.min_vwap_ratio:
            return None
        if self.market == DOMESTIC_ETF_MARKET and not self._domestic_etf_index_proxy_ok(now):
            return None
        if vwap > 0 and profile.max_extension_pct is not None and (latest.close / vwap) - 1.0 > profile.max_extension_pct:
            return None
        lookback = current_bars[max(0, len(current_bars) - 4)]
        if latest.close <= lookback.close * (1.0 + profile.min_lookback_move):
            return None
        opening_cutoff = session_start + timedelta(minutes=strategy.observation_minutes)
        opening_bars = [bar for bar in current_bars if bar.timestamp < opening_cutoff]
        opening_high = max((bar.high for bar in opening_bars), default=latest.high)
        opening_breakout = latest.close > opening_high * (1.0 + strategy.min_edge_rate)
        if profile.require_opening_breakout and not opening_breakout:
            return None
        breakout_bonus = 1.0 if opening_breakout else 0.0
        score = (setup_move * 100.0) + min(volume_ratio, 5.0) + breakout_bonus
        return score, latest, profile.reason

    def _nasdaq_surge_recent_trade_value_threshold(self, now: datetime) -> float:
        if self._market_session(now) == SESSION_PREMARKET:
            return NASDAQ_SURGE_PREMARKET_MIN_RECENT_TRADE_VALUE
        return NASDAQ_SURGE_MIN_RECENT_TRADE_VALUE

    def _domestic_etf_index_proxy_ok(self, now: datetime) -> bool:
        proxy_states = []
        for proxy_symbol in DOMESTIC_ETF_INDEX_PROXIES:
            current_bars = sorted(
                (bar for bar in self.bars if bar.symbol == proxy_symbol and bar.session == now.date()),
                key=lambda bar: bar.timestamp,
            )
            if len(current_bars) < 2:
                continue
            vwap = _latest_vwap(current_bars)
            proxy_states.append(vwap > 0 and current_bars[-1].close >= vwap)
        # 데이터가 부족하면 진입 차단 (전일 종가 시드만 있는 장 초반 보호)
        if not proxy_states:
            return False
        return any(proxy_states)

    def _log_direct_entry_rejections(self, now: datetime, strategy: StockScannerConfig) -> None:
        if not self.active_symbols:
            return
        rejected = []
        for symbol in self.active_symbols[:12]:
            rejected.append({"symbol": symbol, "reason": self._symbol_entry_reason(symbol, now)})
        self._log_decision("entry_rejected", now, rejected=rejected, strategy=_strategy_snapshot(strategy))

    def _log_decision(self, event: str, now: datetime, **payload: Any) -> None:
        _append_decision_log(
            self.report_dir,
            {
                "timestamp": now.isoformat(sep=" ", timespec="seconds"),
                "market": self.market,
                "mode": self.config.mode,
                "event": event,
                **payload,
            },
        )

    def _direct_entry_profile(self, now: datetime, strategy: StockScannerConfig) -> DirectEntryProfile:
        if self.market == NASDAQ_SURGE_MARKET:
            if self._market_session(now) == SESSION_PREMARKET:
                return DirectEntryProfile(
                    min_bars=max(5, strategy.volume_sma + 1),
                    min_volume_ratio=max(1.8, strategy.volume_factor),
                    min_vwap_ratio=1.002,
                    min_lookback_move=0.018,
                    require_opening_breakout=True,
                    max_setup_move=min(strategy.gap_max_pct, 0.18),
                    max_extension_pct=min(strategy.max_extension_pct, 0.06),
                    reason="live_nasdaq_surge_premarket_breakout_entry",
                )
            return DirectEntryProfile(
                min_bars=max(4, strategy.volume_sma + 1),
                min_volume_ratio=max(1.2, strategy.volume_factor),
                min_vwap_ratio=1.0,
                min_lookback_move=0.015,
                max_setup_move=strategy.gap_max_pct,
                max_extension_pct=strategy.max_extension_pct,
                reason="live_nasdaq_surge_breakout_entry",
            )
        if self.market == OVERSEAS_MARKET:
            if self._market_session(now) == SESSION_PREMARKET:
                return DirectEntryProfile(
                    min_bars=max(5, strategy.volume_sma + 1),
                    min_volume_ratio=max(1.6, strategy.volume_factor),
                    min_vwap_ratio=1.003,
                    min_lookback_move=0.003,
                    require_opening_breakout=True,
                    max_setup_move=min(strategy.gap_max_pct, 0.08),
                    max_extension_pct=min(strategy.max_extension_pct, 0.035),
                    reason="live_premarket_momentum_entry",
                )
            return DirectEntryProfile(
                min_bars=max(4, strategy.volume_sma + 1),
                min_volume_ratio=max(1.2, min(strategy.volume_factor, 1.6)),
                min_vwap_ratio=1.0,
                min_lookback_move=0.002,
                require_opening_breakout=True,
                max_extension_pct=strategy.max_extension_pct,
                reason="live_overseas_momentum_entry",
            )
        if self.market == DOMESTIC_ETF_MARKET:
            return DirectEntryProfile(
                min_bars=max(2, strategy.volume_sma + 1),
                min_volume_ratio=max(1.0, strategy.volume_factor),
                min_vwap_ratio=0.999,
                min_lookback_move=0.0004,
                max_setup_move=strategy.gap_max_pct,
                max_extension_pct=strategy.max_extension_pct,
                reason="live_domestic_etf_vwap_entry",
            )
        if self.market == DOMESTIC_SURGE_MARKET:
            return DirectEntryProfile(
                min_bars=max(4, strategy.volume_sma + 1),
                min_volume_ratio=max(1.0, strategy.volume_factor),
                min_vwap_ratio=1.0,
                min_lookback_move=0.02,
                max_setup_move=strategy.gap_max_pct,
                max_extension_pct=strategy.max_extension_pct,
                reason="live_domestic_surge_breakout_entry",
            )
        return DirectEntryProfile(max_extension_pct=strategy.max_extension_pct)

    def _set_trade_message(self, message: str) -> None:
        with self.lock:
            self.status["trade_message"] = message

    def _entry_wait_message(self, now: datetime) -> str:
        if not self.active_symbols:
            return "자동선별 종목 없음"
        strategy = self._active_strategy(now)
        if _is_overseas_market(self.market) and self._market_session(now) == SESSION_PREMARKET:
            prefix = "프리장 "
        else:
            prefix = ""
        if now.time() < strategy.entry_start_clock:
            return f"{strategy.entry_start_time} 전 신규 진입 대기"
        if now.time() >= strategy.entry_cutoff_clock:
            return f"{strategy.entry_cutoff_time or strategy.force_exit_time} 이후 신규 진입 중단"
        entry_count = _live_buy_count_for_session(self.report_dir, now.date())
        if entry_count >= strategy.max_trades_per_day:
            return _daily_entry_limit_message(entry_count, strategy.max_trades_per_day)
        if len(self.positions) >= self.config.max_positions:
            return _max_positions_message(len(self.positions), self.config.max_positions)

        reasons: list[tuple[str, str]] = []
        for symbol in self.active_symbols:
            reason = self._symbol_entry_reason(symbol, now)
            if reason:
                reasons.append((symbol, reason))
        if not reasons:
            return f"{prefix}매수 조건 대기"
        messages = [f"{symbol}: {reason}" for symbol, reason in reasons[:5]]
        summary = _reason_summary([reason for _, reason in reasons])
        if len(reasons) > len(messages):
            messages.append(f"외 {len(reasons) - len(messages)}종목")
        if summary:
            messages.append(f"요약: {summary}")
        return f"{prefix}{' / '.join(messages)}"

    def _active_strategy(self, now: datetime) -> StockScannerConfig:
        if self.market == NASDAQ_SURGE_MARKET:
            if self._market_session(now) == SESSION_PREMARKET:
                self._set_strategy_tone("premarket")
                return replace(
                    self.strategy,
                    observation_minutes=max(self.strategy.observation_minutes, 10),
                    gap_min_pct=max(self.strategy.gap_min_pct, 0.03),
                    gap_max_pct=min(max(self.strategy.gap_max_pct, 0.18), 0.22),
                    volume_sma=max(self.strategy.volume_sma, 4),
                    volume_factor=max(self.strategy.volume_factor, 2.0),
                    min_atr_pct=max(self.strategy.min_atr_pct, 0.008),
                    max_atr_pct=min(max(self.strategy.max_atr_pct, 0.12), 0.18),
                    max_extension_pct=min(self.strategy.max_extension_pct, 0.06),
                    risk_per_trade_pct=min(self.strategy.risk_per_trade_pct, 0.006),
                    max_position_pct=min(self.strategy.max_position_pct, 0.35),
                    stop_loss_pct=max(self.strategy.stop_loss_pct, 0.02),
                    take_profit_pct=max(self.strategy.take_profit_pct, 0.04),
                    trailing_stop_pct=max(self.strategy.trailing_stop_pct, 0.025),
                    daily_stop_loss_pct=min(self.strategy.daily_stop_loss_pct, 0.025),
                    max_trades_per_day=min(self.strategy.max_trades_per_day, 3),
                )
            self._set_strategy_tone("neutral")
            return self.strategy
        if self.market == OVERSEAS_MARKET and self._market_session(now) == SESSION_PREMARKET:
            self._set_strategy_tone("premarket")
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
        if self.market == OVERSEAS_MARKET and self.config.mode == "live":
            base = replace(
                self.strategy,
                observation_minutes=min(self.strategy.observation_minutes, 15),
                volume_factor=max(1.25, self.strategy.volume_factor),
                min_atr_pct=max(self.strategy.min_atr_pct, 0.004),
                max_trades_per_day=min(self.strategy.max_trades_per_day, 6),
            )
            tone = self._stable_tone(now, base)
            self._set_strategy_tone(tone)
            return self._strategy_by_tone(base, tone)
        if self.market == DOMESTIC_ETF_MARKET and self.config.mode == "live":
            base = replace(
                self.strategy,
                observation_minutes=min(self.strategy.observation_minutes, 5),
                top_value_rank=max(self.strategy.top_value_rank, 10),
                gap_min_pct=min(self.strategy.gap_min_pct, 0.0),
                gap_max_pct=min(max(self.strategy.gap_max_pct, 0.03), 0.06),
                volume_sma=min(self.strategy.volume_sma, 2),
                volume_factor=min(self.strategy.volume_factor, 1.05),
                atr_period=min(self.strategy.atr_period, 3),
                min_atr_pct=min(self.strategy.min_atr_pct, 0.0005),
                max_atr_pct=min(max(self.strategy.max_atr_pct, 0.015), 0.03),
                min_edge_bps=min(self.strategy.min_edge_bps, 3.0),
                max_extension_pct=min(max(self.strategy.max_extension_pct, 0.003), 0.006),
                risk_per_trade_pct=min(self.strategy.risk_per_trade_pct, 0.01),
                stop_loss_pct=min(self.strategy.stop_loss_pct, 0.0025),
                take_profit_pct=min(max(self.strategy.take_profit_pct, 0.0025), 0.004),
                trailing_stop_pct=min(max(self.strategy.trailing_stop_pct, 0.0015), 0.003),
                daily_stop_loss_pct=min(self.strategy.daily_stop_loss_pct, 0.007),
                daily_take_profit_pct=max(self.strategy.daily_take_profit_pct, 0.004),
                max_trades_per_day=min(max(self.strategy.max_trades_per_day, 3), 5),
                cooldown_bars=max(self.strategy.cooldown_bars, 1),
            )
            tone = self._stable_tone(now, base)
            self._set_strategy_tone(tone)
            return self._strategy_by_tone(base, tone)
        if self.market == DEFAULT_MARKET and self.config.mode == "live":
            base = replace(
                self.strategy,
                observation_minutes=min(self.strategy.observation_minutes, 10),
                top_value_rank=max(self.strategy.top_value_rank, 8),
                gap_min_pct=min(self.strategy.gap_min_pct, 0.008),
                gap_max_pct=max(self.strategy.gap_max_pct, 0.12),
                volume_sma=min(self.strategy.volume_sma, 3),
                volume_factor=min(self.strategy.volume_factor, 1.3),
                atr_period=min(self.strategy.atr_period, 4),
                min_atr_pct=min(self.strategy.min_atr_pct, 0.0025),
                max_atr_pct=max(self.strategy.max_atr_pct, 0.08),
                min_edge_bps=min(self.strategy.min_edge_bps, 15.0),
                max_extension_pct=max(self.strategy.max_extension_pct, 0.07),
                max_trades_per_day=max(self.strategy.max_trades_per_day, 8),
                cooldown_bars=min(self.strategy.cooldown_bars, 1),
            )
            tone = self._stable_tone(now, base)
            self._set_strategy_tone(tone)
            return self._strategy_by_tone(base, tone)
        self._set_strategy_tone("neutral")
        return self.strategy

    def _set_strategy_tone(self, tone: str) -> None:
        with self.lock:
            self.status["strategy_tone"] = tone

    def _stable_tone(self, now: datetime, strategy: StockScannerConfig) -> str:
        """시간 기반 히스테리시스 적용 톤. 공격 전환은 느리게, 방어 전환은 빠르게 확인한다."""
        signal = self._market_tone_signal(now, strategy)
        raw = signal.tone
        if self._tone_current_since is None:
            self._tone_current_since = now - timedelta(seconds=TONE_MIN_HOLD_SECONDS)
        if raw == self._tone_pending:
            self._tone_pending_count += 1
        else:
            self._tone_pending = raw
            self._tone_pending_count = 1
            self._tone_pending_since = now
        if self._tone_pending_since is None:
            self._tone_pending_since = now
        if raw == self._tone_current:
            return self._tone_current
        if self._urgent_conservative_signal(now, strategy, signal):
            return self._commit_tone("conservative", now)
        held_seconds = (now - self._tone_current_since).total_seconds()
        pending_seconds = (now - self._tone_pending_since).total_seconds()
        if held_seconds < TONE_MIN_HOLD_SECONDS:
            return self._tone_current
        if pending_seconds >= _tone_confirm_seconds(raw):
            return self._commit_tone(raw, now)
        return self._tone_current

    def _market_tone(self, now: datetime, strategy: StockScannerConfig) -> str:
        return self._market_tone_signal(now, strategy).tone

    def _market_tone_signal(self, now: datetime, strategy: StockScannerConfig) -> MarketToneSignal:
        if not strategy.adaptive_market_regime:
            return MarketToneSignal()
        candidates = list(DOMESTIC_ETF_INDEX_PROXIES) if not _is_overseas_market(self.market) else []
        candidates.extend(self.active_symbols)
        symbols: list[str] = []
        for symbol in candidates:
            if symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            return MarketToneSignal()

        move_samples: list[float] = []
        above_vwap = 0
        for symbol in symbols[:8]:
            symbol_bars = sorted((bar for bar in self.bars if bar.symbol == symbol), key=lambda bar: bar.timestamp)
            current_bars = [bar for bar in symbol_bars if bar.session == now.date()]
            if len(current_bars) < 3:
                continue
            latest = current_bars[-1]
            previous_close = _previous_close_for(symbol_bars, latest)
            if previous_close <= 0:
                continue
            move_samples.append((latest.close / previous_close) - 1.0)
            vwap = _latest_vwap(current_bars)
            if vwap > 0 and latest.close >= vwap:
                above_vwap += 1

        sample_count = len(move_samples)
        if sample_count < 3:
            return MarketToneSignal(sample_count=sample_count)
        avg_move = sum(move_samples) / sample_count
        breadth = above_vwap / sample_count
        if avg_move >= 0.006 and breadth >= 0.6:
            tone = "aggressive"
        elif avg_move <= 0.0015 or breadth < 0.45:
            tone = "conservative"
        else:
            tone = "neutral"
        return MarketToneSignal(tone=tone, avg_move=avg_move, breadth=breadth, sample_count=sample_count)

    def _commit_tone(self, tone: str, now: datetime) -> str:
        if tone != self._tone_current:
            self._tone_current = tone
            self._tone_current_since = now
        return self._tone_current

    def _urgent_conservative_signal(self, now: datetime, strategy: StockScannerConfig, signal: MarketToneSignal) -> bool:
        if signal.tone != "conservative":
            return False
        if signal.sample_count >= 3 and signal.avg_move <= TONE_EXTREME_WEAK_MOVE and signal.breadth <= TONE_EXTREME_WEAK_BREADTH:
            return True
        if strategy.daily_stop_loss_pct > 0:
            self._sync_daily_state(now)
            if self._daily_return(now) <= -(strategy.daily_stop_loss_pct * TONE_URGENT_STOP_RATIO):
                return True
        return False

    def _strategy_by_tone(self, strategy: StockScannerConfig, tone: str) -> StockScannerConfig:
        if tone == "aggressive":
            return replace(
                strategy,
                volume_factor=max(1.1, strategy.volume_factor - 0.15),
                gap_min_pct=max(0.0, strategy.gap_min_pct - 0.002),
                risk_per_trade_pct=min(0.015, strategy.risk_per_trade_pct * 1.15),
                max_trades_per_day=min(12, strategy.max_trades_per_day + 2),
                max_position_pct=min(1.0, strategy.max_position_pct * 1.1),
            )
        if tone == "conservative":
            return replace(
                strategy,
                entry_start_time=_add_minutes_to_clock(strategy.entry_start_clock, 20),
                volume_factor=min(2.2, strategy.volume_factor + 0.3),
                gap_min_pct=min(0.03, strategy.gap_min_pct + 0.003),
                risk_per_trade_pct=max(0.004, strategy.risk_per_trade_pct * 0.7),
                max_trades_per_day=max(3, min(strategy.max_trades_per_day, 5)),
                max_position_pct=max(0.2, strategy.max_position_pct * 0.75),
                stop_loss_pct=max(strategy.stop_loss_pct, 0.011),
                trailing_stop_pct=max(strategy.trailing_stop_pct, 0.012),
            )
        return strategy

    def _symbol_entry_reason(self, symbol: str, now: datetime) -> str:
        strategy = self._active_strategy(now)
        symbol_bars = sorted((bar for bar in self.bars if bar.symbol == symbol), key=lambda bar: bar.timestamp)
        if not symbol_bars:
            return "현재가 수집 대기"
        current_bars = [bar for bar in symbol_bars if bar.session == now.date()]
        if not current_bars:
            return f"오늘 {self.config.bar_minutes}분봉 수집 대기"

        latest = current_bars[-1]
        previous_close = _previous_close_for(symbol_bars, latest)
        if previous_close <= 0:
            return "전일 종가 기준값 대기"

        session_start = current_bars[0].timestamp
        if latest.timestamp < session_start + timedelta(minutes=strategy.observation_minutes):
            elapsed_minutes = max(0, int((latest.timestamp - session_start).total_seconds() // 60))
            return f"진입 전 관찰 중 ({elapsed_minutes}/{strategy.observation_minutes}분)"

        setup_move = (latest.close / previous_close) - 1.0
        if setup_move < strategy.gap_min_pct:
            return f"상승률 {setup_move * 100:.1f}% < {strategy.gap_min_pct * 100:.1f}%"
        if setup_move > strategy.gap_max_pct:
            return f"상승률 {setup_move * 100:.1f}% > {strategy.gap_max_pct * 100:.1f}%"
        if self.market == NASDAQ_SURGE_MARKET:
            recent_bars = current_bars[-3:]
            if len(recent_bars) < 3:
                return "최근 3분 거래대금 계산 대기"
            recent_value = sum(bar.value for bar in recent_bars)
            threshold = self._nasdaq_surge_recent_trade_value_threshold(now)
            if recent_value < threshold:
                return f"최근 3분 거래대금 ${recent_value / 1_000_000:.1f}M < ${threshold / 1_000_000:.1f}M"
        if self.market == DOMESTIC_SURGE_MARKET:
            spread_reason = _spread_reject_reason(latest.spread_pct, strategy)
            if spread_reason:
                return spread_reason
            recent_bars = current_bars[-3:]
            if len(recent_bars) < 3:
                return "최근 3분 거래대금 계산 대기"
            recent_value = sum(bar.value for bar in recent_bars)
            if recent_value < DOMESTIC_SURGE_MIN_RECENT_TRADE_VALUE:
                return f"최근 3분 거래대금 {recent_value / 100_000_000:.1f}억 < 10.0억"
            if _recent_vi_proxy_blocked(current_bars, strategy):
                return "VI 프록시 쿨다운"

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
        if _is_overseas_market(self.market):
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
            price=max(1, int(round(price))) if self.market == DOMESTIC_SURGE_MARKET and side == "buy" else 0,
            order_division="00" if self.market == DOMESTIC_SURGE_MARKET and side == "buy" else "01",
            live=live,
        )

    def _query_balance_holding(self, client: KisClient, symbol: str) -> dict[str, float] | None:
        """라이브 모드에서 KIS 잔고 조회로 해당 종목의 실제 보유 수량/평균단가/현금을 가져온다.
        실패하거나 paper 모드면 None."""
        if self.config.mode != "live" or not self.config.account_no:
            return None
        try:
            if _is_overseas_market(self.market):
                response = client.inquire_overseas_balance(
                    account_no=self.config.account_no,
                    product_code=self.config.product_code,
                    exchange_code=self.config.exchange_code,
                    currency=self.config.currency,
                    live=True,
                )
                parsed = parse_overseas_balance_response(response)
            else:
                response = client.inquire_balance(
                    account_no=self.config.account_no,
                    product_code=self.config.product_code,
                    live=True,
                )
                parsed = parse_balance_response(response)
        except Exception:  # noqa: BLE001
            return None
        if str(parsed.get("rt_cd") or "") not in {"0", ""}:
            return None
        target = symbol.strip().upper()
        for holding in parsed.get("holdings") or []:
            holding_symbol = str(holding.get("symbol") or "").strip().upper()
            if holding_symbol == target:
                return {
                    "quantity": float(holding.get("quantity") or 0.0),
                    "average_price": float(holding.get("average_price") or 0.0),
                    "cash": float(parsed.get("cash") or 0.0),
                }
        return {"quantity": 0.0, "average_price": 0.0, "cash": float(parsed.get("cash") or 0.0)}

    def _reconcile_after_order(
        self,
        client: KisClient,
        symbol: str,
        side: str,
        now: datetime,
    ) -> dict[str, float] | None:
        """주문 직후 잔고를 조회해 self.cash, position[shares]/entry_price를 실제 값으로 보정.

        주문 체결이 비동기일 수 있어 best-effort로 한 번만 시도한다. 실패 시 추정 값 유지.
        """
        holding = self._query_balance_holding(client, symbol)
        if holding is None:
            return None
        actual_qty = int(holding["quantity"])
        avg_price = float(holding["average_price"])
        actual_cash = float(holding["cash"])
        with self.lock:
            position = next((pos for pos in self.positions if str(pos.get("symbol") or "") == symbol), None)
            if side == "buy":
                if actual_qty <= 0:
                    self._log_decision(
                        "fill_pending",
                        now,
                        side=side,
                        symbol=symbol,
                        message="잔고 미반영 (체결 지연 가능)",
                    )
                    return holding
                if position:
                    position["shares"] = actual_qty
                    if avg_price > 0:
                        position["entry_price"] = avg_price
                        if float(position.get("highest_price") or 0.0) < avg_price:
                            position["highest_price"] = avg_price
            elif side == "sell":
                if actual_qty <= 0 and position:
                    self.positions = [p for p in self.positions if str(p.get("symbol") or "") != symbol]
                elif position and actual_qty > 0:
                    position["shares"] = actual_qty
            if actual_cash > 0:
                self.cash = round(actual_cash, 2)
        self._log_decision(
            "fill_reconciled",
            now,
            side=side,
            symbol=symbol,
            actual_qty=actual_qty,
            avg_price=avg_price,
            cash=actual_cash,
        )
        return holding


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


def _append_decision_log(report_dir: Path, payload: dict[str, Any]) -> None:
    ensure_live_report(report_dir)
    safe_payload = _json_safe(payload)
    with (report_dir / "decision_log.jsonl").open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _price_error_payload(
    symbol: str,
    message: str,
    parsed: dict[str, Any],
    *,
    reason_key: str = "error",
    price: float | int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"symbol": symbol, reason_key: message}
    if price is not None:
        payload["price"] = price
    meta = parsed.get("kis_response")
    if isinstance(meta, dict):
        payload["kis_response"] = meta
    return payload


def _kis_response_summary(data: dict[str, Any]) -> dict[str, Any]:
    output = data.get("output")
    summary: dict[str, Any] = {
        "rt_cd": data.get("rt_cd", ""),
        "msg_cd": data.get("msg_cd", ""),
        "msg1": data.get("msg1", ""),
        "output_keys": _output_keys(output),
    }
    return {key: value for key, value in summary.items() if _has_summary_value(value)}


def _has_summary_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, list) and not value:
        return False
    return True


def _output_keys(output: Any) -> list[str]:
    if isinstance(output, dict):
        return sorted(str(key) for key in output.keys())
    if isinstance(output, list):
        keys: set[str] = set()
        for row in output[:5]:
            if isinstance(row, dict):
                keys.update(str(key) for key in row.keys())
        return sorted(keys)
    return []


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
    _invalidate_trade_row_cache(report_dir)


def _last_trade_key(report_dir: Path) -> str:
    rows = _load_trade_rows(report_dir)
    return rows[-1].get("trade_key", "") if rows else ""


def _trade_key_exists(report_dir: Path, trade_key: str) -> bool:
    if not trade_key:
        return False
    return any(row.get("trade_key", "") == trade_key for row in _load_trade_rows(report_dir))


def _open_positions_from_trades(report_dir: Path) -> tuple[list[dict[str, Any]], float]:
    rows = _load_trade_rows(report_dir)
    positions: dict[str, dict[str, Any]] = {}
    cash = 0.0
    for row in rows:
        action = str(row.get("action") or "").upper()
        symbol = str(row.get("symbol") or "").strip()
        shares = int(_float(row.get("shares")))
        price = _float(row.get("price"))
        cash_after = _float(row.get("cash_after"))
        if cash_after > 0:
            cash = cash_after
        if action == "BUY" and symbol and shares > 0 and price > 0:
            positions[symbol] = {
                "symbol": symbol,
                "shares": shares,
                "entry_price": price,
                "highest_price": price,
                "entry_time": str(row.get("timestamp") or ""),
            }
        elif action == "SELL_PARTIAL" and symbol:
            position = positions.get(symbol)
            if position:
                remaining = int(position.get("shares") or 0) - shares
                if remaining > 0:
                    position["shares"] = remaining
                    position["partial_taken"] = True
                    position["partial_stages"] = int(position.get("partial_stages") or 0) + 1
                else:
                    positions.pop(symbol, None)
        elif action.startswith("SELL") and symbol:
            positions.pop(symbol, None)
    return list(positions.values()), cash


def _open_position_from_trades(report_dir: Path) -> tuple[dict[str, Any] | None, float]:
    positions, cash = _open_positions_from_trades(report_dir)
    return (positions[0] if positions else None), cash


def _live_buy_count_for_session(report_dir: Path, session: object) -> int:
    count = 0
    for row in _load_trade_rows(report_dir):
        action = str(row.get("action") or "").upper()
        if action != "BUY":
            continue
        if _timestamp_date(row.get("timestamp")) == session:
            count += 1
    return count


def _live_consecutive_losses(report_dir: Path, session: object) -> tuple[int, datetime | None]:
    rows = _load_trade_rows(report_dir)
    sell_rows = [
        row
        for row in rows
        if str(row.get("action") or "").upper() == "SELL_ALL"
        and _timestamp_date(row.get("timestamp")) == session
    ]
    count = 0
    last_loss_at: datetime | None = None
    for row in reversed(sell_rows):
        if _float(row.get("realized_pnl")) >= 0:
            break
        count += 1
        if last_loss_at is None:
            last_loss_at = _timestamp_datetime(row.get("timestamp"))
    return count, last_loss_at


def _live_symbol_stop_loss_reentry_block_until(
    report_dir: Path,
    symbol: str,
    session: object,
    block_minutes: int,
) -> datetime | None:
    if block_minutes <= 0:
        return None
    target = str(symbol or "").strip().upper()
    if not target:
        return None
    for row in reversed(_load_trade_rows(report_dir)):
        if _timestamp_date(row.get("timestamp")) != session:
            continue
        if str(row.get("symbol") or "").strip().upper() != target:
            continue
        action = str(row.get("action") or "").upper()
        reason = str(row.get("reason") or "")
        if action.startswith("SELL") and reason == "live_stop_loss":
            exited_at = _timestamp_datetime(row.get("timestamp"))
            if not exited_at:
                return None
            return exited_at + timedelta(minutes=max(1, int(block_minutes)))
        if action.startswith("SELL") and reason == "live_trailing_stop":
            # trailing stop 후에는 절반 시간만 차단 (수익 실현 후 재진입 기회는 남긴다)
            exited_at = _timestamp_datetime(row.get("timestamp"))
            if not exited_at:
                return None
            trailing_block = max(1, int(block_minutes) // 2)
            return exited_at + timedelta(minutes=trailing_block)
        if action == "BUY":
            # 최근 이벤트가 BUY라면 직전 손절 블록을 이미 통과한 상태로 본다.
            return None
    return None


def _live_realized_today(report_dir: Path, session: object) -> float:
    rows = _load_trade_rows(report_dir)
    total = 0.0
    for row in rows:
        action = str(row.get("action") or "").upper()
        if not action.startswith("SELL"):
            continue
        if _timestamp_date(row.get("timestamp")) != session:
            continue
        total += _float(row.get("realized_pnl"))
    return total


_TRADE_ROW_CACHE: dict[Path, tuple[int, list[dict[str, Any]]]] = {}


def _load_trade_rows(report_dir: Path) -> list[dict[str, Any]]:
    path = report_dir / "trades.csv"
    if not path.exists():
        _TRADE_ROW_CACHE.pop(path, None)
        return []
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return []
    cached = _TRADE_ROW_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    with path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    _TRADE_ROW_CACHE[path] = (mtime, rows)
    return rows


def _invalidate_trade_row_cache(report_dir: Path) -> None:
    path = report_dir / "trades.csv"
    _TRADE_ROW_CACHE.pop(path, None)


def _daily_entry_limit_message(entry_count: int, max_trades_per_day: int) -> str:
    return f"일일 진입 한도 도달 ({entry_count}/{max_trades_per_day}회)"


def _tone_confirm_seconds(tone: str) -> int:
    if tone == "aggressive":
        return TONE_AGGRESSIVE_CONFIRM_SECONDS
    if tone == "conservative":
        return TONE_CONSERVATIVE_CONFIRM_SECONDS
    return TONE_NEUTRAL_CONFIRM_SECONDS


def _max_positions_message(position_count: int, max_positions: int) -> str:
    return f"최대 동시보유 도달 ({position_count}/{max_positions}종목)"


def _positions_summary(positions: list[dict[str, Any]]) -> str:
    if not positions:
        return "없음"
    return ", ".join(f"{position.get('symbol')} {position.get('shares')}주" for position in positions)


def _write_live_equity(rows: list[dict[str, Any]], report_dir: Path) -> None:
    if not rows:
        return
    with (report_dir / "equity_curve.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["datetime", "cash", "symbol", "shares", "mark_price", "equity", "drawdown", "paused"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_live_state_equity(row: dict[str, Any], report_dir: Path, fallback_initial: float) -> None:
    ensure_live_report(report_dir)
    rows = _load_live_equity_rows(report_dir)
    row_key = str(row.get("datetime") or "")
    replaced = False
    merged: list[dict[str, Any]] = []
    for existing in rows:
        if str(existing.get("datetime") or "") == row_key:
            merged.append(dict(row))
            replaced = True
        else:
            merged.append(existing)
    if not replaced:
        merged.append(dict(row))
    merged = [item for item in merged if str(item.get("datetime") or "")]
    merged.sort(key=lambda item: str(item.get("datetime") or ""))

    first_equity = _float(merged[0].get("equity")) if merged else fallback_initial
    peak = first_equity if first_equity > 0 else fallback_initial
    for item in merged:
        equity = _float(item.get("equity"))
        if equity <= 0:
            equity = _float(item.get("cash"))
            item["equity"] = round(equity, 2)
        peak = max(peak, equity)
        item["drawdown"] = round((equity / peak) - 1.0, 6) if peak > 0 else 0.0

    _write_live_equity(merged, report_dir)


def _write_live_metrics(metrics: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_live_equity_rows(report_dir: Path) -> list[dict[str, Any]]:
    path = report_dir / "equity_curve.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _live_metrics_from_report(report_dir: Path, *, strategy_name: str, fallback_initial: float) -> dict[str, Any]:
    equity_rows = _load_live_equity_rows(report_dir)
    trade_rows = _load_trade_rows(report_dir)
    first_equity = _float(equity_rows[0].get("equity")) if equity_rows else 0.0
    initial = first_equity if first_equity > 0 else fallback_initial
    final = _float(equity_rows[-1].get("equity")) if equity_rows else initial
    total_return = ((final / initial) - 1.0) if initial > 0 else 0.0
    max_drawdown = min((_float(row.get("drawdown")) for row in equity_rows), default=0.0)
    trades = [row for row in trade_rows if str(row.get("action") or "").strip()]
    sell_trades = [row for row in trades if str(row.get("action") or "").upper().startswith("SELL")]
    realized_pnl = sum(_float(row.get("realized_pnl")) for row in sell_trades)
    explicit_cost = sum(_float(row.get("cost")) for row in trades)
    wins = sum(1 for row in sell_trades if _float(row.get("realized_pnl")) > 0)
    exposure_count = sum(1 for row in equity_rows if int(_float(row.get("shares"))) > 0)
    symbols = {str(row.get("symbol") or "").strip() for row in trades if str(row.get("symbol") or "").strip()}
    sessions = {
        str(row.get("datetime") or row.get("date") or "")[:10]
        for row in equity_rows
        if str(row.get("datetime") or row.get("date") or "")
    }
    return {
        "strategy": strategy_name,
        "symbols": len(symbols),
        "sessions": len(sessions),
        "start_datetime": equity_rows[0].get("datetime", "") if equity_rows else "",
        "end_datetime": equity_rows[-1].get("datetime", "") if equity_rows else "",
        "initial_capital": round(initial, 2),
        "final_equity": round(final, 2),
        "total_return_pct": round(total_return * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe_approx": 0.0,
        "trades": len(trades),
        "sell_trades": len(sell_trades),
        "sell_win_rate_pct": round((wins / len(sell_trades)) * 100.0, 2) if sell_trades else 0.0,
        "realized_pnl": round(realized_pnl, 2),
        "explicit_trade_cost": round(explicit_cost, 2),
        "exposure_pct": round((exposure_count / len(equity_rows)) * 100.0, 2) if equity_rows else 0.0,
    }


def _idle_status(market: str = DEFAULT_MARKET) -> dict[str, Any]:
    market = _market(market)
    config = load_live_config(market)
    selector = _selector_label(market)
    return {
        "running": False,
        "market": market,
        "message": "대기 중",
        "mode": config.mode,
        "selector": selector,
        "selector_message": f"{selector} 대기",
        "active_symbols": [],
        "orders": 0,
        "seed_capital": config.seed_capital,
        "seed_source": config.seed_source,
        "auto_start": config.auto_start,
        "symbol": config.symbol,
        "max_positions": config.max_positions,
        "position": {},
        "positions": [],
        "exchange_code": config.exchange_code,
        "price_exchange_code": config.price_exchange_code,
        "currency": config.currency,
        "session": "",
        "session_label": "",
        "market_time": _current_market_time(market).isoformat(sep=" ", timespec="seconds"),
        "overseas_premarket_enabled": config.overseas_premarket_enabled,
        "bar_count": 0,
        "bar_minutes": config.bar_minutes,
        "bar_ready_symbols": 0,
        "bar_min_ready": 0,
        "bar_counts": {},
        "price_error_count": 0,
        "token_status": "대기",
        "token_expires_at": "",
        "trade_message": "자동매매 시작 전",
        "strategy_tone": "neutral",
        "strategy_profile_mode": "auto",
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
    market = _market(market)
    if market == OVERSEAS_MARKET:
        return "NASDAQ 자동선별"
    if market == NASDAQ_SURGE_MARKET:
        return "나스닥 급등주 자동선별"
    if market == DOMESTIC_SURGE_MARKET:
        return "국내 급등주 자동선별"
    if market == DOMESTIC_ETF_MARKET:
        return "국내ETF 자동선별"
    return "자동선별"


def _session_label(session: str, market: str = DEFAULT_MARKET) -> str:
    market = _market(market)
    if session == SESSION_PREMARKET:
        return "프리장"
    if session == SESSION_REGULAR:
        return "본장"
    if session == SESSION_CLOSED:
        return "해외장 대기" if _is_overseas_market(market) else "국내장 대기"
    return ""


def _market_wait_message(market: str, now: datetime, premarket_enabled: bool) -> str:
    market = _market(market)
    if not _is_overseas_market(market):
        if now.weekday() >= 5:
            return "국내장 휴장: 주말"
        if now.time() < clock_time(9, 0):
            return "국내장 대기: 09:00 정규장 시작"
        return "국내장 종료: 다음 정규장 대기"
    if now.weekday() >= 5:
        return "해외장 휴장: 주말"
    if premarket_enabled:
        if now.time() >= clock_time(16, 0):
            return "해외장 종료: 다음 프리장 대기"
        return "해외장 대기: 프리장 04:00 시작"
    return "프리장 비활성화: 09:30 본장 대기"


def _current_market_time(market: str) -> datetime:
    tz = NEW_YORK_TZ if _is_overseas_market(market) else SEOUL_TZ
    return datetime.now(tz).replace(tzinfo=None)


def _as_market_time(now: datetime, tz: ZoneInfo) -> datetime:
    if now.tzinfo is None:
        aware = now.replace(tzinfo=SEOUL_TZ)
    else:
        aware = now
    return aware.astimezone(tz).replace(tzinfo=None)


def _market(value: object) -> str:
    market = str(value or DEFAULT_MARKET).strip().lower()
    return market if market in SUPPORTED_MARKETS else DEFAULT_MARKET


def _is_overseas_market(market: str) -> bool:
    return _market(market) in {OVERSEAS_MARKET, NASDAQ_SURGE_MARKET}


def _is_surge_market(market: str) -> bool:
    return _market(market) in {DOMESTIC_SURGE_MARKET, NASDAQ_SURGE_MARKET}


def _market_label(market: str) -> str:
    market = _market(market)
    if market == OVERSEAS_MARKET:
        return "해외"
    if market == NASDAQ_SURGE_MARKET:
        return "나스닥 급등주"
    if market == DOMESTIC_SURGE_MARKET:
        return "국내 급등주"
    if market == DOMESTIC_ETF_MARKET:
        return "국내ETF"
    return "국내"


def _strategy_name(market: str) -> str:
    market = _market(market)
    if market == OVERSEAS_MARKET:
        return "live_overseas_stock_scanner"
    if market == NASDAQ_SURGE_MARKET:
        return "live_nasdaq_surge_scalp"
    if market == DOMESTIC_SURGE_MARKET:
        return "live_domestic_surge_scalp"
    if market == DOMESTIC_ETF_MARKET:
        return "live_domestic_etf_scalp"
    return "live_volatile_stock_scanner"


def _reason_summary(reasons: list[str]) -> str:
    buckets: dict[str, int] = {}
    for reason in reasons:
        label = _reason_bucket(reason)
        buckets[label] = buckets.get(label, 0) + 1
    if not buckets:
        return ""
    ordered = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    return ", ".join(f"{label} {count}" for label, count in ordered[:3])


def _reason_bucket(reason: str) -> str:
    if reason.startswith("진입 전 관찰"):
        return "관찰중"
    if reason.startswith("상승률"):
        return "상승률"
    if reason.startswith("거래량"):
        return "거래량"
    if reason.startswith("변동성") or reason.startswith("ATR"):
        return "변동성"
    if "VWAP" in reason:
        return "VWAP"
    if "고가" in reason:
        return "돌파"
    if "모멘텀" in reason:
        return "모멘텀"
    return reason.split(" ", 1)[0]


def live_config_path(market: str = DEFAULT_MARKET) -> Path:
    market = _market(market)
    if market == OVERSEAS_MARKET:
        return OVERSEAS_LIVE_CONFIG_PATH
    if market == NASDAQ_SURGE_MARKET:
        return NASDAQ_SURGE_LIVE_CONFIG_PATH
    if market == DOMESTIC_SURGE_MARKET:
        return DOMESTIC_SURGE_LIVE_CONFIG_PATH
    if market == DOMESTIC_ETF_MARKET:
        return DOMESTIC_ETF_LIVE_CONFIG_PATH
    return LIVE_CONFIG_PATH


def kis_keys_path(market: str = DEFAULT_MARKET) -> Path:
    market = _market(market)
    if market == OVERSEAS_MARKET:
        return OVERSEAS_KIS_KEYS_PATH
    if market == NASDAQ_SURGE_MARKET:
        return NASDAQ_SURGE_KIS_KEYS_PATH
    if market == DOMESTIC_SURGE_MARKET:
        return DOMESTIC_SURGE_KIS_KEYS_PATH
    if market == DOMESTIC_ETF_MARKET:
        return DOMESTIC_ETF_KIS_KEYS_PATH
    return KIS_KEYS_PATH


def live_report_dir(market: str = DEFAULT_MARKET) -> Path:
    market = _market(market)
    if market == OVERSEAS_MARKET:
        return OVERSEAS_LIVE_REPORT_DIR
    if market == NASDAQ_SURGE_MARKET:
        return NASDAQ_SURGE_LIVE_REPORT_DIR
    if market == DOMESTIC_SURGE_MARKET:
        return DOMESTIC_SURGE_LIVE_REPORT_DIR
    if market == DOMESTIC_ETF_MARKET:
        return DOMESTIC_ETF_LIVE_REPORT_DIR
    return LIVE_REPORT_DIR


def _excluded_name(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in ("ETF", "ETN", "스팩", "SPAC"))


def _excluded_domestic_warning_row(row: dict[str, Any]) -> bool:
    name = _row_name(row).upper()
    if any(token in name for token in ("관리종목", "투자경고", "투자위험")):
        return True
    warning_keys = (
        "warning",
        "is_warning",
        "trht_yn",
        "mket_warn_cls_code",
        "mrkt_warn_cls_code",
        "invst_warn_cls_code",
        "invst_risk_cls_code",
        "mngt_cls_code",
        "mngt_yn",
    )
    for key in warning_keys:
        raw = str(row.get(key, "")).strip().upper()
        if raw and raw not in {"0", "00", "N", "NORMAL", "NONE", "FALSE"}:
            return True
    return False


def _spread_reject_reason(spread_pct: Any, strategy: StockScannerConfig) -> str:
    if spread_pct in {None, ""}:
        return "spread_missing" if strategy.require_spread else ""
    spread = _float(spread_pct)
    if spread <= 0:
        return ""
    if spread > strategy.max_spread_pct:
        return f"spread {spread * 100:.2f}%>{strategy.max_spread_pct * 100:.2f}%"
    return ""


def _recent_vi_proxy_blocked(current_bars: list[StockBar], strategy: StockScannerConfig) -> bool:
    if strategy.vi_proxy_move_pct <= 0:
        return False
    lookback = max(1, strategy.vi_cooldown_bars)
    for bar in current_bars[-lookback:]:
        if bar.open > 0 and abs((bar.close / bar.open) - 1.0) >= strategy.vi_proxy_move_pct:
            return True
    return False


def _included_domestic_etf(row: dict[str, Any], symbol: str) -> bool:
    name = _row_name(row) or DOMESTIC_ETF_UNIVERSE.get(symbol, "")
    if _excluded_domestic_etf_name(name):
        return False
    upper = name.upper()
    if symbol in DOMESTIC_ETF_UNIVERSE:
        return True
    brands = ("KODEX", "TIGER", "ACE", "SOL", "HANARO", "KBSTAR", "PLUS", "ARIRANG", "KOSEF", "TIMEFOLIO", "RISE")
    return "ETF" in upper or any(brand in upper for brand in brands)


def _excluded_domestic_etf_name(name: str) -> bool:
    upper = name.upper()
    tokens = (
        "ETN",
        "스팩",
        "SPAC",
        "레버리지",
        "인버스",
        "곱버스",
        "선물인버스",
        "2X",
        "3X",
        "2배",
        "3배",
    )
    return any(token in upper for token in tokens)


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


def _prepend_symbols(symbols: list[str], preferred: list[str], limit: int) -> list[str]:
    selected: list[str] = []
    for symbol in preferred + symbols:
        if symbol not in selected:
            selected.append(symbol)
        if len(selected) >= limit:
            break
    return selected


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


def _strategy_snapshot(strategy: StockScannerConfig) -> dict[str, Any]:
    keys = (
        "observation_minutes",
        "gap_min_pct",
        "gap_max_pct",
        "volume_sma",
        "volume_factor",
        "min_atr_pct",
        "max_atr_pct",
        "max_extension_pct",
        "risk_per_trade_pct",
        "max_position_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "trailing_stop_pct",
        "time_stop_minutes",
        "force_exit_time",
    )
    return {key: getattr(strategy, key) for key in keys}


def _position_entry_date(position: dict[str, Any] | None) -> object | None:
    if not position:
        return None
    return _timestamp_date(position.get("entry_time"))


def _position_held_minutes(position: dict[str, Any] | None, now: datetime) -> int:
    if not position:
        return 0
    entered_at = _timestamp_datetime(position.get("entry_time"))
    if not entered_at:
        return 0
    return max(0, int((now - entered_at).total_seconds() // 60))


def _timestamp_date(value: Any) -> object | None:
    parsed = _timestamp_datetime(value)
    return parsed.date() if parsed else None


def _timestamp_datetime(value: Any) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    for candidate in (value, value.replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return value


def _live_order_shares(
    cash: float,
    price: float,
    strategy: StockScannerConfig,
    max_positions: int = 1,
    capital_base: float | None = None,
) -> int:
    if cash <= 0 or price <= 0:
        return 0
    max_positions = max(1, int(max_positions))
    capital_base = capital_base if capital_base and capital_base > 0 else cash
    slot_cap = capital_base / max_positions
    risk_budget = slot_cap * strategy.risk_per_trade_pct
    risk_cap = risk_budget / strategy.stop_loss_pct if strategy.stop_loss_pct > 0 else cash
    position_cap = capital_base * min(strategy.max_position_pct, 1.0 / max_positions)
    budget = min(cash, slot_cap, risk_cap, position_cap)
    cost_per_share = price * (1.0 + strategy.commission_rate + strategy.slippage_rate)
    return math.floor(budget / cost_per_share) if cost_per_share > 0 else 0


def _latest_symbol_bar(bars: list[StockBar], symbol: str, session: object) -> StockBar | None:
    symbol = str(symbol)
    matching = [bar for bar in bars if bar.symbol == symbol and bar.session == session]
    return max(matching, key=lambda bar: bar.timestamp) if matching else None


def _first_row_float(row: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        number = _float(row.get(key))
        if number:
            return number
    return 0.0


def _add_minutes_to_clock(value: clock_time, minutes: int) -> str:
    base = datetime.combine(datetime.now().date(), value)
    shifted = base + timedelta(minutes=minutes)
    return shifted.strftime("%H:%M")


def _float(value: object) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _is_rate_limit_error(message: object) -> bool:
    text = str(message or "").lower()
    return any(
        token in text
        for token in (
            "rate",
            "limit",
            "429",
            "too many",
            "egw00201",
            "초당 거래건수 초과",
        )
    )


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
