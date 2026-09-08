from app import config as config_module


def test_project_env_credentials_override_inherited_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BINANCE_API_KEY=project-key\n"
        "BINANCE_API_SECRET=project-secret\n"
        "BINANCE_TESTNET=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "APP_DIR", str(tmp_path))
    monkeypatch.setenv("BINANCE_API_KEY", "stale-shell-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "stale-shell-secret")

    config = config_module.load_config()

    assert config.api_key == "project-key"
    assert config.api_secret == "project-secret"
    assert config.testnet is False


def test_trade_detail_log_is_configurable(
        tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TRADE_DETAIL_LOG_ENABLED=true\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "APP_DIR", str(tmp_path))

    assert config_module.load_config().trade_detail_log_enabled is True

    env_file.write_text("TRADE_DETAIL_LOG_ENABLED=false\n", encoding="utf-8")

    assert config_module.load_config().trade_detail_log_enabled is False
