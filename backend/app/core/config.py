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


settings = Settings()
