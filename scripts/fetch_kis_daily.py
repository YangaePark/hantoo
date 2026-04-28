#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="Download daily OHLCV from Korea Investment Open API.")
    parser.add_argument("--symbol", default="396500", help="KRX symbol, e.g. 396500")
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--base-url", default=os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443"))
    parser.add_argument("--chunk-days", type=int, default=90, help="Date window size per request")
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds to sleep between API calls")
    args = parser.parse_args()

    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    if not app_key or not app_secret:
        raise SystemExit("Set KIS_APP_KEY and KIS_APP_SECRET first.")

    token = issue_token(args.base_url, app_key, app_secret)
    rows_by_date: dict[str, dict[str, str]] = {}
    windows = list(date_windows(args.start, args.end, args.chunk_days))
    for idx, (start, end) in enumerate(windows, start=1):
        print(f"fetching {args.symbol} {start}~{end} ({idx}/{len(windows)})")
        rows = fetch_daily(args.base_url, app_key, app_secret, token, args.symbol, start, end)
        rows_by_date.update({row["date"]: row for row in rows})
        if idx < len(windows):
            time.sleep(args.sleep)

    rows = [rows_by_date[key] for key in sorted(rows_by_date)]
    write_csv(Path(args.out), rows)
    print(f"wrote {len(rows)} bars to {args.out}")
    return 0


def issue_token(base_url: str, app_key: str, app_secret: str) -> str:
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    request = Request(
        f"{base_url}/oauth2/tokenP",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json; charset=utf-8"},
        method="POST",
    )
    data = _request_json(request)
    return data["access_token"]


def fetch_daily(
    base_url: str,
    app_key: str,
    app_secret: str,
    token: str,
    symbol: str,
    start: str,
    end: str,
) -> list[dict[str, str]]:
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_DATE_1": start,
        "FID_INPUT_DATE_2": end,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }
    query = urlencode(params)
    request = Request(
        f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice?{query}",
        headers={
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST03010100",
            "custtype": "P",
        },
        method="GET",
    )
    data = _request_json(request)
    if data.get("rt_cd") != "0":
        raise RuntimeError(f"KIS API error: {data.get('msg_cd')} {data.get('msg1')}")

    output = data.get("output2") or []
    rows = [
        {
            "date": item["stck_bsop_date"],
            "open": item["stck_oprc"],
            "high": item["stck_hgpr"],
            "low": item["stck_lwpr"],
            "close": item["stck_clpr"],
            "volume": item["acml_vol"],
        }
        for item in output
    ]
    rows.sort(key=lambda row: row["date"])
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def date_windows(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")

    current = datetime.strptime(start, "%Y%m%d").date()
    final = datetime.strptime(end, "%Y%m%d").date()
    windows: list[tuple[str, str]] = []
    while current <= final:
        chunk_end = min(final, current + timedelta(days=chunk_days - 1))
        windows.append((current.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        current = chunk_end + timedelta(days=1)
    return windows


def _request_json(request: Request) -> dict:
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
