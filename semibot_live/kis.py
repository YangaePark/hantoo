from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    access_token_expires_at: str = ""

    @classmethod
    def from_file(cls, path: Path) -> "KisCredentials":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            app_key=data.get("app_key", ""),
            app_secret=data.get("app_secret", ""),
            base_url=data.get("base_url", "https://openapi.koreainvestment.com:9443"),
            access_token=data.get("access_token", ""),
            access_token_expires_at=data.get("access_token_expires_at", ""),
        )


class KisClient:
    def __init__(self, credentials: KisCredentials, credentials_path: Path | None = None):
        self.credentials = credentials
        self.credentials_path = credentials_path
        self.access_token = credentials.access_token
        self.access_token_expires_at = credentials.access_token_expires_at

    def ensure_token(self) -> str:
        if self.access_token and not self._token_expiring_soon():
            return self.access_token
        return self.refresh_token()

    def refresh_token(self) -> str:
        body = {
            "grant_type": "client_credentials",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
        }
        data = self._request("POST", "/oauth2/tokenP", body=body, auth=False)
        self.access_token = data["access_token"]
        self.access_token_expires_at = _token_expiry(data)
        self._save_token()
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

    def inquire_overseas_price(self, exchange_code: str, symbol: str, auth: str = "") -> dict[str, Any]:
        params = {
            "AUTH": auth,
            "EXCD": exchange_code,
            "SYMB": symbol,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-price/v1/quotations/price?{urlencode(params)}",
            tr_id="HHDFS00000300",
        )

    def overseas_trade_value_rank(
        self,
        *,
        exchange_code: str = "NAS",
        days: str = "0",
        volume_range: str = "4",
        price_min: str = "5",
        price_max: str = "",
        auth: str = "",
        keyb: str = "",
    ) -> dict[str, Any]:
        params = {
            "EXCD": exchange_code,
            "NDAY": days,
            "VOL_RANG": volume_range,
            "AUTH": auth,
            "KEYB": keyb,
            "PRC1": price_min,
            "PRC2": price_max,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/ranking/trade-pbmn?{urlencode(params)}",
            tr_id="HHDFS76320010",
        )

    def overseas_trade_volume_rank(
        self,
        *,
        exchange_code: str = "NAS",
        days: str = "0",
        volume_range: str = "4",
        price_min: str = "5",
        price_max: str = "",
        auth: str = "",
        keyb: str = "",
    ) -> dict[str, Any]:
        params = {
            "EXCD": exchange_code,
            "NDAY": days,
            "VOL_RANG": volume_range,
            "KEYB": keyb,
            "AUTH": auth,
            "PRC1": price_min,
            "PRC2": price_max,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/ranking/trade-vol?{urlencode(params)}",
            tr_id="HHDFS76310010",
        )

    def overseas_updown_rate_rank(
        self,
        *,
        exchange_code: str = "NAS",
        days: str = "0",
        gubn: str = "1",
        volume_range: str = "4",
        auth: str = "",
        keyb: str = "",
    ) -> dict[str, Any]:
        params = {
            "EXCD": exchange_code,
            "NDAY": days,
            "GUBN": gubn,
            "VOL_RANG": volume_range,
            "AUTH": auth,
            "KEYB": keyb,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/ranking/updown-rate?{urlencode(params)}",
            tr_id="HHDFS76290000",
        )

    def overseas_volume_surge_rank(
        self,
        *,
        exchange_code: str = "NAS",
        minutes: str = "4",
        volume_range: str = "4",
        keyb: str = "",
        auth: str = "",
    ) -> dict[str, Any]:
        params = {
            "EXCD": exchange_code,
            "MINX": minutes,
            "VOL_RANG": volume_range,
            "KEYB": keyb,
            "AUTH": auth,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/ranking/volume-surge?{urlencode(params)}",
            tr_id="HHDFS76270000",
        )

    def overseas_volume_power_rank(
        self,
        *,
        exchange_code: str = "NAS",
        days: str = "0",
        volume_range: str = "4",
        auth: str = "",
        keyb: str = "",
    ) -> dict[str, Any]:
        params = {
            "EXCD": exchange_code,
            "NDAY": days,
            "VOL_RANG": volume_range,
            "AUTH": auth,
            "KEYB": keyb,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/ranking/volume-power?{urlencode(params)}",
            tr_id="HHDFS76280000",
        )

    def volume_rank(self, *, sort_code: str = "3", min_volume: str = "0") -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "1",
            "FID_BLNG_CLS_CODE": sort_code,
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "1111111111",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "1000000",
            "FID_VOL_CNT": min_volume,
            "FID_INPUT_DATE_1": "",
        }
        return self._request(
            "GET",
            f"/uapi/domestic-stock/v1/quotations/volume-rank?{urlencode(params)}",
            tr_id="FHPST01710000",
        )

    def fluctuation_rank(self, *, min_rate: str = "2", max_rate: str = "30", count: str = "50") -> dict[str, Any]:
        params = {
            "fid_rsfl_rate2": max_rate,
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20170",
            "fid_input_iscd": "0000",
            "fid_rank_sort_cls_code": "0000",
            "fid_input_cnt_1": count,
            "fid_prc_cls_code": "0",
            "fid_input_price_1": "0",
            "fid_input_price_2": "1000000",
            "fid_vol_cnt": "0",
            "fid_trgt_cls_code": "0",
            "fid_trgt_exls_cls_code": "1111111111",
            "fid_div_cls_code": "0",
            "fid_rsfl_rate1": min_rate,
        }
        return self._request(
            "GET",
            f"/uapi/domestic-stock/v1/ranking/fluctuation?{urlencode(params)}",
            tr_id="FHPST01700000",
        )

    def volume_power_rank(self) -> dict[str, Any]:
        params = {
            "fid_trgt_exls_cls_code": "0",
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20168",
            "fid_input_iscd": "0000",
            "fid_div_cls_code": "1",
            "fid_input_price_1": "0",
            "fid_input_price_2": "1000000",
            "fid_vol_cnt": "0",
            "fid_trgt_cls_code": "0",
        }
        return self._request(
            "GET",
            f"/uapi/domestic-stock/v1/ranking/volume-power?{urlencode(params)}",
            tr_id="FHPST01680000",
        )

    def inquire_balance(self, account_no: str, product_code: str = "01", *, live: bool = True) -> dict[str, Any]:
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
            tr_id="TTTC8434R" if live else "VTTC8434R",
        )

    def inquire_overseas_balance(
        self,
        account_no: str,
        product_code: str = "01",
        *,
        exchange_code: str = "NASD",
        currency: str = "USD",
        live: bool = True,
    ) -> dict[str, Any]:
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
            "OVRS_EXCG_CD": exchange_code,
            "TR_CRCY_CD": currency,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/trading/inquire-balance?{urlencode(params)}",
            tr_id="TTTS3012R" if live else "VTTS3012R",
        )

    def inquire_overseas_margin(self, account_no: str, product_code: str = "01", *, live: bool = True) -> dict[str, Any]:
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
        }
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/trading/foreign-margin?{urlencode(params)}",
            tr_id="TTTC2101R" if live else "VTTC2101R",
        )

    def inquire_overseas_psamount(
        self,
        account_no: str,
        product_code: str = "01",
        *,
        exchange_code: str = "NASD",
        price: str = "1.4",
        symbol: str = "QQQ",
        live: bool = True,
        night: bool = False,
    ) -> dict[str, Any]:
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
            "OVRS_EXCG_CD": exchange_code,
            "OVRS_ORD_UNPR": price,
            "ITEM_CD": symbol,
        }
        tr_id = "JTTT3007R" if night else "TTTS3007R"
        if not live:
            tr_id = "VTTS3007R"
        return self._request(
            "GET",
            f"/uapi/overseas-stock/v1/trading/inquire-psamount?{urlencode(params)}",
            tr_id=tr_id,
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

    def order_overseas(
        self,
        *,
        account_no: str,
        product_code: str,
        exchange_code: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_division: str = "00",
        order_server_division: str = "0",
        live: bool = False,
    ) -> dict[str, Any]:
        tr_id = _overseas_order_tr_id(exchange_code, side)
        if not live:
            tr_id = "V" + tr_id[1:]
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
            "OVRS_EXCG_CD": exchange_code,
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": _format_overseas_price(price, exchange_code),
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "SLL_TYPE": "00" if side == "sell" else "",
            "ORD_SVR_DVSN_CD": order_server_division,
            "ORD_DVSN": order_division,
        }
        return self._request("POST", "/uapi/overseas-stock/v1/trading/order", body=body, tr_id=tr_id, hash_body=True)

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
        return self._send_request(url, payload, headers, method, retry_auth=auth)

    def _send_request(
        self,
        url: str,
        payload: bytes | None,
        headers: dict[str, str],
        method: str,
        *,
        retry_auth: bool,
        retried: bool = False,
    ) -> dict[str, Any]:
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                if retry_auth and not retried and _looks_like_token_error(data):
                    headers["authorization"] = f"Bearer {self.refresh_token()}"
                    return self._send_request(url, payload, headers, method, retry_auth=True, retried=True)
                return data
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if retry_auth and not retried and exc.code in {401, 403}:
                headers["authorization"] = f"Bearer {self.refresh_token()}"
                return self._send_request(url, payload, headers, method, retry_auth=True, retried=True)
            return {"rt_cd": "-1", "msg_cd": f"HTTP_{exc.code}", "msg1": detail}

    def _token_expiring_soon(self) -> bool:
        expires_at = _parse_token_expiry(self.access_token_expires_at)
        if expires_at is None:
            return False
        return datetime.now(timezone.utc) >= expires_at - timedelta(minutes=10)

    def _save_token(self) -> None:
        if not self.credentials_path:
            return
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if self.credentials_path.exists():
            data = json.loads(self.credentials_path.read_text(encoding="utf-8"))
        data.update(
            {
                "app_key": self.credentials.app_key,
                "app_secret": self.credentials.app_secret,
                "base_url": self.credentials.base_url,
                "access_token": self.access_token,
                "access_token_expires_at": self.access_token_expires_at,
            }
        )
        self.credentials_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_price_response(data: dict[str, Any]) -> dict[str, float]:
    output = data.get("output") or {}
    price = _float(output.get("stck_prpr"))
    open_price = _float(output.get("stck_oprc")) or price
    high = _float(output.get("stck_hgpr")) or price
    low = _float(output.get("stck_lwpr")) or price
    volume = _float(output.get("acml_vol"))
    value = _float(output.get("acml_tr_pbmn"))
    prev_rate = _float(output.get("prdy_ctrt"))
    bid = _first_float(output, ("bidp1", "bidp", "buy_bidp", "best_bidp"))
    ask = _first_float(output, ("askp1", "askp", "sell_askp", "best_askp"))
    spread = 0.0
    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        spread = ((ask - bid) / mid) if mid else 0.0
    return {
        "price": price,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "value": value,
        "prev_rate_pct": prev_rate,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread,
    }


