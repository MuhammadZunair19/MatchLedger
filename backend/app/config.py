from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = 'postgresql+psycopg://matchledger@localhost:5432/matchledger'
    app_origin: str = 'http://localhost:3000'
    cookie_secure: bool = False
    session_hours: int = Field(default=12, ge=1, le=168)
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
