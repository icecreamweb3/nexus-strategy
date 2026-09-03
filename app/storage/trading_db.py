"""SQLite 实盘订单、成交与持仓存储。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.config import APP_DIR


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS strategy_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER REFERENCES positions (id),
    config_id INTEGER REFERENCES strategy_configs (id),
    symbol TEXT NOT NULL,
    trade_type TEXT NOT NULL CHECK (trade_type IN
        ('OPEN', 'DCA', 'TAKE_PROFIT', 'STOP_LOSS', 'LIQUIDATION')),
    direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    cost REAL NOT NULL,
    fee REAL NOT NULL,
    realized_pnl REAL DEFAULT 0.0,
    avg_entry_price_after REAL,
    position_size_after REAL,
    balance_after REAL,
    dca_count_after INTEGER,
    mode TEXT NOT NULL CHECK (mode IN ('BACKTEST', 'LIVE')),
    executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    client_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    position_side TEXT,
    order_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    filled_quantity REAL DEFAULT 0,
    filled_price REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP,
    expired_at TIMESTAMP,
    use_type TEXT CHECK (use_type IN ('OPEN', 'SL_CLOSE', 'TP_CLOSE', 'DCA')),
    action_type TEXT CHECK (action_type IN ('OPEN', 'TP', 'SL', 'DCA')),
    exchange TEXT NOT NULL DEFAULT 'binance',
    stop_price REAL,
    algo_id TEXT,
    algo_client_id TEXT,
    filled_qty REAL NOT NULL DEFAULT 0,
    avg_price REAL,
    realized_pnl REAL,
    commission REAL,
    commission_asset TEXT,
    trade_details_sync_attempts INTEGER NOT NULL DEFAULT 0,
    trade_details_sync_next_retry_at TEXT,
    trade_details_sync_last_error TEXT,
    trade_direction TEXT,
    position_mode TEXT NOT NULL DEFAULT 'UNKNOWN',
    reduce_only INTEGER NOT NULL DEFAULT 0,
    post_only INTEGER NOT NULL DEFAULT 0,
    position_id INTEGER,
    order_category TEXT NOT NULL DEFAULT 'Basic',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL DEFAULT 'binance',
    symbol TEXT NOT NULL,
    position_side TEXT NOT NULL DEFAULT 'BOTH'
        CHECK (position_side IN ('LONG', 'SHORT', 'BOTH')),
    position_mode TEXT NOT NULL DEFAULT 'UNKNOWN',
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSE')),
    quantity REAL NOT NULL DEFAULT 0,
    avg_entry_price REAL,
    liquidation_price REAL,
    tp_price REAL,
    sl_price REAL,
    unrealized_pnl REAL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    leverage INTEGER NOT NULL DEFAULT 1,
    margin_type TEXT NOT NULL DEFAULT 'CROSS'
        CHECK (margin_type IN ('ISOLATED', 'CROSS')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL DEFAULT 'LONG',
    position_mode TEXT NOT NULL DEFAULT 'UNKNOWN',
    entry_price REAL NOT NULL,
    close_price REAL NOT NULL,
    tp_price REAL,
    sl_price REAL,
    close_order_id TEXT,
    quantity REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0.0,
    commission REAL NOT NULL DEFAULT 0.0,
    commission_asset TEXT,
    position_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_trade_links (
    order_id TEXT PRIMARY KEY,
    trade_id INTEGER NOT NULL REFERENCES trades (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_exchange_order_id
ON orders(exchange, order_id) WHERE order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_exchange_symbol_side
ON positions(exchange, symbol, position_side);
CREATE INDEX IF NOT EXISTS ix_orders_status_updated ON orders(status, updated_at);
CREATE INDEX IF NOT EXISTS ix_trades_mode_time ON trades(mode, executed_at);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _event_time(value) -> str:
    if value in (None, ""):
        return _utc_now()
    try:
        return datetime.fromtimestamp(
            float(value) / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return str(value)


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TradingDatabase:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(APP_DIR, "data", "nexus_strategy.sqlite3")
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self):
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @staticmethod
    def _order_values(order: dict) -> dict:
        status = str(order.get("X", order.get("status", "NEW"))).upper()
        side = str(order.get("S", order.get("side", ""))).upper()
        position_side = str(order.get(
            "ps", order.get("positionSide", "BOTH")) or "BOTH").upper()
        direction = position_side if position_side in ("LONG", "SHORT") \
            else ("LONG" if side == "BUY" else "SHORT")
        reduce_only = bool(order.get("R", order.get("reduceOnly", False)))
        order_type = str(order.get("o", order.get("type", "MARKET"))).upper()
        if reduce_only and position_side == "BOTH":
            direction = "LONG" if side == "SELL" else "SHORT"
        inferred_action = "SL" if "STOP" in order_type \
            else ("TP" if "TAKE_PROFIT" in order_type else "OPEN")
        action_type = order.get("action_type", inferred_action)
        use_type = order.get("use_type", {
            "SL": "SL_CLOSE", "TP": "TP_CLOSE", "DCA": "DCA",
        }.get(action_type, "OPEN"))
        filled_qty = _float(order.get("z", order.get(
            "executedQty", order.get("filled_qty", 0))))
        avg_price = _float(order.get("ap", order.get("avgPrice", 0)))
        event_at = _event_time(order.get("T", order.get(
            "updateTime", order.get("transactTime"))))
        return {
            "order_id": str(order.get("i", order.get("orderId", ""))) or None,
            "client_order_id": order.get("c", order.get("clientOrderId")),
            "symbol": str(order.get("s", order.get("symbol", ""))).upper(),
            "side": side,
            "position_side": position_side,
            "order_type": order_type,
            "quantity": _float(order.get("q", order.get("origQty", 0))),
            "price": _float(order.get("p", order.get("price", 0))),
            "status": status,
            "filled_quantity": filled_qty,
            "filled_price": avg_price,
            "updated_at": event_at,
            "filled_at": event_at if status == "FILLED" else None,
            "expired_at": event_at if status in ("EXPIRED", "CANCELED") else None,
            "use_type": use_type,
            "action_type": action_type,
            "stop_price": _float(order.get("sp", order.get("stopPrice", 0))) or None,
            "algo_id": order.get("aid", order.get("algoId")),
            "algo_client_id": order.get("caid", order.get("clientAlgoId")),
            "filled_qty": filled_qty,
            "avg_price": avg_price,
            "realized_pnl": _float(order.get("rp", order.get("realizedPnl", 0))),
            "commission": _float(order.get(
                "n", order.get("commission", order.get("fee", 0)))),
            "commission_asset": order.get("N", order.get("commissionAsset")),
            "trade_direction": direction,
            "position_mode": "HEDGE" if position_side in ("LONG", "SHORT") else "ONE_WAY",
            "reduce_only": int(reduce_only),
            "post_only": int(bool(order.get("postOnly", False))),
            "error_message": order.get("error_message"),
        }

    def upsert_order(self, order: dict) -> tuple[dict, bool]:
        values = self._order_values(order)
        if not values["order_id"] or not values["symbol"] or not values["side"]:
            raise ValueError("订单事件缺少 order_id/symbol/side")
        columns = tuple(values)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(
            f"{name}=excluded.{name}" for name in columns if name != "order_id")
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT status, action_type, use_type, trade_direction, reduce_only "
                "FROM orders WHERE exchange='binance' AND order_id=?",
                (values["order_id"],),
            ).fetchone()
            # Binance's regular LIMIT TP update has no semantic TP marker. Keep
            # the classification saved when the protection order was created.
            if previous is not None:
                if previous["action_type"] in ("TP", "SL", "DCA") \
                        and values["action_type"] == "OPEN":
                    values["action_type"] = previous["action_type"]
                    values["use_type"] = previous["use_type"]
                    values["trade_direction"] = previous["trade_direction"]
                if previous["reduce_only"]:
                    values["reduce_only"] = 1
            connection.execute(
                f"INSERT INTO orders ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(exchange, order_id) WHERE order_id IS NOT NULL "
                f"DO UPDATE SET {updates}",
                tuple(values[name] for name in columns),
            )
        newly_filled = values["status"] == "FILLED" \
            and (previous is None or previous["status"] != "FILLED")
        return values, newly_filled

    def record_filled_trade(self, order: dict, balance_after: float | None = None):
        values = self._order_values(order)
        if values["status"] != "FILLED" or not values["order_id"]:
            return None
        with self._connect() as connection:
            stored_order = connection.execute(
                "SELECT action_type, trade_direction FROM orders "
                "WHERE exchange='binance' AND order_id=?",
                (values["order_id"],),
            ).fetchone()
            if stored_order is not None:
                values["action_type"] = stored_order["action_type"]
                values["trade_direction"] = stored_order["trade_direction"]
            direction = values["trade_direction"]
            action = values["action_type"]
            trade_type = {
                "DCA": "DCA", "TP": "TAKE_PROFIT", "SL": "STOP_LOSS",
            }.get(action, "OPEN")
            price = values["avg_price"] or values["price"]
            quantity = values["filled_qty"] or values["quantity"]
            linked = connection.execute(
                "SELECT trade_id FROM order_trade_links WHERE order_id=?",
                (values["order_id"],),
            ).fetchone()
            if linked:
                connection.execute(
                    "UPDATE trades SET price=?, quantity=?, cost=?, fee=?, "
                    "realized_pnl=?, balance_after=COALESCE(?, balance_after), "
                    "executed_at=? WHERE id=?",
                    (price, quantity, price * quantity, values["commission"],
                     values["realized_pnl"], balance_after,
                     values["updated_at"], linked["trade_id"]),
                )
                return linked["trade_id"]
            position = connection.execute(
                "SELECT id, avg_entry_price, quantity FROM positions "
                "WHERE exchange='binance' AND symbol=? AND position_side=?",
                (values["symbol"], direction),
            ).fetchone()
            cursor = connection.execute(
                "INSERT INTO trades (position_id, symbol, trade_type, direction, "
                "price, quantity, cost, fee, realized_pnl, avg_entry_price_after, "
                "position_size_after, balance_after, mode, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LIVE', ?)",
                (
                    position["id"] if position else None,
                    values["symbol"], trade_type, direction, price, quantity,
                    price * quantity, values["commission"], values["realized_pnl"],
                    position["avg_entry_price"] if position else price,
                    position["quantity"] if position else quantity,
                    balance_after, values["updated_at"],
                ),
            )
            trade_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO order_trade_links(order_id, trade_id) VALUES (?, ?)",
                (values["order_id"], trade_id),
            )
            return trade_id

    def sync_positions(self, positions: Iterable[dict],
                       symbols: Optional[Iterable[str]] = None):
        """同步当前仓位；symbols 用于限定可被判定为已消失的交易对。"""
        now = _utc_now()
        positions = list(positions)
        scope = {str(symbol).upper() for symbol in symbols} \
            if symbols is not None else None
        seen: set[tuple[str, str]] = set()
        with self._connect() as connection:
            for raw in positions:
                symbol = str(raw.get("symbol", "")).upper()
                amount = _float(raw.get("positionAmt", raw.get("quantity", 0)))
                if not symbol or amount == 0:
                    continue
                raw_side = str(raw.get("positionSide", "") or "").upper()
                side = raw_side if raw_side in ("LONG", "SHORT") \
                    else ("LONG" if amount > 0 else "SHORT")
                seen.add((symbol, side))
                margin_type = str(raw.get("marginType", "CROSS") or "CROSS").upper()
                if margin_type not in ("ISOLATED", "CROSS"):
                    margin_type = "CROSS"
                values = (
                    "binance", symbol, side,
                    str(raw.get("positionMode", "UNKNOWN") or "UNKNOWN").upper(),
                    abs(amount), _float(raw.get("entryPrice", raw.get("avgEntryPrice", 0))),
                    _float(raw.get("liquidationPrice", 0)) or None,
                    _float(raw.get("tpPrice", 0)) or None,
                    _float(raw.get("slPrice", 0)) or None,
                    _float(raw.get("unrealizedProfit", raw.get("unRealizedProfit", 0))),
                    _float(raw.get("realizedPnl", 0)),
                    int(_float(raw.get("leverage", 1), 1)), margin_type, now,
                )
                connection.execute(
                    "INSERT INTO positions (exchange, symbol, position_side, "
                    "position_mode, status, quantity, avg_entry_price, liquidation_price, "
                    "tp_price, sl_price, unrealized_pnl, realized_pnl, leverage, "
                    "margin_type, updated_at) VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(exchange, symbol, position_side) DO UPDATE SET "
                    "position_mode=excluded.position_mode, status='OPEN', "
                    "quantity=excluded.quantity, avg_entry_price=excluded.avg_entry_price, "
                    "liquidation_price=excluded.liquidation_price, "
                    "tp_price=COALESCE(excluded.tp_price, positions.tp_price), "
                    "sl_price=COALESCE(excluded.sl_price, positions.sl_price), "
                    "unrealized_pnl=excluded.unrealized_pnl, "
                    "realized_pnl=excluded.realized_pnl, leverage=excluded.leverage, "
                    "margin_type=excluded.margin_type, updated_at=excluded.updated_at",
                    values,
                )

            open_rows = connection.execute(
                "SELECT * FROM positions WHERE status='OPEN'").fetchall()
            for row in open_rows:
                if scope is not None and row["symbol"] not in scope:
                    continue
                if (row["symbol"], row["position_side"]) in seen:
                    continue
                close_order = connection.execute(
                    "SELECT * FROM orders WHERE symbol=? AND trade_direction=? "
                    "AND status='FILLED' AND (reduce_only=1 OR action_type IN ('TP','SL')) "
                    "ORDER BY filled_at DESC, updated_at DESC LIMIT 1",
                    (row["symbol"], row["position_side"]),
                ).fetchone()
                close_order_id = close_order["order_id"] if close_order else None
                existing_history = connection.execute(
                    "SELECT id FROM positions_history WHERE symbol=? "
                    "AND close_order_id=? ORDER BY id DESC LIMIT 1",
                    (row["symbol"], close_order_id),
                ).fetchone() if close_order_id else None
                if existing_history:
                    # userTrades may have already created the accurate cycle.
                    # Only attach locally known protection/position metadata.
                    connection.execute(
                        "UPDATE positions_history SET tp_price=COALESCE(tp_price, ?), "
                        "sl_price=COALESCE(sl_price, ?), "
                        "position_id=COALESCE(position_id, ?) WHERE id=?",
                        (row["tp_price"], row["sl_price"], row["id"],
                         existing_history["id"]),
                    )
                else:
                    connection.execute(
                        "INSERT INTO positions_history (symbol, side, position_mode, "
                        "entry_price, close_price, tp_price, sl_price, close_order_id, "
                        "quantity, realized_pnl, commission, commission_asset, position_id, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["symbol"], row["position_side"], row["position_mode"],
                            row["avg_entry_price"] or 0,
                            (close_order["avg_price"] or close_order["price"])
                            if close_order else (row["avg_entry_price"] or 0),
                            row["tp_price"], row["sl_price"], close_order_id,
                            row["quantity"],
                            close_order["realized_pnl"] if close_order else row["realized_pnl"],
                            close_order["commission"] if close_order else 0,
                            close_order["commission_asset"] if close_order else None,
                            row["id"], row["updated_at"], now,
                        ),
                    )
                connection.execute(
                    "UPDATE positions SET status='CLOSE', quantity=0, updated_at=? WHERE id=?",
                    (now, row["id"]),
                )

    def sync_user_trades(self, user_trades: Iterable[dict]) -> int:
        """用 Binance userTrades 补全订单并重建完全结束的仓位周期。

        返回本次识别出的完整仓位周期数量。重复同步会更新同一条历史记录，
        不会再次插入。
        """
        rows = sorted(
            (dict(item) for item in user_trades),
            key=lambda item: (_float(item.get("time")), _float(item.get("id"))),
        )
        self._update_orders_from_user_trades(rows)

        states: dict[tuple[str, str], dict] = {}
        completed: list[dict] = []
        for trade in rows:
            symbol = str(trade.get("symbol", "")).upper()
            side = str(trade.get("side", "")).upper()
            raw_position_side = str(
                trade.get("positionSide", "BOTH") or "BOTH").upper()
            quantity = abs(_float(trade.get("qty")))
            price = _float(trade.get("price"))
            if not symbol or side not in ("BUY", "SELL") \
                    or quantity <= 0 or price <= 0:
                continue

            key = (symbol, raw_position_side)
            state = states.get(key)
            if raw_position_side == "LONG":
                direction, is_open = "LONG", side == "BUY"
            elif raw_position_side == "SHORT":
                direction, is_open = "SHORT", side == "SELL"
            elif state is None or state["remaining"] <= 1e-12:
                direction, is_open = ("LONG", True) if side == "BUY" \
                    else ("SHORT", True)
            else:
                direction = state["direction"]
                is_open = side == ("BUY" if direction == "LONG" else "SELL")

            if state is None or state["remaining"] <= 1e-12:
                if not is_open:
                    continue
                state = {
                    "symbol": symbol, "direction": direction,
                    "position_mode": "ONE_WAY" if raw_position_side == "BOTH" else "HEDGE",
                    "remaining": 0.0, "entry_qty": 0.0,
                    "entry_value": 0.0, "exit_qty": 0.0,
                    "exit_value": 0.0, "realized_pnl": 0.0,
                    "commission": 0.0, "commission_asset": None,
                    "created_at": _event_time(trade.get("time")),
                    "close_order_id": None,
                }
                states[key] = state

            state["commission"] += _float(trade.get("commission"))
            state["commission_asset"] = trade.get("commissionAsset") \
                or state["commission_asset"]
            state["realized_pnl"] += _float(trade.get("realizedPnl"))
            if is_open:
                state["remaining"] += quantity
                state["entry_qty"] += quantity
                state["entry_value"] += quantity * price
                continue

            close_quantity = min(quantity, state["remaining"])
            state["remaining"] -= close_quantity
            state["exit_qty"] += close_quantity
            state["exit_value"] += close_quantity * price
            state["close_order_id"] = str(trade.get("orderId", "")) or None
            state["updated_at"] = _event_time(trade.get("time"))
            if state["remaining"] <= 1e-12 and state["exit_qty"] > 0:
                completed.append(dict(state))
                states.pop(key, None)

        with self._connect() as connection:
            for cycle in completed:
                entry_price = cycle["entry_value"] / cycle["entry_qty"]
                close_price = cycle["exit_value"] / cycle["exit_qty"]
                existing = connection.execute(
                    "SELECT id FROM positions_history WHERE symbol=? "
                    "AND close_order_id=? ORDER BY id DESC LIMIT 1",
                    (cycle["symbol"], cycle["close_order_id"]),
                ).fetchone()
                values = (
                    cycle["direction"], cycle["position_mode"], entry_price,
                    close_price, cycle["entry_qty"], cycle["realized_pnl"],
                    cycle["commission"], cycle["commission_asset"],
                    cycle["created_at"], cycle["updated_at"],
                )
                if existing:
                    connection.execute(
                        "UPDATE positions_history SET side=?, position_mode=?, "
                        "entry_price=?, close_price=?, quantity=?, realized_pnl=?, "
                        "commission=?, commission_asset=?, created_at=?, updated_at=? "
                        "WHERE id=?",
                        values + (existing["id"],),
                    )
                else:
                    connection.execute(
                        "INSERT INTO positions_history (symbol, side, position_mode, "
                        "entry_price, close_price, close_order_id, quantity, "
                        "realized_pnl, commission, commission_asset, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cycle["symbol"], cycle["direction"], cycle["position_mode"],
                         entry_price, close_price, cycle["close_order_id"],
                         cycle["entry_qty"], cycle["realized_pnl"],
                         cycle["commission"], cycle["commission_asset"],
                         cycle["created_at"], cycle["updated_at"]),
                    )
        return len(completed)

    def _update_orders_from_user_trades(self, rows: list[dict]) -> None:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for trade in rows:
            symbol = str(trade.get("symbol", "")).upper()
            order_id = str(trade.get("orderId", ""))
            if symbol and order_id:
                grouped.setdefault((symbol, order_id), []).append(trade)
        with self._connect() as connection:
            for (symbol, order_id), fills in grouped.items():
                quantity = sum(abs(_float(fill.get("qty"))) for fill in fills)
                if quantity <= 0:
                    continue
                avg_price = sum(
                    abs(_float(fill.get("qty"))) * _float(fill.get("price"))
                    for fill in fills) / quantity
                realized_pnl = sum(_float(fill.get("realizedPnl")) for fill in fills)
                commission = sum(_float(fill.get("commission")) for fill in fills)
                commission_asset = next((
                    fill.get("commissionAsset") for fill in reversed(fills)
                    if fill.get("commissionAsset")), None)
                updated_at = _event_time(max(
                    (_float(fill.get("time")) for fill in fills), default=0))
                connection.execute(
                    "UPDATE orders SET filled_quantity=?, filled_qty=?, "
                    "filled_price=?, avg_price=?, realized_pnl=?, commission=?, "
                    "commission_asset=?, updated_at=? "
                    "WHERE exchange='binance' AND symbol=? AND order_id=?",
                    (quantity, quantity, avg_price, avg_price, realized_pnl,
                     commission, commission_asset, updated_at, symbol, order_id),
                )
                linked = connection.execute(
                    "SELECT trade_id FROM order_trade_links WHERE order_id=?",
                    (order_id,),
                ).fetchone()
                if linked:
                    connection.execute(
                        "UPDATE trades SET price=?, quantity=?, cost=?, fee=?, "
                        "realized_pnl=?, executed_at=? WHERE id=?",
                        (avg_price, quantity, avg_price * quantity, commission,
                         realized_pnl, updated_at, linked["trade_id"]),
                    )

    def set_position_protection(self, symbol: str, position_side: str,
                                tp_price=None, sl_price=None) -> None:
        """保存已提交保护单的触发价。"""
        with self._connect() as connection:
            connection.execute(
                "UPDATE positions SET tp_price=?, sl_price=?, updated_at=? "
                "WHERE exchange='binance' AND symbol=? AND position_side=? "
                "AND status='OPEN'",
                (tp_price, sl_price, _utc_now(), symbol.upper(),
                 position_side.upper()),
            )

    def rows(self, query: str, params: tuple = ()) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def current_positions(self) -> list[dict]:
        return self.rows(
            "SELECT * FROM positions WHERE status='OPEN' ORDER BY updated_at DESC")

    def position_history(self, limit: int = 10) -> list[dict]:
        return self.rows(
            "SELECT * FROM positions_history ORDER BY updated_at DESC LIMIT ?",
            (max(int(limit), 1),))

    def current_orders(self) -> list[dict]:
        return self.rows(
            "SELECT * FROM orders WHERE status IN ('NEW','PARTIALLY_FILLED') "
            "ORDER BY updated_at DESC")

    def order_history(self) -> list[dict]:
        return self.rows(
            "SELECT * FROM orders WHERE status NOT IN ('NEW','PARTIALLY_FILLED') "
            "ORDER BY updated_at DESC")
