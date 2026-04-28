from __future__ import annotations

import csv
import json
import mimetypes
import os
from dataclasses import replace
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from semibot_backtester.stock_scanner import StockScannerConfig
from semibot_live.kis import KisClient, KisCredentials, parse_balance_response
from semibot_live.trader import (
    ensure_live_report,
    LiveConfig,
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
KIS_KEYS_PATH = STATE_ROOT / "config" / "kis.local.json"
SCANNER_CONFIG_PATH = ROOT / "config" / "volatile_stock_scalp.json"


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
            self._json(load_kis_key_status())
        elif parsed.path == "/api/kis/balance":
            self._json(load_kis_balance())
        elif parsed.path == "/api/live/config":
            self._json(load_live_config().to_dict())
        elif parsed.path == "/api/live/status":
            self._json(live_status())
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/kis/keys":
            payload = self._read_json()
            app_key = str(payload.get("app_key", "")).strip()
            app_secret = str(payload.get("app_secret", "")).strip()
            access_token = str(payload.get("access_token", "")).strip()
            access_token_expires_at = str(payload.get("access_token_expires_at", "")).strip()
            base_url = str(payload.get("base_url", "https://openapi.koreainvestment.com:9443")).strip()
            if not app_key or not app_secret:
                self._json({"error": "app_key and app_secret are required"}, HTTPStatus.BAD_REQUEST)
                return
            KIS_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
            KIS_KEYS_PATH.write_text(
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
            self._json(load_kis_key_status())
        elif parsed.path == "/api/live/config":
            payload = self._read_json()
            config = LiveConfig.from_dict(payload)
            if config.mode not in {"paper", "live"}:
                self._json({"error": "mode must be paper or live"}, HTTPStatus.BAD_REQUEST)
                return
            save_live_config(config)
            self._json(config.to_dict())
        elif parsed.path == "/api/live/start":
            config = load_live_config()
            strategy = load_live_strategy_config(config.seed_capital)
            self._json(start_live_trader(strategy))
        elif parsed.path == "/api/live/stop":
            self._json(stop_live_trader())
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
        metrics_path = path / "metrics.json"
        if not metrics_path.exists():
            continue
        metrics = _read_json_file(metrics_path)
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
    report_dir = REPORTS_ROOT / name
    if not report_dir.exists():
        return {"error": "report not found"}

    metrics = _read_json_file(report_dir / "metrics.json")
    trades = _read_csv_file(report_dir / "trades.csv")
    equity = _read_csv_file(report_dir / "equity_curve.csv")
    return {
        "name": name,
        "label": _report_label(name, metrics),
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity,
        "current": current_snapshot(metrics, trades, equity),
    }


def current_snapshot(metrics: dict, trades: list[dict], equity: list[dict]) -> dict:
    last_equity = equity[-1] if equity else {}
    open_symbol = last_equity.get("symbol") or metrics.get("symbol") or ""
    open_shares = _to_number(last_equity.get("shares", 0))
    last_trade = trades[-1] if trades else {}
    return {
        "time": last_equity.get("datetime") or last_equity.get("date") or metrics.get("end_datetime") or metrics.get("end_date"),
        "equity": _to_number(last_equity.get("equity", metrics.get("final_equity", 0))),
        "cash": _to_number(last_equity.get("cash", 0)),
        "open_symbol": open_symbol if open_shares else "",
        "open_shares": open_shares,
        "last_trade": last_trade,
    }


def load_kis_key_status() -> dict:
    if not KIS_KEYS_PATH.exists():
        return {
            "configured": False,
            "token_configured": False,
            "app_key_masked": "",
            "base_url": "https://openapi.koreainvestment.com:9443",
        }
    data = _read_json_file(KIS_KEYS_PATH)
    return {
        "configured": bool(data.get("app_key") and data.get("app_secret")),
        "token_configured": bool(data.get("access_token")),
        "token_expires_at": data.get("access_token_expires_at", ""),
        "app_key_masked": _mask(str(data.get("app_key", ""))),
        "base_url": data.get("base_url", "https://openapi.koreainvestment.com:9443"),
    }


def load_kis_balance() -> dict:
    if not KIS_KEYS_PATH.exists():
        return {"ok": False, "message": "KIS 키가 저장되어 있지 않습니다."}
    config = load_live_config()
    if not config.account_no:
        return {"ok": False, "message": "계좌번호를 저장한 뒤 조회하세요."}
    client = KisClient(KisCredentials.from_file(KIS_KEYS_PATH), credentials_path=KIS_KEYS_PATH)
    response = client.inquire_balance(config.account_no, config.product_code, live=True)
    parsed = parse_balance_response(response)
    ok = parsed["rt_cd"] in {"0", ""}
    parsed.pop("raw", None)
    return {
        **parsed,
        "ok": ok,
        "account_no_masked": _mask_account(config.account_no),
        "product_code": config.product_code,
        "fetched_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
    }


def load_live_strategy_config(seed_capital: float | None = None) -> StockScannerConfig:
    config = StockScannerConfig()
    if SCANNER_CONFIG_PATH.exists():
        config = StockScannerConfig.from_dict(_read_json_file(SCANNER_CONFIG_PATH))
    if seed_capital and seed_capital > 0:
        return replace(config, initial_capital=seed_capital)
    return config


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
    ensure_live_report()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
