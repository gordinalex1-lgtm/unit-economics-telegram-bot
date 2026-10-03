from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    openrouter_api_key: str
    openrouter_model: str = "google/gemini-3.8-flash"
    database_url: str
    webhook_base_url: str
    webhook_secret: str
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