def parse_overseas_price_response(data: dict[str, Any]) -> dict[str, float]:
    output = data.get("output") or {}
    price = _first_float(output, ("last", "ovrs_prpr", "stck_prpr"))
    open_price = _first_float(output, ("open", "ovrs_oprc", "stck_oprc")) or price
    high = _first_float(output, ("high", "ovrs_hgpr", "stck_hgpr")) or price
    low = _first_float(output, ("low", "ovrs_lwpr", "stck_lwpr")) or price
    volume = _first_float(output, ("tvol", "acml_vol", "ovrs_acml_vol"))
    value = _first_float(output, ("tamt", "acml_tr_pbmn", "ovrs_acml_tr_pbmn"))
    prev_rate = _first_float(output, ("rate", "prdy_ctrt", "ovrs_prdy_ctrt"))
    previous_close = _first_float(output, ("base", "clos", "ovrs_sdpr"))
    if previous_close > 0 and price > 0 and prev_rate == 0:
        prev_rate = ((price / previous_close) - 1.0) * 100.0
    return {
        "price": price,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "value": value,
        "prev_rate_pct": prev_rate,
    }


def parse_rank_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("output", "output1", "output2"):
        output = data.get(key) or []
        if isinstance(output, dict):
            output = [output]
        rows.extend(row for row in output if isinstance(row, dict))
    return rows


