from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.parse import urlencode

import httpx

from kraken_bot.domain.enums import OrderStatus, OrderType
from kraken_bot.domain.models import Candle, ExchangeOpenOrder, ExchangeOrder, ExchangeOrderResult, Quote, Ticker
from kraken_bot.exchange.base import ExchangeAdapter


class KrakenApiError(RuntimeError):
    def __init__(self, action: str, detail: str) -> None:
        self.action = action
        self.detail = detail
        super().__init__(f"Kraken API failure during {action}: {detail}")


class KrakenAdapter(ExchangeAdapter):
    def __init__(
        self,
        base_url: str,
        api_key_env: str | None,
        api_secret_env: str | None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.api_secret_env = api_secret_env
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = httpx.Client(base_url=self.base_url, timeout=10.0)
        self._asset_pair_cache: dict[str, dict[str, Any]] = {}

    def get_ticker(self, asset: str) -> Ticker:
        result = self._get_ticker_result(asset)
        return Ticker(
            asset=asset,
            price=Decimal(result["c"][0]),
            time=datetime.now(timezone.utc),
        )

    def get_quote(self, asset: str) -> Quote:
        result = self._get_ticker_result(asset)
        asset_pair = self._get_asset_pair(asset)
        tick_size = Decimal(str(asset_pair.get("tick_size") or "0"))
        increment = tick_size if tick_size > 0 else self._places_quantum(int(asset_pair.get("pair_decimals") or 0))
        return Quote(
            asset=asset,
            bid=Decimal(str(result["b"][0])),
            ask=Decimal(str(result["a"][0])),
            price_increment=increment,
            time=datetime.now(timezone.utc),
        )

    def get_ohlc(self, asset: str, interval: str, limit: int) -> list[Candle]:
        payload = self._get_public(
            "/0/public/OHLC",
            {"pair": asset, "interval": self._map_interval(interval)},
            action=f"get OHLC for {asset}",
        )
        rows = next(iter(payload["result"].values()))
        candles: list[Candle] = []
        for row in rows[-limit:]:
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(int(row[0]), tz=timezone.utc),
                    open=Decimal(row[1]),
                    high=Decimal(row[2]),
                    low=Decimal(row[3]),
                    close=Decimal(row[4]),
                    volume=Decimal(row[6]),
                )
            )
        return candles

    def place_limit_order(
        self,
        asset: str,
        side: OrderType,
        price: Decimal,
        quantity: Decimal,
        post_only: bool,
    ) -> ExchangeOrderResult:
        normalized_price, normalized_quantity = self._normalize_order_params(asset, price, quantity)
        payload = {
            "pair": asset,
            "type": side.value.lower(),
            "ordertype": "limit",
            "price": self._format_decimal(normalized_price),
            "volume": self._format_decimal(normalized_quantity),
        }
        if post_only:
            payload["oflags"] = "post"
        result = self._post_private("/0/private/AddOrder", payload, action=f"place {side.value.lower()} order for {asset}")
        txids = result.get("result", {}).get("txid")
        if not isinstance(txids, list) or not txids:
            raise KrakenApiError(f"place {side.value.lower()} order for {asset}", "missing txid in AddOrder response")
        return ExchangeOrderResult(
            exchange_order_id=str(txids[0]),
            status=OrderStatus.SUBMITTED,
            raw_payload=json.dumps(result, sort_keys=True),
        )

    def get_order(self, exchange_order_id: str) -> ExchangeOrder:
        raw_order = self._fetch_order_payload(exchange_order_id)
        status = self._map_order_status(str(raw_order.get("status") or "open"))
        average_price = raw_order.get("avg_price") or raw_order.get("price") or None
        closed_at = None
        if raw_order.get("closetm") not in (None, ""):
            closed_at = datetime.fromtimestamp(float(raw_order["closetm"]), tz=timezone.utc)
        return ExchangeOrder(
            exchange_order_id=exchange_order_id,
            status=status,
            filled_quantity=Decimal(str(raw_order.get("vol_exec") or "0")),
            average_price=Decimal(str(average_price)) if average_price not in (None, "") else None,
            fee=Decimal(str(raw_order.get("fee") or "0")),
            closed_at=closed_at,
            raw_payload=json.dumps(raw_order, sort_keys=True),
        )

    def cancel_order(self, exchange_order_id: str) -> None:
        self._require_credentials()

    def list_open_orders(self, asset: str | None = None) -> list[ExchangeOpenOrder]:
        payload = self._post_private("/0/private/OpenOrders", {"trades": "true"}, action="list open orders")
        open_orders = payload.get("result", {}).get("open", {})
        orders: list[ExchangeOpenOrder] = []
        for exchange_order_id, order_payload in open_orders.items():
            descr = order_payload.get("descr", {})
            pair = str(descr.get("pair") or "")
            if asset and not self._pair_matches_asset(pair, asset):
                continue
            side = OrderType.BUY if str(descr.get("type", "buy")).lower() == "buy" else OrderType.SELL
            opened_at = None
            if order_payload.get("opentm") is not None:
                opened_at = datetime.fromtimestamp(float(order_payload["opentm"]), tz=timezone.utc)
            price = descr.get("price") or order_payload.get("price") or "0"
            orders.append(
                ExchangeOpenOrder(
                    exchange_order_id=str(exchange_order_id),
                    asset=pair or (asset or ""),
                    type=side,
                    status=str(order_payload.get("status") or "open").upper(),
                    price=Decimal(str(price)),
                    quantity=Decimal(str(order_payload.get("vol") or "0")),
                    filled_quantity=Decimal(str(order_payload.get("vol_exec") or "0")),
                    opened_at=opened_at,
                    description=str(descr) if descr else None,
                    raw_payload=json.dumps(order_payload, sort_keys=True),
                )
            )
        return orders

    def get_available_base_balance(self, asset: str) -> Decimal:
        asset_pair = self._get_asset_pair(asset)
        payload = self._post_private("/0/private/Balance", {}, action=f"get balance for {asset}")
        balances = payload.get("result", {})
        if not isinstance(balances, dict):
            raise KrakenApiError(f"get balance for {asset}", "invalid Balance response format")
        for candidate in self._balance_asset_candidates(asset_pair):
            raw_balance = balances.get(candidate)
            if raw_balance is not None:
                return Decimal(str(raw_balance))
        return Decimal("0")

    def _fetch_order_payload(self, exchange_order_id: str) -> dict[str, Any]:
        for path, action in (
            ("/0/private/QueryOrders", f"query order {exchange_order_id}"),
            ("/0/private/ClosedOrders", f"lookup closed order {exchange_order_id}"),
        ):
            payload = self._post_private(path, {"txid": exchange_order_id, "trades": "true"}, action=action)
            result = payload.get("result", {})
            if path.endswith("ClosedOrders"):
                order_payload = result.get("closed", {}).get(exchange_order_id)
            else:
                order_payload = result.get(exchange_order_id)
            if isinstance(order_payload, dict):
                return order_payload
        raise KrakenApiError(f"query order {exchange_order_id}", "order not found in Kraken QueryOrders or ClosedOrders")

    def _map_order_status(self, kraken_status: str) -> OrderStatus:
        mapping = {
            "pending": OrderStatus.SUBMITTED,
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
        }
        return mapping.get(kraken_status.lower(), OrderStatus.OPEN)

    def _normalize_order_params(self, asset: str, price: Decimal, quantity: Decimal) -> tuple[Decimal, Decimal]:
        asset_pair = self._get_asset_pair(asset)
        tick_size = Decimal(str(asset_pair.get("tick_size") or "0"))
        pair_decimals = int(asset_pair.get("pair_decimals") or 0)
        lot_decimals = int(asset_pair.get("lot_decimals") or 0)

        normalized_price = self._round_to_increment(
            price,
            tick_size if tick_size > 0 else self._places_quantum(pair_decimals),
            ROUND_DOWN,
        )
        normalized_quantity = self._quantize_down(quantity, self._places_quantum(lot_decimals))
        return normalized_price, normalized_quantity

    def _get_ticker_result(self, asset: str) -> dict[str, Any]:
        payload = self._get_public("/0/public/Ticker", {"pair": asset}, action=f"get ticker for {asset}")
        result = next(iter(payload["result"].values()))
        if not isinstance(result, dict):
            raise KrakenApiError(f"get ticker for {asset}", "invalid Ticker response format")
        return result

    def _get_asset_pair(self, asset: str) -> dict[str, Any]:
        if asset in self._asset_pair_cache:
            return self._asset_pair_cache[asset]

        payload = self._get_public("/0/public/AssetPairs", {"pair": asset}, action=f"get asset pair metadata for {asset}")
        pairs = payload.get("result", {})
        if not isinstance(pairs, dict) or not pairs:
            raise KrakenApiError(f"get asset pair metadata for {asset}", "pair metadata missing from AssetPairs response")

        for pair_payload in pairs.values():
            if not isinstance(pair_payload, dict):
                continue
            altname = str(pair_payload.get("altname") or "")
            wsname = str(pair_payload.get("wsname") or "")
            if asset in {altname, wsname}:
                self._asset_pair_cache[asset] = pair_payload
                return pair_payload

        first_pair = next(iter(pairs.values()))
        if not isinstance(first_pair, dict):
            raise KrakenApiError(f"get asset pair metadata for {asset}", "invalid AssetPairs response format")
        self._asset_pair_cache[asset] = first_pair
        return first_pair

    def _pair_matches_asset(self, pair: str, asset: str) -> bool:
        if pair == asset:
            return True
        normalized_pair = pair.replace("/", "").upper()
        normalized_asset = asset.replace("/", "").upper()
        if normalized_pair == normalized_asset:
            return True
        asset_pair = self._get_asset_pair(asset)
        altname = str(asset_pair.get("altname") or "")
        wsname = str(asset_pair.get("wsname") or "")
        return pair in {altname, wsname}

    def _balance_asset_candidates(self, asset_pair: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        base = str(asset_pair.get("base") or "")
        if base:
            candidates.append(base)
        wsname = str(asset_pair.get("wsname") or "")
        if "/" in wsname:
            candidates.append(wsname.split("/", 1)[0])
        altname = str(asset_pair.get("altname") or "")
        quote_hint = str(asset_pair.get("quote") or "")
        if altname and quote_hint and altname.endswith(quote_hint):
            candidates.append(altname[: -len(quote_hint)])
        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    def _places_quantum(self, places: int) -> Decimal:
        if places <= 0:
            return Decimal("1")
        return Decimal("1").scaleb(-places)

    def _quantize_down(self, value: Decimal, quantum: Decimal) -> Decimal:
        return value.quantize(quantum, rounding=ROUND_DOWN)

    def _round_to_increment(self, value: Decimal, increment: Decimal, rounding: str) -> Decimal:
        if increment <= 0:
            return value
        units = (value / increment).to_integral_value(rounding=rounding)
        return units * increment

    def _format_decimal(self, value: Decimal) -> str:
        return format(value, "f")

    def _map_interval(self, interval: str) -> int:
        mapping = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
        if interval not in mapping:
            raise ValueError(f"unsupported interval {interval}")
        return mapping[interval]

    def _require_credentials(self) -> None:
        self._resolve_credentials()

    def _resolve_credentials(self) -> tuple[str, str]:
        api_key = self.api_key or self._read_env(self.api_key_env)
        api_secret = self.api_secret or self._read_env(self.api_secret_env)
        if not api_key or not api_secret:
            raise KrakenApiError("authenticate", "Kraken credentials not configured")
        return api_key, api_secret

    def _read_env(self, configured_value: str | None) -> str | None:
        if not configured_value:
            return None
        return os.getenv(configured_value)

    def _get_public(self, path: str, params: dict[str, Any], action: str) -> dict[str, Any]:
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise KrakenApiError(action, str(exc)) from exc
        self._raise_for_kraken_errors(payload, action)
        return payload

    def _post_private(self, path: str, data: dict[str, Any], action: str) -> dict[str, Any]:
        api_key, api_secret = self._resolve_credentials()
        nonce = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        form_data = {**data, "nonce": nonce}
        encoded = urlencode(form_data)
        message = nonce.encode("utf-8") + encoded.encode("utf-8")
        sha256_hash = hashlib.sha256(message).digest()
        try:
            decoded_secret = base64.b64decode(api_secret)
        except binascii.Error as exc:
            raise KrakenApiError(action, "invalid Kraken API secret encoding") from exc
        signature = hmac.new(decoded_secret, path.encode("utf-8") + sha256_hash, hashlib.sha512).digest()
        headers = {
            "API-Key": api_key,
            "API-Sign": base64.b64encode(signature).decode("utf-8"),
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        try:
            response = self.client.post(path, content=encoded, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (ValueError, httpx.HTTPError) as exc:
            raise KrakenApiError(action, str(exc)) from exc
        self._raise_for_kraken_errors(payload, action)
        return payload

    def _raise_for_kraken_errors(self, payload: dict[str, Any], action: str) -> None:
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise KrakenApiError(action, "; ".join(str(error) for error in errors))
