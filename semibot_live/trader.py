from __future__ import annotations

import csv
import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any

from semibot_backtester.stock_scanner import StockBar, StockScannerConfig, StockScannerBacktester

from .kis import KisClient, KisCredentials, parse_price_response


ROOT = Path(__file__).resolve().parents[1]
LIVE_CONFIG_PATH = ROOT / "config" / "live.local.json"
KIS_KEYS_PATH = ROOT / "config" / "kis.local.json"
LIVE_REPORT_DIR = ROOT / "reports" / "live_trading"
DEFAULT_WATCHLIST = [
    "000660",
    "005930",
    "042700",
    "058470",
    "000990",
    "039030",
    "240810",
    "403870",
    "095340",
    "357780",
]


@dataclass
class LiveConfig:
    mode: str = "paper"
    account_no: str = ""
    product_code: str = "01"
    watchlist: list[str] | None = None
    poll_interval_sec: int = 10
    bar_minutes: int = 5
    max_symbols: int = 20

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveConfig":
        watchlist_raw = data.get("watchlist", [])
        if isinstance(watchlist_raw, str):
            watchlist = [item.strip() for item in watchlist_raw.replace("\n", ",").split(",") if item.strip()]
        else:
            watchlist = [str(item).strip() for item in watchlist_raw if str(item).strip()]
        return cls(
            mode=data.get("mode", "paper"),
            account_no=data.get("account_no", ""),
            product_code=data.get("product_code", "01"),
            watchlist=watchlist,
            poll_interval_sec=int(data.get("poll_interval_sec", 10)),
            bar_minutes=int(data.get("bar_minutes", 5)),
            max_symbols=int(data.get("max_symbols", 20)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "account_no": self.account_no,
            "product_code": self.product_code,
            "watchlist": self.watchlist or [],
            "poll_interval_sec": self.poll_interval_sec,
            "bar_minutes": self.bar_minutes,
            "max_symbols": self.max_symbols,
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
        }
        self.bars: list[StockBar] = []
        self.seeded_previous_close: set[str] = set()
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
            return data

    def _loop(self) -> None:
        with self.lock:
            self.status.update({"running": True, "message": "실행 중"})
        try:
            client = KisClient(KisCredentials.from_file(KIS_KEYS_PATH))
            watchlist = (self.config.watchlist or [])[: self.config.max_symbols]
            while self.running:
                now = datetime.now()
                for symbol in watchlist:
                    price_data = client.inquire_price(symbol)
                    parsed = parse_price_response(price_data)
                    if parsed["price"] <= 0:
                        continue
                    self._add_tick(symbol, now, parsed)
                self._evaluate(client, now)
                with self.lock:
                    self.status.update({"last_tick": now.isoformat(sep=" ", timespec="seconds"), "message": "실행 중"})
                time.sleep(max(1, self.config.poll_interval_sec))
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.status.update({"last_error": str(exc), "message": "오류"})
        finally:
            with self.lock:
                self.status["running"] = False
            self.running = False

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
        return LiveConfig(watchlist=DEFAULT_WATCHLIST)
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
    return {"running": False, "message": "대기 중"}


def live_status() -> dict[str, Any]:
    if _TRADER:
        return _TRADER.snapshot()
    return {"running": False, "message": "대기 중"}


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
