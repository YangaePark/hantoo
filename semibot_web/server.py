from __future__ import annotations

import csv
import json
import mimetypes
import os
from collections import deque
from dataclasses import replace
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from semibot_backtester.stock_scanner import StockScannerConfig
from semibot_live.kis import (
    KisClient,
    KisCredentials,
    parse_balance_response,
    parse_overseas_balance_response,
    parse_overseas_margin_response,
    parse_overseas_psamount_response,
)
from semibot_live.trader import (
    DEFAULT_MARKET,
    OVERSEAS_MARKET,
    SUPPORTED_MARKETS,
    ensure_live_report,
    kis_keys_path,
    LiveConfig,
    live_report_dir,
    live_status,
    load_live_config,
    save_live_config,
    start_live_trader,
    stop_live_trader,
)


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path(os.environ.get("SEMIBOT_STATE_ROOT", ROOT)).resolve()
WEB_ROOT = ROOT / "semibot_web" / "static"
REPORTS_ROOT = STATE_ROOT / "reports"
NEW_YORK_TZ = ZoneInfo("America/New_York")
SEOUL_TZ = ZoneInfo("Asia/Seoul")
SCANNER_CONFIG_PATH = ROOT / "config" / "volatile_stock_scalp.json"
OVERSEAS_SCANNER_CONFIG_PATH = ROOT / "config" / "overseas_stock_scalp.json"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SemibotDashboard/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(WEB_ROOT / "index.html")
        elif parsed.path.startswith("/static/"):
            self._serve_file(WEB_ROOT / parsed.path.removeprefix("/static/"))
        elif parsed.path == "/api/health":
            self._json({"ok": True})
        elif parsed.path == "/api/reports":
            self._json({"reports": list_reports()})
        elif parsed.path == "/api/report":
            name = parse_qs(parsed.query).get("name", [""])[0]
            self._json(load_report(name))
        elif parsed.path == "/api/kis/keys":
            self._json(load_kis_key_status(_market_from_query(parsed)))
        elif parsed.path == "/api/kis/balance":
            self._json(load_kis_balance(_market_from_query(parsed)))
        elif parsed.path == "/api/live/config":
            self._json(load_live_config(_market_from_query(parsed)).to_dict())
        elif parsed.path == "/api/live/status":
            self._json(load_live_status(_market_from_query(parsed)))
        elif parsed.path == "/api/live/decisions":
            self._json(load_live_decisions(_market_from_query(parsed), _limit_from_query(parsed)))
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/kis/keys":
            payload = self._read_json()
            market = _market_from_payload(payload, parsed)
            app_key = str(payload.get("app_key", "")).strip()
            app_secret = str(payload.get("app_secret", "")).strip()
            access_token = str(payload.get("access_token", "")).strip()
            access_token_expires_at = str(payload.get("access_token_expires_at", "")).strip()
            base_url = str(payload.get("base_url", "https://openapi.koreainvestment.com:9443")).strip()
            if not app_key or not app_secret:
                self._json({"error": "app_key and app_secret are required"}, HTTPStatus.BAD_REQUEST)
                return
            keys_path = kis_keys_path(market)
            keys_path.parent.mkdir(parents=True, exist_ok=True)
            keys_path.write_text(
                json.dumps(
                    {
                        "app_key": app_key,
                        "app_secret": app_secret,
                        "access_token": access_token,
                        "access_token_expires_at": access_token_expires_at,
                        "base_url": base_url,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._json(load_kis_key_status(market))
        elif parsed.path == "/api/live/config":
            payload = self._read_json()
            market = _market_from_payload(payload, parsed)
            payload["market"] = market
            config = LiveConfig.from_dict(payload)
            if config.mode not in {"paper", "live"}:
                self._json({"error": "mode must be paper or live"}, HTTPStatus.BAD_REQUEST)
                return
            save_live_config(config, market)
            self._json(config.to_dict())
        elif parsed.path == "/api/live/start":
            payload = self._read_json()
            market = _market_from_payload(payload, parsed)
            config = load_live_config(market)
            seed_capital, seed_error = resolve_seed_capital(config)
            if seed_capital <= 0:
                self._json({"running": False, "message": seed_error or "잔고 최대 시드로 사용할 현금이 없습니다."})
                return
            strategy = load_live_strategy_config(market, seed_capital)
            self._json(start_live_trader(strategy, market))
        elif parsed.path == "/api/live/stop":
            payload = self._read_json()
            market = _market_from_payload(payload, parsed)
            self._json(stop_live_trader(market))
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if WEB_ROOT.resolve() not in resolved.parents and resolved != WEB_ROOT.resolve():
                raise FileNotFoundError
            body = resolved.read_bytes()
        except FileNotFoundError:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def list_reports() -> list[dict]:
    reports: list[dict] = []
    if not REPORTS_ROOT.exists():
        return reports
    for path in sorted(REPORTS_ROOT.iterdir()):
        if not path.is_dir():
            continue
        if path.name.startswith("live_trading") and not _is_live_report_name(path.name):
            continue
        metrics_path = path / "metrics.json"
        if not metrics_path.exists():
            continue
        metrics = _read_json_file(metrics_path)
        trades = _read_csv_file(path / "trades.csv")
        equity = _read_csv_file(path / "equity_curve.csv")
        if _is_live_report_name(path.name):
            metrics = _normalized_report_metrics(metrics, trades, equity)
        reports.append(
            {
                "name": path.name,
                "label": _report_label(path.name, metrics),
                "strategy": metrics.get("strategy") or metrics.get("symbol") or "backtest",
                "total_return_pct": metrics.get("total_return_pct", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "trades": metrics.get("trades", 0),
                "final_equity": metrics.get("final_equity", 0),
            }
        )
    return reports


def load_report(name: str) -> dict:
    if not _safe_name(name):
        return {"error": "invalid report name"}
    if name.startswith("live_trading") and not _is_live_report_name(name):
        return {"error": "report not found"}
    report_dir = REPORTS_ROOT / name
    if not report_dir.exists():
        return {"error": "report not found"}

    metrics = _read_json_file(report_dir / "metrics.json")
    trades = _read_csv_file(report_dir / "trades.csv")
    equity = _read_csv_file(report_dir / "equity_curve.csv")
    if _is_live_report_name(name):
        metrics = _normalized_report_metrics(metrics, trades, equity)
    tone_summary = _build_tone_summary(report_dir, trades)
    market = _market_from_report_name(name)
    daily_pnl = _daily_pnl_series(equity, trades)
    daily_summary = _daily_summary(market, trades, daily_pnl)
    return {
        "name": name,
        "label": _report_label(name, metrics),
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity,
        "current": current_snapshot(metrics, trades, equity),
        "tone_summary": tone_summary,
        "daily_summary": daily_summary,
        "daily_pnl": daily_pnl,
    }


def load_live_status(market: str = DEFAULT_MARKET) -> dict:
    market = _market(market)
    status = dict(live_status(market))
    report_dir = live_report_dir(market)
    trades = _read_csv_file(report_dir / "trades.csv")
    equity = _read_csv_file(report_dir / "equity_curve.csv")
    daily_pnl = _daily_pnl_series(equity, trades)
    status["daily_summary"] = _daily_summary(market, trades, daily_pnl)
    return status


def _build_tone_summary(report_dir: Path, trades: list[dict]) -> dict:
    decision_path = report_dir / "decision_log.jsonl"
    if not decision_path.exists():
        return {
            "latest_tone": "normal",
            "tone_switches": 0,
            "tone_counts": {},
            "stop_loss_reentry_blocks": 0,
            "estimated_avoided_loss": 0.0,
            "profile_mode": "auto",
        }

    decisions: list[dict] = []
    with decision_path.open(encoding="utf-8") as log_file:
        for line in log_file:
            line = line.strip()
            if not line:
                continue
            try:
                decisions.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    tone_counts: dict[str, int] = {}
    latest_tone = "normal"
    previous_tone = ""
    switches = 0
    profile_mode = "auto"
    for row in decisions:
        tone = _normalize_tone(row.get("strategy_tone"))
        if not tone:
            continue
        tone_counts[tone] = tone_counts.get(tone, 0) + 1
        latest_tone = tone
        if previous_tone and tone != previous_tone:
            switches += 1
        previous_tone = tone

    reentry_blocks = sum(
        1
        for row in decisions
        if str(row.get("event") or "") == "entry_skip"
        and str(row.get("reason") or "") == "stop_loss_reentry_cooldown"
    )

    stop_losses = [
        abs(_to_number(trade.get("realized_pnl", 0)))
        for trade in trades
        if str(trade.get("action") or "").startswith("SELL")
        and str(trade.get("reason") or "") == "live_stop_loss"
        and _to_number(trade.get("realized_pnl", 0)) < 0
    ]
    avg_stop_loss = (sum(stop_losses) / len(stop_losses)) if stop_losses else 0.0
    estimated_avoided_loss = round(reentry_blocks * avg_stop_loss, 2)

    return {
        "latest_tone": latest_tone,
        "tone_switches": switches,
        "tone_counts": tone_counts,
        "stop_loss_reentry_blocks": reentry_blocks,
        "estimated_avoided_loss": estimated_avoided_loss,
        "profile_mode": profile_mode,
    }


def _normalize_tone(value: object) -> str:
    tone = str(value or "").strip().lower()
    if not tone:
        return ""
    if tone in {"entry_block", "conservative"}:
        return "entry_block"
    return "normal"


def load_live_decisions(market: str = DEFAULT_MARKET, limit: int = 80) -> dict:
    market = _market(market)
    report_dir = live_report_dir(market)
    path = report_dir / "decision_log.jsonl"
    rows: deque[dict] = deque(maxlen=max(1, min(200, limit)))
    if path.exists():
        with path.open(encoding="utf-8") as log_file:
            for line in log_file:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"event": "parse_error", "message": line[:200]})
    return {
        "market": market,
        "report": report_dir.name,
        "decisions": list(rows),
    }


def current_snapshot(metrics: dict, trades: list[dict], equity: list[dict]) -> dict:
    last_equity = equity[-1] if equity else {}
    open_symbol = last_equity.get("symbol") or metrics.get("symbol") or ""
    open_shares = _to_number(last_equity.get("shares", 0))
    last_trade = trades[-1] if trades else {}
    cash = _to_number(last_equity.get("cash", 0))
    if not equity and not open_shares:
        cash = _to_number(metrics.get("final_equity", 0))
    return {
        "time": last_equity.get("datetime") or last_equity.get("date") or metrics.get("end_datetime") or metrics.get("end_date"),
        "equity": _to_number(last_equity.get("equity", metrics.get("final_equity", 0))),
        "cash": cash,
        "open_symbol": open_symbol if open_shares else "",
        "open_shares": open_shares,
        "last_trade": last_trade,
    }


def _is_live_report_name(name: str) -> bool:
    return str(name or "") in {"live_trading", "live_trading_overseas"}


def _normalized_report_metrics(metrics: dict, trades: list[dict], equity: list[dict]) -> dict:
    if not equity:
        return metrics
    normalized = dict(metrics)
    first_equity = _to_number(equity[0].get("equity", 0))
    initial = first_equity if first_equity > 0 else _to_number(metrics.get("initial_capital", 0))
    final = _to_number(equity[-1].get("equity", metrics.get("final_equity", 0)))
    if initial > 0 and final > 0:
        normalized["initial_capital"] = round(initial, 2)
        normalized["final_equity"] = round(final, 2)
        normalized["total_return_pct"] = round(((final / initial) - 1.0) * 100.0, 2)
    drawdowns = [_to_number(row.get("drawdown", 0)) for row in equity]
    if drawdowns:
        normalized["max_drawdown_pct"] = round(min(drawdowns) * 100.0, 2)
    trade_rows = [row for row in trades if str(row.get("action") or "").strip()]
    sell_rows = [row for row in trade_rows if str(row.get("action") or "").upper().startswith("SELL")]
    if trade_rows:
        wins = sum(1 for row in sell_rows if _to_number(row.get("realized_pnl", 0)) > 0)
        normalized["trades"] = len(trade_rows)
        normalized["sell_trades"] = len(sell_rows)
        normalized["sell_win_rate_pct"] = round((wins / len(sell_rows)) * 100.0, 2) if sell_rows else 0.0
        normalized["realized_pnl"] = round(sum(_to_number(row.get("realized_pnl", 0)) for row in sell_rows), 2)
        normalized["explicit_trade_cost"] = round(sum(_to_number(row.get("cost", 0)) for row in trade_rows), 2)
    return normalized


def _market_from_report_name(name: str) -> str | None:
    report_markets = {
        "live_trading": DEFAULT_MARKET,
        "live_trading_overseas": OVERSEAS_MARKET,
    }
    return report_markets.get(str(name or ""))


def _daily_summary(
    market: str | None,
    trades: list[dict],
    daily_pnl: list[dict],
    *,
    today: date | None = None,
) -> dict:
    today_key = (today or _today_for_market(market)).isoformat()
    entry_limit = _daily_entry_limit(market)
    entries_used = _entry_count_for_date(trades, today_key)
    day_row = next((row for row in daily_pnl if row.get("date") == today_key), {})
    return {
        "date": today_key,
        "entry_limit": entry_limit,
        "entries_used": entries_used,
        "entry_remaining": max(0, entry_limit - entries_used) if entry_limit > 0 else 0,
        "pnl_amount": round(_to_number(day_row.get("pnl_amount", 0)), 2),
        "return_pct": round(_to_number(day_row.get("return_pct", 0)), 2),
        "realized_pnl": round(_to_number(day_row.get("realized_pnl", 0)), 2),
    }


def _daily_entry_limit(market: str | None) -> int:
    if not market:
        return 0
    try:
        return int(load_live_strategy_config(market).max_trades_per_day)
    except Exception:  # noqa: BLE001
        return 0


def _today_for_market(market: str | None) -> date:
    if market and _is_overseas_market_name(market):
        return datetime.now(NEW_YORK_TZ).date()
    return datetime.now(SEOUL_TZ).date()


def _is_overseas_market_name(market: str) -> bool:
    return _market(market) == OVERSEAS_MARKET


def _daily_pnl_series(equity: list[dict], trades: list[dict]) -> list[dict]:
    equity_by_date: dict[str, list[float]] = {}
    for row in equity:
        key = _date_key(row.get("datetime") or row.get("date"))
        value = _to_number(row.get("equity", row.get("cash", 0)))
        if key and value > 0:
            equity_by_date.setdefault(key, []).append(value)

    trade_stats = _trade_stats_by_date(trades)
    dates = sorted(set(equity_by_date) | set(trade_stats))
    rows: list[dict] = []
    previous_close = 0.0
    for key in dates:
        values = equity_by_date.get(key, [])
        stats = trade_stats.get(key, {})
        if values:
            start = previous_close if previous_close > 0 else values[0]
            end = values[-1]
            pnl_amount = end - start
            # Older live reports may have stale flat equity rows; use realized PnL when it is the only movement signal.
            if abs(pnl_amount) < 0.005 and abs(_to_number(stats.get("realized_pnl"))) > 0:
                pnl_amount = _to_number(stats.get("realized_pnl"))
            previous_close = end
        else:
            start = previous_close
            end = previous_close
            pnl_amount = _to_number(stats.get("realized_pnl"))
        base = start if start > 0 else 0.0
        rows.append(
            {
                "date": key,
                "start_equity": round(start, 2),
                "end_equity": round(end, 2),
                "pnl_amount": round(pnl_amount, 2),
                "return_pct": round((pnl_amount / base) * 100.0, 2) if base > 0 else 0.0,
                "entries": int(stats.get("entries", 0) or 0),
                "trades": int(stats.get("trades", 0) or 0),
                "realized_pnl": round(_to_number(stats.get("realized_pnl")), 2),
            }
        )
    return rows


def _trade_stats_by_date(trades: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for trade in trades:
        key = _date_key(trade.get("timestamp") or trade.get("date"))
        if not key:
            continue
        item = stats.setdefault(key, {"entries": 0, "trades": 0, "realized_pnl": 0.0})
        action = str(trade.get("action") or "").upper()
        if action:
            item["trades"] += 1
        if action == "BUY":
            item["entries"] += 1
        if action.startswith("SELL"):
            item["realized_pnl"] += _to_number(trade.get("realized_pnl"))
    return stats


def _entry_count_for_date(trades: list[dict], date_key: str) -> int:
    return sum(
        1
        for trade in trades
        if str(trade.get("action") or "").upper() == "BUY"
        and _date_key(trade.get("timestamp") or trade.get("date")) == date_key
    )


def _date_key(value: object) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def load_kis_key_status(market: str = DEFAULT_MARKET) -> dict:
    market = _market(market)
    keys_path = kis_keys_path(market)
    if not keys_path.exists():
        return {
            "market": market,
            "configured": False,
            "token_configured": False,
            "app_key_masked": "",
            "base_url": "https://openapi.koreainvestment.com:9443",
        }
    data = _read_json_file(keys_path)
    return {
        "market": market,
        "configured": bool(data.get("app_key") and data.get("app_secret")),
        "token_configured": bool(data.get("access_token")),
        "token_expires_at": data.get("access_token_expires_at", ""),
        "app_key_masked": _mask(str(data.get("app_key", ""))),
        "base_url": data.get("base_url", "https://openapi.koreainvestment.com:9443"),
    }


def load_kis_balance(market: str = DEFAULT_MARKET) -> dict:
    market = _market(market)
    keys_path = kis_keys_path(market)
    if not keys_path.exists():
        return {"ok": False, "message": "KIS 키가 저장되어 있지 않습니다."}
    config = load_live_config(market)
    if not config.account_no:
        return {"ok": False, "message": "계좌번호를 저장한 뒤 조회하세요."}
    client = KisClient(KisCredentials.from_file(keys_path), credentials_path=keys_path)
    try:
        if market == OVERSEAS_MARKET:
            response = client.inquire_overseas_balance(
                config.account_no,
                config.product_code,
                exchange_code=config.exchange_code,
                currency=config.currency,
                live=True,
            )
            parsed = parse_overseas_balance_response(response)
            if _overseas_balance_needs_margin_fallback(parsed):
                parsed = _load_overseas_cash_fallback(client, config, parsed)
        else:
            response = client.inquire_balance(config.account_no, config.product_code, live=True)
            parsed = parse_balance_response(response)
    except Exception as exc:
        parsed = {
            "rt_cd": "-1",
            "msg_cd": exc.__class__.__name__,
            "message": str(exc),
            "cash": 0,
            "withdrawable_cash": 0,
            "total_evaluation": 0,
            "stock_evaluation": 0,
            "profit_loss": 0,
            "profit_loss_rate": 0,
            "holdings": [],
        }
    ok = parsed["rt_cd"] in {"0", ""}
    if market == OVERSEAS_MARKET and ok and balance_max_seed(parsed) <= 0:
        parsed["rt_cd"] = "-1"
        parsed["msg_cd"] = "OVERSEAS_BALANCE_ZERO"
        parsed["message"] = _overseas_zero_balance_message(parsed)
        ok = False
    parsed.pop("raw", None)
    max_seed_capital = balance_max_seed(parsed)
    return {
        **parsed,
        "market": market,
        "ok": ok,
        "max_seed_capital": max_seed_capital,
        "account_no_masked": _mask_account(config.account_no),
        "product_code": config.product_code,
        "exchange_code": config.exchange_code,
        "currency": config.currency,
        "fetched_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
    }


def resolve_seed_capital(config: LiveConfig) -> tuple[float, str]:
    if config.seed_source != "balance_max":
        return config.seed_capital, ""
    balance = load_kis_balance(config.market)
    if not balance.get("ok"):
        return 0.0, str(balance.get("message") or "잔고 조회에 실패했습니다.")
    seed = balance_max_seed(balance)
    if seed <= 0:
        return 0.0, "잔고 최대 시드로 사용할 현금이 없습니다."
    return seed, ""


def balance_max_seed(balance: dict) -> float:
    cash = _to_number(balance.get("cash", 0))
    withdrawable_cash = _to_number(balance.get("withdrawable_cash", 0))
    return float(max(cash, withdrawable_cash))


def _overseas_balance_needs_margin_fallback(parsed: dict) -> bool:
    if str(parsed.get("rt_cd", "")) not in {"0", ""}:
        return False
    return balance_max_seed(parsed) <= 0


def _merge_overseas_margin(balance: dict, margin: dict) -> dict:
    merged = dict(balance)
    merged["margin_msg_cd"] = margin.get("msg_cd", "")
    merged["margin_message"] = margin.get("message", "")
    if str(margin.get("rt_cd", "")) not in {"0", ""}:
        if balance_max_seed(merged) <= 0:
            merged["rt_cd"] = str(margin.get("rt_cd") or "-1")
            merged["msg_cd"] = margin.get("msg_cd") or "OVERSEAS_MARGIN_FAILED"
            merged["message"] = f"해외 예수금 조회 실패: {margin.get('message') or '응답 금액을 확인하지 못했습니다.'}"
        return merged
    for key in ("cash", "withdrawable_cash", "total_evaluation"):
        if _to_number(merged.get(key, 0)) == 0 and _to_number(margin.get(key, 0)) != 0:
            merged[key] = margin[key]
    merged["margin_checked"] = True
    return merged


def _load_overseas_cash_fallback(client: KisClient, config: LiveConfig, parsed: dict) -> dict:
    merged = parsed
    for night in (False, True):
        psamount_response = client.inquire_overseas_psamount(
            config.account_no,
            config.product_code,
            exchange_code=config.exchange_code,
            live=True,
            night=night,
        )
        psamount = parse_overseas_psamount_response(psamount_response)
        merged = _merge_overseas_psamount(merged, psamount, "night" if night else "regular")
        if balance_max_seed(merged) > 0:
            return merged

    margin_response = client.inquire_overseas_margin(config.account_no, config.product_code, live=True)
    return _merge_overseas_margin(merged, parse_overseas_margin_response(margin_response, config.currency))


def _merge_overseas_psamount(balance: dict, psamount: dict, ledger: str) -> dict:
    merged = dict(balance)
    merged["psamount_checked"] = True
    merged["psamount_ledger"] = ledger
    merged["psamount_msg_cd"] = psamount.get("msg_cd", "")
    merged["psamount_message"] = psamount.get("message", "")
    merged["psamount_debug_keys"] = psamount.get("debug_keys", "")
    if str(psamount.get("rt_cd", "")) not in {"0", ""}:
        return merged
    for key in ("cash", "withdrawable_cash", "total_evaluation"):
        if _to_number(merged.get(key, 0)) == 0 and _to_number(psamount.get(key, 0)) != 0:
            merged[key] = psamount[key]
    return merged


def _overseas_zero_balance_message(parsed: dict) -> str:
    details = []
    for key in ("psamount_msg_cd", "psamount_message", "margin_msg_cd", "margin_message", "psamount_debug_keys"):
        value = str(parsed.get(key, "")).strip()
        if value:
            details.append(value)
    suffix = f" ({' / '.join(details)})" if details else ""
    return f"해외 잔고/매수가능금액 응답에서 USD 금액을 찾지 못했습니다.{suffix}"


def _market_from_query(parsed) -> str:
    return _market(parse_qs(parsed.query).get("market", [DEFAULT_MARKET])[0])


def _limit_from_query(parsed, default: int = 80) -> int:
    raw = parse_qs(parsed.query).get("limit", [str(default)])[0]
    try:
        return max(1, min(200, int(raw)))
    except (TypeError, ValueError):
        return default


def _market_from_payload(payload: dict, parsed) -> str:
    return _market(payload.get("market") or parse_qs(parsed.query).get("market", [DEFAULT_MARKET])[0])


def _market(value: object) -> str:
    market = str(value or DEFAULT_MARKET).strip().lower()
    return market if market in SUPPORTED_MARKETS else DEFAULT_MARKET


def load_live_strategy_config(market: str = DEFAULT_MARKET, seed_capital: float | None = None) -> StockScannerConfig:
    config = StockScannerConfig()
    market = _market(market)
    if market == OVERSEAS_MARKET:
        path = OVERSEAS_SCANNER_CONFIG_PATH
    else:
        path = SCANNER_CONFIG_PATH
    if path.exists():
        config = StockScannerConfig.from_dict(_read_json_file(path))
    # 프리셋 파일 분리 대신 장세 기반 자동 프로파일을 기본 모드로 강제한다.
    reentry_block = config.stop_loss_reentry_block_minutes
    if reentry_block <= 0:
        reentry_block = 25 if market == OVERSEAS_MARKET else 20
    config = replace(
        config,
        adaptive_market_regime=True,
        stop_loss_reentry_block_minutes=reentry_block,
    )
    if seed_capital and seed_capital > 0:
        return replace(config, initial_capital=seed_capital)
    return config


def auto_start_live_trader(market: str = DEFAULT_MARKET) -> dict:
    market = _market(market)
    config = load_live_config(market)
    if not config.auto_start:
        return {"running": False, "message": "자동시작 꺼짐"}
    seed_capital, seed_error = resolve_seed_capital(config)
    if seed_capital <= 0:
        return {"running": False, "message": seed_error or "자동시작 실패: 시드 금액 없음"}
    strategy = load_live_strategy_config(market, seed_capital)
    return start_live_trader(strategy, market)


def auto_start_live_traders() -> dict[str, dict]:
    return {
        market: auto_start_live_trader(market)
        for market in (DEFAULT_MARKET, OVERSEAS_MARKET)
    }


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _safe_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and name not in {".", ".."}


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _mask_account(value: str) -> str:
    value = str(value or "")
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}****{value[-2:]}"


def _to_number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return int(number) if number.is_integer() else number


def _report_label(name: str, metrics: dict) -> str:
    strategy = metrics.get("strategy")
    symbol = metrics.get("symbol")
    if strategy:
        return f"{name} ({strategy})"
    if symbol:
        return f"{name} ({symbol})"
    return name


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    ensure_live_report(live_report_dir(DEFAULT_MARKET), strategy_name="live_volatile_stock_scanner")
    ensure_live_report(live_report_dir(OVERSEAS_MARKET), strategy_name="live_overseas_stock_scanner")
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    auto_start_statuses = auto_start_live_traders()
    for market, auto_start_status in auto_start_statuses.items():
        label = "해외" if market == OVERSEAS_MARKET else "국내"
        if auto_start_status.get("running"):
            print(f"[live:{market}] {label} 자동매매 자동시작")
        elif load_live_config(market).auto_start:
            print(f"[live:{market}] {label} 자동시작 실패: {auto_start_status.get('message', 'unknown')}")
    server.serve_forever()


if __name__ == "__main__":
    run()
