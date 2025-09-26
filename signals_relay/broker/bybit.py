# signals_relay/broker/bybit.py
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from signals_relay.config import cfg

log = logging.getLogger(__name__)

JSON = Dict[str, Any]


def _now_ms() -> int:
    return int(time.time() * 1000)


class BybitBroker:
    """
    v5-клиент Bybit (UTA) для линейных контрактов (USDT Perp).
    - подпись X-BAPI-* (HMAC SHA256)
    - авто-синхронизация времени (offset) по /v5/market/time
    - ретраи/ресинк на retCode 10002/10003
    - кэш шагов инструмента
    """

    def __init__(self) -> None:
        self.api_key = cfg.BYBIT_API_KEY
        self.api_secret = cfg.BYBIT_API_SECRET.encode()
        self.category = cfg.BYBIT_CATEGORY
        self.recv_window_ms = cfg.BYBIT_RECV_WINDOW_MS
        self.max_retries = cfg.BYBIT_MAX_RETRIES
        self.time_resync_sec = cfg.BYBIT_TIME_RESYNC_SEC

        self.base_url = "https://api-testnet.bybit.com" if cfg.BYBIT_TESTNET else "https://api.bybit.com"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(cfg.BYBIT_TIMEOUT_SEC, connect=cfg.BYBIT_TIMEOUT_SEC),
            headers={"Content-Type": "application/json"},
        )

        self._time_offset_ms: int = 0
        self._last_sync_ts: float = 0.0
        self._instruments: Dict[str, Tuple[float, float]] = {}  # symbol -> (tickSize, qtyStep)

        log.info(
            "Broker=Bybit v5 ready [%s, category=%s]",
            "TESTNET" if cfg.BYBIT_TESTNET else "LIVE",
            self.category,
        )

    # ---------- time sync ----------

    async def _sync_time(self) -> None:
        try:
            r = await self._client.get("/v5/market/time")
            r.raise_for_status()
            data = r.json()
            server_ms: Optional[int] = None
            if isinstance(data, dict):
                if "time" in data and isinstance(data["time"], (int, float)):
                    server_ms = int(data["time"])
                elif "result" in data and isinstance(data["result"], dict):
                    res = data["result"]
                    if "timeNano" in res:
                        server_ms = int(int(res["timeNano"]) / 1_000_000)
                    elif "timeSecond" in res:
                        server_ms = int(res["timeSecond"]) * 1000
            if not server_ms:
                raise RuntimeError(f"Unexpected time payload: {data}")

            local_ms = _now_ms()
            self._time_offset_ms = server_ms - local_ms
            self._last_sync_ts = time.time()
            log.info("Bybit time sync: offset=%s ms", self._time_offset_ms)
        except Exception as e:
            log.warning("Bybit: time sync failed: %s", e)

    def _need_resync(self) -> bool:
        return (time.time() - self._last_sync_ts) > self.time_resync_sec

    # ---------- signing ----------

    def _signed_headers(self, method: str, query: Optional[JSON], body: Optional[JSON]) -> Dict[str, str]:
        ts = _now_ms() + self._time_offset_ms
        recv = self.recv_window_ms

        if method.upper() == "GET":
            payload = ""
            if query:
                items = sorted((k, str(v)) for k, v in query.items() if v is not None)
                payload = "&".join(f"{k}={v}" for k, v in items)
        else:
            payload = json.dumps(body or {}, separators=(",", ":"))

        sign_str = f"{ts}{self.api_key}{recv}{payload}"
        sign = hmac.new(self.api_secret, sign_str.encode(), hashlib.sha256).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": str(ts),
            "X-BAPI-RECV-WINDOW": str(recv),
            "X-BAPI-SIGN-TYPE": "2",
            "Content-Type": "application/json",
        }

    # ---------- core request ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[JSON] = None,
        body: Optional[JSON] = None,
        auth: bool = True,
        opname: str = "",
    ) -> JSON:
        tries = 0
        if self._need_resync():
            await self._sync_time()

        while True:
            tries += 1
            headers = self._signed_headers(method, query, body) if auth else None
            try:
                if method.upper() == "GET":
                    resp = await self._client.get(path, params=query, headers=headers)
                else:
                    resp = await self._client.post(path, params=query, json=body, headers=headers)
                j = resp.json()
                ret = j.get("retCode")
                if ret == 0:
                    return j.get("result") or {}
                if ret in (10002, 10003):
                    log.error("Timestamp window on %s → resync & retry (%s: %s)", opname or path, ret, j.get("retMsg"))
                    await self._sync_time()
                    if tries <= self.max_retries:
                        await asyncio.sleep(0.5 * tries)
                        continue
                raise RuntimeError(f"{j.get('retMsg','Bybit error')} (ErrCode: {ret})")
            except httpx.HTTPError as e:
                if tries <= self.max_retries:
                    await asyncio.sleep(0.5 * tries)
                    continue
                raise RuntimeError(f"HTTP error {opname or path}: {e}") from e

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------- market meta ----------

    async def _instrument_info(self, symbol: str) -> Tuple[float, float]:
        if symbol in self._instruments:
            return self._instruments[symbol]
        res = await self._request(
            "GET",
            "/v5/market/instruments-info",
            query={"category": self.category, "symbol": symbol},
            auth=False,
            opname="instruments-info",
        )
        rows = res.get("list") or []
        if not rows:
            raise RuntimeError(f"No instrument info for {symbol}")
        row = rows[0]
        tick = float(row.get("priceFilter", {}).get("tickSize", "0.0001"))
        lot = float(row.get("lotSizeFilter", {}).get("qtyStep", "0.001"))
        self._instruments[symbol] = (tick, lot)
        return tick, lot

    @staticmethod
    def _quantize(val: float, step: float) -> float:
        return round((round(val / step) * step), 10)

    async def quantize_price_qty(
        self, symbol: str, price: Optional[float], qty: float
    ) -> Tuple[Optional[float], float]:
        tick, lot = await self._instrument_info(symbol)
        q_price = self._quantize(price, tick) if price is not None else None
        q_qty = max(self._quantize(qty, lot), lot)
        return q_price, q_qty

    # ---------- account prep ----------

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._request(
            "POST",
            "/v5/position/set-leverage",
            body={
                "category": self.category,
                "symbol": symbol,
                "buyLeverage": str(leverage),
                "sellLeverage": str(leverage),
            },
            opname="set_leverage",
        )

    async def switch_isolated(self, symbol: str) -> None:
        await self._request(
            "POST",
            "/v5/position/switch-isolated",
            body={"category": self.category, "symbol": symbol, "tradeMode": 1},
            opname="switch_isolated",
        )

    # ---------- trading ----------

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,           # "Buy" / "Sell"
        order_type: str,     # "Limit" / "Market"
        qty: float,
        price: Optional[float] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        tpsl_mode: str = "Full",
        trigger_by: str = "MarkPrice",
    ) -> JSON:
        body: JSON = {
            "category": self.category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
            "tpslMode": tpsl_mode,
        }
        if price is not None:
            body["price"] = str(price)
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
            body["tpTriggerBy"] = trigger_by
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
            body["slTriggerBy"] = trigger_by

        return await self._request("POST", "/v5/order/create", body=body, opname="place_order")
