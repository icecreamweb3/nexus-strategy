"""兼容正确拼写的 Binance WebSocket 框架入口。

迁移文件原名为 ``binance_websoket.py``，保留原文件避免影响既有引用。
"""

from app.client.binance_websoket import OrdersMonitor, get_proxy_config

__all__ = ["OrdersMonitor", "get_proxy_config"]
