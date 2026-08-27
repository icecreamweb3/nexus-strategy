"""策略与开单参数的单文件 INF 导入导出。"""
import configparser
import os
from dataclasses import fields
from typing import Tuple

from app.backtest.engine import OrderParams, StrategyParams


STRATEGY_PARAM_NAMES = (
    "volume_enabled", "volume_prev_n", "volume_mult",
    "single_change_enabled", "single_change_pct", "single_change_max_pct",
    "consecutive_enabled", "consecutive_count",
    "cum_change_enabled", "cum_klines", "cum_change_pct",
    "atr_enabled", "atr_period", "atr_min_pct", "atr_max_pct",
    "shadow_body_enabled", "shadow_body_upper",
)

ORDER_PARAM_NAMES = (
    "position_size", "initial_order_ratio", "fee_rate_pct", "stop_loss",
    "stop_cooldown", "take_profit", "direction", "add_interval_pct",
    "add_mult", "add_count", "max_hold_klines",
)


class ParamsFileError(ValueError):
    pass


def _stringify(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _coerce(raw: str, default):
    if isinstance(default, bool):
        normalized = raw.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        raise ParamsFileError(f"invalid boolean value: {raw}")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def _read_section(config, section: str, defaults, allowed_names):
    known_fields = {field.name for field in fields(defaults)}
    values = {}
    for name in allowed_names:
        if name not in known_fields or not config.has_option(section, name):
            continue
        values[name] = _coerce(config.get(section, name), getattr(defaults, name))
    return values


def save_params(path: str, strategy: StrategyParams, order: OrderParams):
    config = configparser.ConfigParser(interpolation=None)
    config["meta"] = {"format": "nexus-strategy-params", "version": "1"}
    config["strategy"] = {
        name: _stringify(getattr(strategy, name)) for name in STRATEGY_PARAM_NAMES
    }
    config["order"] = {
        name: _stringify(getattr(order, name)) for name in ORDER_PARAM_NAMES
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as output:
        config.write(output)


def load_params(path: str) -> Tuple[StrategyParams, OrderParams]:
    config = configparser.ConfigParser(interpolation=None)
    try:
        loaded = config.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise ParamsFileError(str(exc)) from exc
    if not loaded:
        raise ParamsFileError(f"parameter file not found: {path}")
    if not config.has_section("strategy") or not config.has_section("order"):
        raise ParamsFileError("missing [strategy] or [order] section")
    if config.get("meta", "format", fallback="") != "nexus-strategy-params":
        raise ParamsFileError("unsupported parameter file format")

    strategy_defaults = StrategyParams()
    order_defaults = OrderParams()
    try:
        strategy = StrategyParams(**_read_section(
            config, "strategy", strategy_defaults, STRATEGY_PARAM_NAMES))
        order = OrderParams(**_read_section(
            config, "order", order_defaults, ORDER_PARAM_NAMES))
    except (TypeError, ValueError) as exc:
        raise ParamsFileError(str(exc)) from exc
    if order.direction not in ("BOTH", "LONG", "SHORT"):
        raise ParamsFileError(f"invalid direction: {order.direction}")
    return strategy, order
