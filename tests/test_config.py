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
