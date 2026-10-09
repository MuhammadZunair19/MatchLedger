from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = 'postgresql+psycopg://matchledger@localhost:5432/matchledger'
    app_origin: str = 'http://localhost:3000'
    cookie_secure: bool = False
    session_hours: int = Field(default=12, ge=1, le=168)
    redis_url: str = 'redis://localhost:6379/0'
    document_storage_path: str = '../private_documents'
    max_upload_size_mb: int = Field(default=20, ge=1, le=100)
    max_document_pages: int = Field(default=30, ge=1, le=100)
    max_image_pixels: int = Field(default=25000000, ge=1000000, le=50000000)
    document_parse_timeout: int = Field(default=30, ge=5, le=120)
    extraction_timeout: int = Field(default=900, ge=30, le=3600)
    max_extraction_attempts: int = Field(default=5, ge=1, le=20)
    ocr_device: str = 'cpu'
    ocr_languages: str = 'en,ar'
    ocr_dpi: int = Field(default=150, ge=72, le=250)
    date_order: str = 'DMY'
    supplier_aliases_path: str | None = None
    ollama_enabled: bool = False
    ollama_base_url: str = 'http://localhost:11434'
    ollama_model: str = 'llama3.2:3b'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
