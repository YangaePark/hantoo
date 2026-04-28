from __future__ import annotations

import csv
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any

from semibot_backtester.stock_scanner import StockBar, StockScannerConfig, StockScannerBacktester

from .kis import KisClient, KisCredentials, parse_price_response, parse_rank_rows, rank_row_symbol


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path(os.environ.get("SEMIBOT_STATE_ROOT", ROOT)).resolve()
LIVE_CONFIG_PATH = STATE_ROOT / "config" / "live.local.json"
KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.local.json"
LIVE_REPORT_DIR = STATE_ROOT / "reports" / "live_trading"


@dataclass
class LiveConfig:
    mode: str = "paper"
    account_no: str = ""
    product_code: str = "01"
    seed_capital: float = 1_000_000.0
    seed_source: str = "manual"
    auto_select: bool = True
    poll_interval_sec: int = 10
    bar_minutes: int = 5
    max_symbols: int = 20
    selection_refresh_sec: int = 60
    candidate_pool_size: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveConfig":
        return cls(
            mode=data.get("mode", "paper"),
            account_no=data.get("account_no", ""),
            product_code=data.get("product_code", "01"),
            seed_capital=_positive_float(data.get("seed_capital"), 1_000_000.0),
            seed_source=_seed_source(data.get("seed_source", "manual")),
            auto_select=True,
            poll_interval_sec=int(data.get("poll_interval_sec", 10)),
            bar_minutes=int(data.get("bar_minutes", 5)),
            max_symbols=int(data.get("max_symbols", 20)),
            selection_refresh_sec=int(data.get("selection_refresh_sec", 60)),
            candidate_pool_size=int(data.get("candidate_pool_size", 60)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "account_no": self.account_no,
            "product_code": self.product_code,
            "seed_capital": self.seed_capital,
            "seed_source": self.seed_source,
            "auto_select": self.auto_select,
            "poll_interval_sec": self.poll_interval_sec,
            "bar_minutes": self.bar_minutes,
            "max_symbols": self.max_symbols,
            "selection_refresh_sec": self.selection_refresh_sec,
            "candidate_pool_size": self.candidate_pool_size,
        }


class LiveTrader:
    def __init__(self, config: LiveConfig, strategy: StockScannerConfig):
        self.config = config
        self.strategy = strategy
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.status: dict[str, Any] = {
            "running": False,
            "mode": config.mode,
            "message": "대기 중",
            "last_tick": "",
            "last_error": "",
            "orders": 0,
            "active_symbols": [],
            "selector": "자동선별",
            "selector_message": "",
            "seed_capital": strategy.initial_capital,
            "seed_source": config.seed_source,
        }
        self.bars: list[StockBar] = []
        self.seeded_previous_close: set[str] = set()
        self.active_symbols: list[str] = []
        self.last_selection_at = 0.0
        self.position: dict[str, Any] | None = None
        self.cash = strategy.initial_capital
        self.day_start_cash = strategy.initial_capital
        ensure_live_report()

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
            data["active_symbols"] = list(self.active_symbols)
            return data

    def _loop(self) -> None:
        with self.lock:
            self.status.update({"running": True, "message": "실행 중"})
        try:
            client = KisClient(KisCredentials.from_file(KIS_KEYS_PATH), credentials_path=KIS_KEYS_PATH)
            self.active_symbols = self._initial_symbols(client)
            while self.running:
                now = datetime.now()
                if self.config.auto_select and time.time() - self.last_selection_at >= self.config.selection_refresh_sec:
                    self.active_symbols = self._select_symbols(client)
                for symbol in self.active_symbols:
                    price_data = client.inquire_price(symbol)
                    parsed = parse_price_response(price_data)
                    if parsed["price"] <= 0:
                        continue
                    self._add_tick(symbol, now, parsed)
                self._evaluate(client, now)
                with self.lock:
                    self.status.update(
                        {
                            "last_tick": now.isoformat(sep=" ", timespec="seconds"),
                            "message": "실행 중",
                            "active_symbols": list(self.active_symbols),
                        }
                    )
                time.sleep(max(1, self.config.poll_interval_sec))
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.status.update({"last_error": str(exc), "message": "오류"})
        finally:
            with self.lock:
                self.status["running"] = False
            self.running = False

    def _initial_symbols(self, client: KisClient) -> list[str]:
        return self._select_symbols(client)

    def _select_symbols(self, client: KisClient) -> list[str]:
        self.last_selection_at = time.time()
        candidates = self._candidate_symbols(client)
        ranked: list[tuple[float, str]] = []
        candidate_items = sorted(candidates.items(), key=lambda item: _source_priority(item[1]), reverse=True)
        for symbol, row in candidate_items[: self.config.candidate_pool_size]:
            price_data = client.inquire_price(symbol)
            parsed = parse_price_response(price_data)
            if not self._passes_live_candidate(parsed, row):
                continue
            score = self._live_candidate_score(parsed, row)
            ranked.append((score, symbol))
            time.sleep(0.04)
        ranked.sort(reverse=True)
        selected = [symbol for _, symbol in ranked[: self.config.max_symbols]]
        with self.lock:
            self.status["selector_message"] = f"자동선별 {len(selected)}종목 / 후보 {len(candidates)}종목"
            self.status["active_symbols"] = selected
        return selected

    def _candidate_symbols(self, client: KisClient) -> dict[str, dict[str, Any]]:
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

    def _passes_live_candidate(self, parsed: dict[str, float], row: dict[str, Any]) -> bool:
        price = parsed["price"]
        if price <= 0:
            return False
        gap = parsed["prev_rate_pct"] / 100.0
        if not (self.strategy.gap_min_pct <= gap <= self.strategy.gap_max_pct):
            return False
        day_range = ((parsed["high"] - parsed["low"]) / price) if price else 0.0
        if day_range < self.strategy.min_atr_pct:
            return False
        avg_volume = _float(row.get("avrg_vol"))
        volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else _float(row.get("vol_inrt")) / 100.0
        sources = set(row.get("_sources", []))
        if volume_surge < self.strategy.volume_factor and "volume_surge" not in sources:
            return False
        trade_value = parsed["value"] or _float(row.get("acml_tr_pbmn"))
        return trade_value >= 1_000_000_000

    def _live_candidate_score(self, parsed: dict[str, float], row: dict[str, Any]) -> float:
        price = parsed["price"] or 1.0
        day_range = max(0.0, (parsed["high"] - parsed["low"]) / price)
        gap = max(0.0, parsed["prev_rate_pct"] / 100.0)
        trade_value = max(parsed["value"], _float(row.get("acml_tr_pbmn")), 1.0)
        avg_volume = _float(row.get("avrg_vol"))
        volume_surge = (parsed["volume"] / avg_volume) if avg_volume > 0 else max(0.0, _float(row.get("vol_inrt")) / 100.0)
        strength = max(0.0, _float(row.get("tday_rltv")) / 100.0)
        return (math.log10(trade_value) * 1.5) + (gap * 100.0) + (day_range * 120.0) + min(volume_surge, 8.0) + strength

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
        if len(self.bars) < 50:
            return
        result = StockScannerBacktester(self.strategy).run(self.bars)
        latest_trade = result.trades[-1] if result.trades else None
        if not latest_trade:
            _write_live_metrics(result.metrics)
            return
        last_recorded = _last_trade_key()
        trade_key = f"{latest_trade.timestamp}|{latest_trade.action}|{latest_trade.symbol}|{latest_trade.shares}|{latest_trade.reason}"
        if trade_key == last_recorded:
            return
        live = self.config.mode == "live"
        if latest_trade.action == "BUY":
            response = self._place_order(client, "buy", latest_trade.symbol, latest_trade.shares, live)
            self.position = {"symbol": latest_trade.symbol, "shares": latest_trade.shares, "entry_price": latest_trade.price}
        else:
            response = self._place_order(client, "sell", latest_trade.symbol, latest_trade.shares, live)
            self.position = None
        self.cash = float(latest_trade.cash_after)
        _append_live_trade(latest_trade, response, self.config.mode, trade_key)
        _write_live_equity(result.equity_curve)
        _write_live_metrics(result.metrics)
        with self.lock:
            self.status["orders"] = int(self.status.get("orders", 0)) + 1

    def _place_order(self, client: KisClient, side: str, symbol: str, quantity: int, live: bool) -> dict[str, Any]:
        if self.config.mode == "paper":
            return {"rt_cd": "0", "msg1": "paper order recorded"}
        if not self.config.account_no:
            return {"rt_cd": "-1", "msg1": "account_no is required"}
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


_TRADER: LiveTrader | None = None


def load_live_config() -> LiveConfig:
    if not LIVE_CONFIG_PATH.exists():
        return LiveConfig(auto_select=True)
    return LiveConfig.from_dict(json.loads(LIVE_CONFIG_PATH.read_text(encoding="utf-8")))


def save_live_config(config: LiveConfig) -> None:
    LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_CONFIG_PATH.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def start_live_trader(strategy: StockScannerConfig) -> dict[str, Any]:
    global _TRADER
    config = load_live_config()
    if config.mode == "live" and (not config.account_no or not config.product_code):
        return {"running": False, "message": "LIVE 모드는 계좌번호와 상품코드가 필요합니다."}
    if not KIS_KEYS_PATH.exists():
        return {"running": False, "message": "KIS 키가 저장되어 있지 않습니다."}
    _TRADER = LiveTrader(config, strategy)
    _TRADER.start()
    return _TRADER.snapshot()


def stop_live_trader() -> dict[str, Any]:
    if _TRADER:
        _TRADER.stop()
        return _TRADER.snapshot()
    return _idle_status()


def live_status() -> dict[str, Any]:
    if _TRADER:
        return _TRADER.snapshot()
    return _idle_status()


def ensure_live_report() -> None:
    LIVE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades_path = LIVE_REPORT_DIR / "trades.csv"
    if not trades_path.exists():
        with trades_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["timestamp", "action", "symbol", "shares", "price", "gross", "cost", "realized_pnl", "cash_after", "reason", "mode", "order_response", "trade_key"])
    metrics_path = LIVE_REPORT_DIR / "metrics.json"
    if not metrics_path.exists():
        metrics_path.write_text(
            json.dumps(
                {
                    "strategy": "live_volatile_stock_scanner",
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


def _append_live_trade(trade, response: dict[str, Any], mode: str, trade_key: str) -> None:
    ensure_live_report()
    with (LIVE_REPORT_DIR / "trades.csv").open("a", newline="", encoding="utf-8") as csv_file:
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


def _last_trade_key() -> str:
    path = LIVE_REPORT_DIR / "trades.csv"
    if not path.exists():
        return ""
    with path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    return rows[-1].get("trade_key", "") if rows else ""


def _write_live_equity(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with (LIVE_REPORT_DIR / "equity_curve.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["datetime", "cash", "symbol", "shares", "mark_price", "equity", "drawdown", "paused"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_live_metrics(metrics: dict[str, Any]) -> None:
    (LIVE_REPORT_DIR / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def _idle_status() -> dict[str, Any]:
    config = load_live_config()
    return {
        "running": False,
        "message": "대기 중",
        "mode": config.mode,
        "selector": "자동선별",
        "selector_message": "시장 자동선별 대기",
        "active_symbols": [],
        "orders": 0,
        "seed_capital": config.seed_capital,
        "seed_source": config.seed_source,
    }


def _valid_stock_symbol(symbol: str) -> bool:
    return len(symbol) == 6 and symbol.isdigit()


def _excluded_name(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in ("ETF", "ETN", "스팩", "SPAC"))


def _source_priority(row: dict[str, Any]) -> int:
    weights = {"trade_value": 4, "volume_surge": 4, "gap_up": 3, "strength": 2}
    return sum(weights.get(source, 0) for source in set(row.get("_sources", [])))


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
