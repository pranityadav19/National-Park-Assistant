from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "National Parks Assistant API"
    debug: bool = True
    nps_api_key: str = ""
    request_timeout_seconds: int = 20
    user_agent: str = "NationalParksAssistantBot/1.0"
    data_file: str = "/app/data/parks_cache.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