def parse_balance_response(data: dict[str, Any]) -> dict[str, Any]:
    summary = _first_dict(data.get("output2"))
    holdings = data.get("output1") or []
    if isinstance(holdings, dict):
        holdings = [holdings]

    parsed_holdings = []
    for row in holdings:
        if not isinstance(row, dict):
            continue
        quantity = _float(row.get("hldg_qty") or row.get("ord_psbl_qty"))
        if quantity <= 0:
            continue
        parsed_holdings.append(
            {
                "symbol": str(row.get("pdno") or "").strip(),
                "name": str(row.get("prdt_name") or row.get("prdt_abrv_name") or "").strip(),
                "quantity": quantity,
                "average_price": _float(row.get("pchs_avg_pric")),
                "current_price": _float(row.get("prpr")),
                "evaluation": _float(row.get("evlu_amt")),
                "profit_loss": _float(row.get("evlu_pfls_amt")),
                "profit_loss_rate": _float(row.get("evlu_pfls_rt")),
            }
        )

    return {
        "rt_cd": str(data.get("rt_cd", "")),
        "msg_cd": data.get("msg_cd", ""),
        "message": data.get("msg1", ""),
        "cash": _first_float(summary, ("dnca_tot_amt", "prvs_rcdl_excc_amt", "nxdy_excc_amt", "d2_auto_rdpt_amt")),
        "withdrawable_cash": _first_float(summary, ("prvs_rcdl_excc_amt", "nxdy_excc_amt", "dnca_tot_amt")),
        "total_evaluation": _first_float(summary, ("tot_evlu_amt", "nass_amt", "asst_icdc_amt")),
        "stock_evaluation": _first_float(summary, ("scts_evlu_amt", "evlu_amt_smtl_amt")),
        "profit_loss": _first_float(summary, ("evlu_pfls_smtl_amt", "asst_icdc_amt")),
        "profit_loss_rate": _first_float(summary, ("evlu_pfls_rt", "asst_icdc_erng_rt")),
        "holdings": parsed_holdings,
        "raw": data,
    }


