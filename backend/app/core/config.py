from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HELM_", env_file=(".env", "../.env"), extra="ignore")

    secret_key: str
    database_url: str
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    sync_token: str
    demo_mode_seed: bool = False
    allow_registration: bool = False
    access_token_lifetime_seconds: int = 3600 * 24
    google_credentials_file: str = ""
    collect_interval_hours: int = 24
    collect_backfill_days: int = 480
    # JS-rendered pages fall back to the crawler-service /extract endpoint when both are set.
    crawler_url: str = ""
    crawler_api_key: str = ""
    # Keyword generator: Claude API for expansion, optional Google Ads for Keyword Planner volume.
    anthropic_api_key: str = ""
    keyword_model: str = "claude-opus-5-5"
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_customer_id: str = ""  # the Ads account used for Keyword Planner calls, digits only
    google_ads_login_customer_id: str = ""  # the manager account, if the customer is under one
    # Where `export_keyword_queue` writes `<slug>/keyword_queue.json`; empty disables file export.
    keyword_export_dir: str = ""
    keyword_geo: str = "2404"  # Google geo target constant; 2404 is Kenya
    keyword_language: str = "1000"  # Google language constant; 1000 is English
    google_ads_api_version: str = "v21"
    # Host headers the MCP server accepts (DNS-rebinding protection); `:*` allows any port.
    mcp_allowed_hosts: list[str] = ["mcp.billtoolbox.com", "localhost:*", "127.0.0.1:*"]
    # Notifications. Both channels are optional; with none configured, alert events are still recorded.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    report_recipients: str = ""  # comma-separated; the only addresses Helm ever mails
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_min_notify_hours: int = 6
    # Seconds between scheduler wake-ups; each job still runs on its own interval.
    scheduler_tick_seconds: int = 60


settings = Settings()
