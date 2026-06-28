from decimal import Decimal

import pytest

from kraken_bot.domain.enums import OrderStatus, OrderType
from kraken_bot.exchange.kraken_adapter import KrakenAdapter, KrakenApiError


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class RecordingClient:
    def __init__(self, post_payload, get_payload=None):
        self.post_payload = post_payload
        self.get_payload = get_payload or {"error": [], "result": {}}
        self.last_path = None
        self.last_content = None
        self.last_headers = None

    def post(self, path, content, headers):
        self.last_path = path
        self.last_content = content
        self.last_headers = headers
        return DummyResponse(self.post_payload)

    def get(self, path, params):
        self.last_get_path = path
        self.last_get_params = params
        return DummyResponse(self.get_payload)


def test_place_limit_order_uses_signed_add_order() -> None:
    adapter = KrakenAdapter(
        base_url="https://api.kraken.com",
        api_key_env=None,
        api_secret_env=None,
        api_key="test-key",
        api_secret="dGVzdC1zZWNyZXQ=",
    )
    client = RecordingClient(
        {"error": [], "result": {"descr": {"order": "buy 0.06 SOLUSD @ limit 72.25"}, "txid": ["OID123"]}},
        {
            "error": [],
            "result": {
                "SOLUSD": {
                    "altname": "SOLUSD",
                    "wsname": "SOL/USD",
                    "pair_decimals": 2,
                    "lot_decimals": 8,
                    "tick_size": "0.01",
                }
            },
        },
    )
    adapter.client = client

    result = adapter.place_limit_order("SOL/USD", OrderType.BUY, Decimal("72.25612"), Decimal("0.06"), True)

    assert result.exchange_order_id == "OID123"
    assert result.status is OrderStatus.SUBMITTED
    assert client.last_path == "/0/private/AddOrder"
    assert client.last_get_path == "/0/public/AssetPairs"
    assert "pair=SOL%2FUSD" in client.last_content
    assert "type=buy" in client.last_content
    assert "ordertype=limit" in client.last_content
    assert "price=72.25" in client.last_content
    assert "volume=0.06" in client.last_content
    assert "oflags=post" in client.last_content
    assert client.last_headers["API-Key"] == "test-key"
    assert "API-Sign" in client.last_headers


def test_get_quote_reads_best_bid_ask_and_tick_size() -> None:
    adapter = KrakenAdapter(
        base_url="https://api.kraken.com",
        api_key_env=None,
        api_secret_env=None,
        api_key="test-key",
        api_secret="dGVzdC1zZWNyZXQ=",
    )
    client = RecordingClient(
        {"error": [], "result": {}},
        {
            "error": [],
            "result": {
                "SOLUSD": {
                    "a": ["72.21", "1", "1.000"],
                    "b": ["72.19", "1", "1.000"],
                    "c": ["72.20", "0.5"],
                }
            },
        },
    )
    asset_pair_payload = {
        "error": [],
        "result": {
            "SOLUSD": {
                "altname": "SOLUSD",
                "wsname": "SOL/USD",
                "pair_decimals": 2,
                "lot_decimals": 8,
                "tick_size": "0.01",
            }
        },
    }
    get_payloads = [client.get_payload, asset_pair_payload]

    def get(path, params):
        client.last_get_path = path
        client.last_get_params = params
        return DummyResponse(get_payloads.pop(0))

    client.get = get
    adapter.client = client

    quote = adapter.get_quote("SOL/USD")

    assert quote.bid == Decimal("72.19")
    assert quote.ask == Decimal("72.21")
    assert quote.price_increment == Decimal("0.01")


def test_place_limit_order_rejects_missing_txid() -> None:
    adapter = KrakenAdapter(
        base_url="https://api.kraken.com",
        api_key_env=None,
        api_secret_env=None,
        api_key="test-key",
        api_secret="dGVzdC1zZWNyZXQ=",
    )
    adapter.client = RecordingClient(
        {"error": [], "result": {"descr": {"order": "buy"}}},
        {
            "error": [],
            "result": {
                "SOLUSD": {
                    "altname": "SOLUSD",
                    "wsname": "SOL/USD",
                    "pair_decimals": 2,
                    "lot_decimals": 8,
                    "tick_size": "0.01",
                }
            },
        },
    )

    with pytest.raises(KrakenApiError) as exc_info:
        adapter.place_limit_order("SOL/USD", OrderType.BUY, Decimal("72.25"), Decimal("0.06"), True)

    assert "missing txid" in str(exc_info.value)


def test_get_order_reads_closed_canceled_order() -> None:
    adapter = KrakenAdapter(
        base_url="https://api.kraken.com",
        api_key_env=None,
        api_secret_env=None,
        api_key="test-key",
        api_secret="dGVzdC1zZWNyZXQ=",
    )
    client = RecordingClient(
        {"error": [], "result": {"closed": {"OID123": {"status": "canceled", "vol_exec": "0.00000000", "fee": "0.00000"}}}},
        {"error": [], "result": {}},
    )
    post_payloads = [
        {"error": [], "result": {}},
        {"error": [], "result": {"closed": {"OID123": {"status": "canceled", "vol_exec": "0.00000000", "fee": "0.00000"}}}},
    ]

    def post(path, content, headers):
        client.last_path = path
        client.last_content = content
        client.last_headers = headers
        return DummyResponse(post_payloads.pop(0))

    client.post = post
    adapter.client = client

    order = adapter.get_order("OID123")

    assert order.exchange_order_id == "OID123"
    assert order.status is OrderStatus.CANCELLED
    assert order.filled_quantity == Decimal("0")


def test_get_order_uses_price_when_avg_price_missing() -> None:
    adapter = KrakenAdapter(
        base_url="https://api.kraken.com",
        api_key_env=None,
        api_secret_env=None,
        api_key="test-key",
        api_secret="dGVzdC1zZWNyZXQ=",
    )
    client = RecordingClient({"error": [], "result": {}}, {"error": [], "result": {}})
    post_payloads = [
        {"error": [], "result": {"OID123": {"status": "closed", "vol_exec": "0.06000000", "fee": "0.01065", "price": "71.03", "closetm": 1782596930.232203}}},
    ]

    def post(path, content, headers):
        client.last_path = path
        client.last_content = content
        client.last_headers = headers
        return DummyResponse(post_payloads.pop(0))

    client.post = post
    adapter.client = client

    order = adapter.get_order("OID123")

    assert order.status is OrderStatus.FILLED
    assert order.average_price == Decimal("71.03")