def parse_order_response(data: dict[str, Any]) -> dict[str, Any]:
    """KIS 주문 응답에서 주문번호/접수일시를 추출."""
    output = data.get("output")
    if isinstance(output, list):
        output = output[0] if output else {}
    if not isinstance(output, dict):
        output = {}
    return {
        "rt_cd": str(data.get("rt_cd", "")),
        "msg": str(data.get("msg1") or data.get("msg_cd") or ""),
        "order_no": str(output.get("ODNO") or output.get("odno") or ""),
        "fwdg_org_no": str(output.get("KRX_FWDG_ORD_ORGNO") or output.get("krx_fwdg_ord_orgno") or ""),
        "ord_time": str(output.get("ORD_TMD") or output.get("ord_tmd") or ""),
    }


def parse_overseas_balance_response(data: dict[str, Any]) -> dict[str, Any]:
    rows = _output_rows(data, ("output1", "output2", "output3", "output"))
    holding_rows = [row for row in rows if _looks_like_overseas_holding(row)]
    if not holding_rows:
        holding_rows = _dict_rows(data.get("output1"))
    summary_rows = [row for row in rows if _looks_like_overseas_summary(row)]
    if not summary_rows:
        summary_rows = _dict_rows(data.get("output2")) + _dict_rows(data.get("output3"))

    parsed_holdings = []
    for row in holding_rows:
        if not isinstance(row, dict):
            continue
        quantity = _first_float(row, ("ovrs_cblc_qty", "ord_psbl_qty", "hldg_qty"))
        if quantity <= 0:
            continue
        parsed_holdings.append(
            {
                "symbol": str(row.get("ovrs_pdno") or row.get("pdno") or "").strip(),
                "name": str(row.get("ovrs_item_name") or row.get("prdt_name") or row.get("prdt_abrv_name") or "").strip(),
                "quantity": quantity,
                "average_price": _first_float(row, ("pchs_avg_pric", "frcr_pchs_amt1")),
                "current_price": _first_float(row, ("now_pric2", "ovrs_now_pric1", "prpr")),
                "evaluation": _first_float(row, ("ovrs_stck_evlu_amt", "evlu_amt", "frcr_evlu_amt2")),
                "profit_loss": _first_float(row, ("frcr_evlu_pfls_amt", "evlu_pfls_amt")),
                "profit_loss_rate": _first_float(row, ("evlu_pfls_rt", "evlu_erng_rt")),
            }
        )

    cash = _first_float_from_rows(
        summary_rows,
        (
            "frcr_dncl_amt_2",
            "frcr_dncl_amt",
            "frcr_drwg_psbl_amt_1",
            "ord_psbl_frcr_amt",
            "dnca_tot_amt",
            "tot_frcr_cblc_smtl",
        ),
    )
    withdrawable_cash = _first_float_from_rows(
        summary_rows,
        (
            "frcr_drwg_psbl_amt_1",
            "frcr_drwg_psbl_amt",
            "ord_psbl_frcr_amt",
            "frcr_dncl_amt_2",
            "frcr_dncl_amt",
        ),
    )

    return {
        "rt_cd": str(data.get("rt_cd", "")),
        "msg_cd": data.get("msg_cd", ""),
        "message": data.get("msg1", ""),
        "cash": cash,
        "withdrawable_cash": withdrawable_cash,
        "total_evaluation": _first_float_from_rows(
            summary_rows,
            ("tot_evlu_amt", "tot_asst_amt", "nass_amt", "ovrs_stck_evlu_amt", "frcr_evlu_amt2", "frcr_evlu_tota"),
        ),
        "stock_evaluation": _first_float_from_rows(summary_rows, ("ovrs_stck_evlu_amt", "frcr_evlu_amt2")),
        "profit_loss": _first_float_from_rows(summary_rows, ("tot_evlu_pfls_amt", "ovrs_tot_pfls", "evlu_pfls_smtl_amt")),
        "profit_loss_rate": _first_float_from_rows(summary_rows, ("tot_pftrt", "rlzt_erng_rt", "evlu_pfls_rt")),
        "holdings": parsed_holdings,
        "raw": data,
    }


