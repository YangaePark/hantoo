from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class KisCredentials:
    app_key: str
    app_secret: str
    base_url: str = "https://openapi.koreainvestment.com:9443"
    access_token: str = ""

    @classmethod
    def from_file(cls, path: Path) -> "KisCredentials":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            app_key=data.get("app_key", ""),
            app_secret=data.get("app_secret", ""),
            base_url=data.get("base_url", "https://openapi.koreainvestment.com:9443"),
            access_token=data.get("access_token", ""),
        )


class KisClient:
    def __init__(self, credentials: KisCredentials):
        self.credentials = credentials
        self.access_token = credentials.access_token

    def ensure_token(self) -> str:
        if self.access_token:
            return self.access_token
        body = {
            "grant_type": "client_credentials",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
        }
        data = self._request("POST", "/oauth2/tokenP", body=body, auth=False)
        self.access_token = data["access_token"]
        return self.access_token

    def hashkey(self, body: dict[str, Any]) -> str:
        data = self._request("POST", "/uapi/hashkey", body=body, auth=False)
        return data.get("HASH") or data.get("hash") or ""

    def inquire_price(self, symbol: str) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }
        return self._request(
            "GET",
            f"/uapi/domestic-stock/v1/quotations/inquire-price?{urlencode(params)}",
            tr_id="FHKST01010100",
        )

    def inquire_balance(self, account_no: str, product_code: str = "01") -> dict[str, Any]:
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        return self._request(
            "GET",
            f"/uapi/domestic-stock/v1/trading/inquire-balance?{urlencode(params)}",
            tr_id="TTTC8434R",
        )

    def order_cash(
        self,
        *,
        account_no: str,
        product_code: str,
        symbol: str,
        side: str,
        quantity: int,
        price: int = 0,
        order_division: str = "01",
        live: bool = False,
    ) -> dict[str, Any]:
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
            "PDNO": symbol,
            "ORD_DVSN": order_division,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price),
        }
        tr_id = ("TTTC0802U" if side == "buy" else "TTTC0801U") if live else ("VTTC0802U" if side == "buy" else "VTTC0801U")
        return self._request("POST", "/uapi/domestic-stock/v1/trading/order-cash", body=body, tr_id=tr_id, hash_body=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        tr_id: str | None = None,
        auth: bool = True,
        hash_body: bool = False,
    ) -> dict[str, Any]:
        url = self.credentials.base_url.rstrip("/") + path
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
            "custtype": "P",
        }
        if auth:
            headers["authorization"] = f"Bearer {self.ensure_token()}"
        if tr_id:
            headers["tr_id"] = tr_id
        if hash_body and body is not None:
            headers["hashkey"] = self.hashkey(body)
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"rt_cd": "-1", "msg_cd": f"HTTP_{exc.code}", "msg1": detail}


def parse_price_response(data: dict[str, Any]) -> dict[str, float]:
    output = data.get("output") or {}
    price = _float(output.get("stck_prpr"))
    open_price = _float(output.get("stck_oprc")) or price
    high = _float(output.get("stck_hgpr")) or price
    low = _float(output.get("stck_lwpr")) or price
    volume = _float(output.get("acml_vol"))
    value = _float(output.get("acml_tr_pbmn"))
    prev_rate = _float(output.get("prdy_ctrt"))
    return {
        "price": price,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "value": value,
        "prev_rate_pct": prev_rate,
    }


def _float(value: object) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
