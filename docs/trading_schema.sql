-- Nexus Strategy Live - SQLite schema
-- Runtime database: data/nexus_strategy.sqlite3

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- trades.config_id 的外键目标。当前仅保留最小配置快照结构。
CREATE TABLE IF NOT EXISTS strategy_configs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    config_json TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id           INTEGER REFERENCES positions (id),
    config_id             INTEGER REFERENCES strategy_configs (id),
    symbol                TEXT    NOT NULL,
    trade_type            TEXT    NOT NULL
                                  CHECK (trade_type IN (
                                      'OPEN', 'DCA', 'TAKE_PROFIT',
                                      'STOP_LOSS', 'LIQUIDATION'
                                  )),
    direction             TEXT    NOT NULL
                                  CHECK (direction IN ('LONG', 'SHORT')),
    price                 REAL    NOT NULL,
    quantity              REAL    NOT NULL,
    cost                  REAL    NOT NULL,
    fee                   REAL    NOT NULL,
    realized_pnl          REAL    DEFAULT 0.0,
    avg_entry_price_after REAL,
    position_size_after   REAL,
    balance_after         REAL,
    dca_count_after       INTEGER,
    mode                  TEXT    NOT NULL
                                  CHECK (mode IN ('BACKTEST', 'LIVE')),
    executed_at           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id                                  INTEGER   PRIMARY KEY AUTOINCREMENT,
    order_id                            TEXT,
    client_order_id                     TEXT,
    symbol                              TEXT      NOT NULL,
    side                                TEXT      NOT NULL,
    position_side                       TEXT,
    order_type                          TEXT      NOT NULL,
    quantity                            REAL      NOT NULL,
    price                               REAL,
    status                              TEXT      NOT NULL,
    filled_quantity                     REAL      DEFAULT 0,
    filled_price                        REAL,
    created_at                          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filled_at                           TIMESTAMP,
    expired_at                          TIMESTAMP,
    use_type                            TEXT      CHECK (use_type IN (
                                                       'OPEN', 'SL_CLOSE',
                                                       'TP_CLOSE', 'DCA'
                                                   )),
    action_type                         TEXT      CHECK (action_type IN (
                                                       'OPEN', 'TP', 'SL', 'DCA'
                                                   )),
    exchange                            TEXT      NOT NULL DEFAULT 'binance',
    stop_price                          REAL,
    algo_id                             TEXT,
    algo_client_id                      TEXT,
    filled_qty                          REAL      NOT NULL DEFAULT 0,
    avg_price                           REAL,
    realized_pnl                        REAL,
    commission                          REAL,
    commission_asset                    TEXT,
    trade_details_sync_attempts         INTEGER   NOT NULL DEFAULT 0,
    trade_details_sync_next_retry_at    TEXT,
    trade_details_sync_last_error       TEXT,
    trade_direction                     TEXT,
    position_mode                       TEXT      NOT NULL DEFAULT 'UNKNOWN',
    reduce_only                         INTEGER   NOT NULL DEFAULT 0,
    post_only                           INTEGER   NOT NULL DEFAULT 0,
    position_id                         INTEGER,
    order_category                      TEXT      NOT NULL DEFAULT 'Basic',
    error_message                       TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange          TEXT    NOT NULL DEFAULT 'binance',
    symbol            TEXT    NOT NULL,
    position_side     TEXT    NOT NULL DEFAULT 'BOTH'
                            CHECK (position_side IN ('LONG', 'SHORT', 'BOTH')),
    position_mode     TEXT    NOT NULL DEFAULT 'UNKNOWN',
    status            TEXT    NOT NULL DEFAULT 'OPEN'
                            CHECK (status IN ('OPEN', 'CLOSE')),
    quantity          REAL    NOT NULL DEFAULT 0,
    avg_entry_price   REAL,
    liquidation_price REAL,
    tp_price          REAL,
    sl_price          REAL,
    unrealized_pnl    REAL,
    realized_pnl      REAL    NOT NULL DEFAULT 0,
    leverage          INTEGER NOT NULL DEFAULT 1,
    margin_type       TEXT    NOT NULL DEFAULT 'CROSS'
                            CHECK (margin_type IN ('ISOLATED', 'CROSS')),
    updated_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT    NOT NULL,
    side             TEXT    NOT NULL DEFAULT 'LONG',
    position_mode    TEXT    NOT NULL DEFAULT 'UNKNOWN',
    entry_price      REAL    NOT NULL,
    close_price      REAL    NOT NULL,
    tp_price         REAL,
    sl_price         REAL,
    close_order_id   TEXT,
    quantity         REAL    NOT NULL,
    realized_pnl     REAL    NOT NULL DEFAULT 0.0,
    commission       REAL    NOT NULL DEFAULT 0.0,
    commission_asset TEXT,
    position_id      INTEGER,
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 防止同一个 Binance FILLED 事件重复生成 trades 记录。
CREATE TABLE IF NOT EXISTS order_trade_links (
    order_id TEXT    PRIMARY KEY,
    trade_id INTEGER NOT NULL REFERENCES trades (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_exchange_order_id
    ON orders (exchange, order_id)
    WHERE order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_exchange_symbol_side
    ON positions (exchange, symbol, position_side);

CREATE INDEX IF NOT EXISTS ix_orders_status_updated
    ON orders (status, updated_at);

CREATE INDEX IF NOT EXISTS ix_trades_mode_time
    ON trades (mode, executed_at);