def parse_overseas_margin_response(data: dict[str, Any], currency: str = "USD") -> dict[str, Any]:
    rows = _preferred_currency_rows(_output_rows(data, ("output", "output1", "output2", "output3")), currency)
    cash = _first_float_from_rows(
        rows,
        (
            "frcr_dncl_amt_2",
            "frcr_dncl_amt",
            "frcr_cblc",
            "frcr_bal",
            "ord_psbl_frcr_amt",
            "ovrs_ord_psbl_amt",
            "frcr_buy_psbl_amt",
        ),
    )
    withdrawable_cash = _first_float_from_rows(
        rows,
        (
            "frcr_drwg_psbl_amt_1",
            "frcr_drwg_psbl_amt",
            "ord_psbl_frcr_amt",
            "ovrs_ord_psbl_amt",
            "frcr_buy_psbl_amt",
            "frcr_dncl_amt_2",
            "frcr_dncl_amt",
        ),
    )
    total_evaluation = _first_float_from_rows(
        rows,
        ("tot_evlu_amt", "tot_asst_amt", "frcr_evlu_tota", "frcr_evlu_amt2", "frcr_dncl_amt_2", "frcr_dncl_amt"),
    )
    if total_evaluation == 0:
        total_evaluation = max(cash, withdrawable_cash)
    return {
        "rt_cd": str(data.get("rt_cd", "")),
        "msg_cd": data.get("msg_cd", ""),
        "message": data.get("msg1", ""),
        "cash": cash,
        "withdrawable_cash": withdrawable_cash,
        "total_evaluation": total_evaluation,
        "stock_evaluation": 0.0,
        "profit_loss": 0.0,
        "profit_loss_rate": 0.0,
        "holdings": [],
        "raw": data,
    }


def parse_overseas_psamount_response(data: dict[str, Any]) -> dict[str, Any]:
    rows = _output_rows(data, ("output", "output1", "output2", "output3"))
    orderable_cash = _first_float_from_rows(
        rows,
        (
            "ovrs_ord_psbl_amt",
            "ord_psbl_frcr_amt",
            "frcr_ord_psbl_amt",
            "max_ord_psbl_amt",
            "ord_psbl_cash",
            "ord_psbl_amt",
            "frcr_buy_psbl_amt",
            "ovrs_max_ord_psbl_amt",
        ),
    )
    return {
        "rt_cd": str(data.get("rt_cd", "")),
        "msg_cd": data.get("msg_cd", ""),
        "message": data.get("msg1", ""),
        "cash": orderable_cash,
        "withdrawable_cash": orderable_cash,
        "total_evaluation": orderable_cash,
        "stock_evaluation": 0.0,
        "profit_loss": 0.0,
        "profit_loss_rate": 0.0,
        "holdings": [],
        "debug_keys": _response_key_summary(data),
        "raw": data,
    }


def rank_row_symbol(row: dict[str, Any]) -> str:
    return str(
        row.get("stck_shrn_iscd")
        or row.get("mksc_shrn_iscd")
        or row.get("ovrs_pdno")
        or row.get("symb")
        or row.get("SYMB")
        or row.get("rsym")
        or row.get("PDNO")
        or row.get("pdno")
        or ""
    ).strip()


