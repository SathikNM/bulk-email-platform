"""Application settings loaded from environment variables / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Bulk Email Platform"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "postgresql+psycopg://bep:bep@localhost:5432/bep"
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "change-me"
    CREDENTIALS_ENCRYPTION_KEY: str = ""  # Fernet key for provider credentials
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    PUBLIC_TRACKING_BASE_URL: str = "http://localhost:8000"

    AWS_REGION: str = "eu-west-1"
    S3_ENDPOINT_URL: str | None = None
    S3_BUCKET: str = "bep-assets"


settings = Settings()
