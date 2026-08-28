from datetime import datetime, timezone

from app.client.kline_stream import KlineStream
from app.client.live_gateway import BinanceLiveGateway


def _local_iso(timestamp_ms):
    return datetime.fromtimestamp(
        timestamp_ms / 1000, tz=timezone.utc,
    ).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def test_rest_kline_time_uses_iso_seconds():
    kline = BinanceLiveGateway.kline_from_rest(
        [1787906700000, "1", "2", "0.5", "1.5", "10"], 1)

    assert kline.open_time == _local_iso(1787906700000)


def test_websocket_kline_time_uses_same_iso_seconds():
    received = []
    stream = KlineStream(None, "BTCUSDT", "1m")
    stream.closed_kline.connect(received.append)

    stream._on_kline_closed({
        "t": 1787906760000,
        "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10",
    })

    assert received[0].open_time == _local_iso(1787906760000)


def test_rest_preheat_uses_binance_server_time():
    class Client:
        def get_kline_data(self, **_kwargs):
            return [
                [1000, "1", "2", "0.5", "1.5", "10", 1999],
                [2000, "1", "2", "0.5", "1.5", "10", 2999],
            ]

        def get_server_time(self):
            return datetime.fromtimestamp(2.5, tz=timezone.utc)

    gateway = object.__new__(BinanceLiveGateway)
    gateway.client = Client()

    klines = gateway.recent_closed_klines("BTCUSDT", "1m", 2)

    assert len(klines) == 1
    assert klines[0].open_time == _local_iso(1000)