def _overseas_order_tr_id(exchange_code: str, side: str) -> str:
    exchange_code = str(exchange_code or "").upper()
    side = str(side or "").lower()
    if side == "buy":
        if exchange_code in {"NASD", "NYSE", "AMEX"}:
            return "TTTT1002U"
        if exchange_code == "SEHK":
            return "TTTS1002U"
        if exchange_code == "SHAA":
            return "TTTS0202U"
        if exchange_code == "SZAA":
            return "TTTS0305U"
        if exchange_code == "TKSE":
            return "TTTS0308U"
        if exchange_code in {"HASE", "VNSE"}:
            return "TTTS0311U"
    if side == "sell":
        if exchange_code in {"NASD", "NYSE", "AMEX"}:
            return "TTTT1006U"
        if exchange_code == "SEHK":
            return "TTTS1001U"
        if exchange_code == "SHAA":
            return "TTTS1005U"
        if exchange_code == "SZAA":
            return "TTTS0304U"
        if exchange_code == "TKSE":
            return "TTTS0307U"
        if exchange_code in {"HASE", "VNSE"}:
            return "TTTS0310U"
    raise ValueError(f"unsupported overseas order: exchange_code={exchange_code}, side={side}")


def _format_overseas_price(price: float, exchange_code: str = "") -> str:
    number = _float(price)
    if number <= 0:
        return "0"
    if str(exchange_code or "").upper() in {"NASD", "NYSE", "AMEX"} and number >= 1:
        return f"{number:.2f}"
    return f"{number:.8f}".rstrip("0").rstrip(".")


def _token_expiry(data: dict[str, Any]) -> str:
    explicit = str(data.get("access_token_token_expired") or data.get("access_token_expires_at") or "").strip()
    if explicit:
        parsed = _parse_token_expiry(explicit)
        if parsed:
            return parsed.isoformat()
        return explicit
    expires_in = _float(data.get("expires_in"))
    if expires_in <= 0:
        expires_in = 24 * 60 * 60
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


def _parse_token_expiry(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    for candidate in (value, value.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone(timedelta(hours=9)))
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)
        except ValueError:
            pass
    return None


def _looks_like_token_error(data: dict[str, Any]) -> bool:
    if str(data.get("rt_cd", "")) in {"0", ""}:
        return False
    text = f"{data.get('msg_cd', '')} {data.get('msg1', '')}".lower()
    return any(token in text for token in ("token", "토큰", "oauth", "authorization", "unauthorized", "인증"))


def _float(value: object) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _first_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    return {}


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _output_rows(data: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        rows.extend(_dict_rows(data.get(key)))
    return rows


def _response_key_summary(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("output", "output1", "output2", "output3"):
        rows = _dict_rows(data.get(key))
        if not rows:
            continue
        row_keys = sorted({row_key for row in rows[:3] for row_key in row})
        parts.append(f"{key}: {','.join(row_keys[:12])}")
    return " / ".join(parts)


def _looks_like_overseas_holding(row: dict[str, Any]) -> bool:
    symbol = str(row.get("ovrs_pdno") or row.get("pdno") or row.get("symb") or "").strip()
    if not symbol:
        return False
    if _first_float(row, ("ovrs_cblc_qty", "ord_psbl_qty", "hldg_qty")) > 0:
        return True
    return any(row.get(key) for key in ("ovrs_item_name", "prdt_name", "prdt_abrv_name"))


def _looks_like_overseas_summary(row: dict[str, Any]) -> bool:
    if _looks_like_overseas_holding(row):
        return False
    return any(
        key in row
        for key in (
            "frcr_dncl_amt_2",
            "frcr_dncl_amt",
            "frcr_drwg_psbl_amt_1",
            "frcr_drwg_psbl_amt",
            "ord_psbl_frcr_amt",
            "tot_evlu_amt",
            "tot_asst_amt",
            "nass_amt",
            "frcr_evlu_tota",
            "tot_frcr_cblc_smtl",
        )
    )


def _preferred_currency_rows(rows: list[dict[str, Any]], currency: str = "") -> list[dict[str, Any]]:
    currency = str(currency or "").strip().upper()
    if not currency:
        return rows
    matches: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for row in rows:
        row_currency = str(row.get("crcy_cd") or row.get("tr_crcy_cd") or row.get("TR_CRCY_CD") or "").strip().upper()
        if row_currency == currency:
            matches.append(row)
        else:
            rest.append(row)
    return matches + rest


def _first_float_from_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> float:
    for row in rows:
        number = _first_float(row, keys)
        if number != 0:
            return number
    return 0.0


def _first_float(data: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        number = _float(data.get(key))
        if number != 0:
            return number
    return 0.0
