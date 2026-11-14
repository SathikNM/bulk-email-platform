"""Application settings loaded from environment variables / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Bulk Email Platform"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | test | production

    DATABASE_URL: str = "postgresql+psycopg://bep:bep@localhost:5432/bep"
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "change-me-in-production-0123456789abcdef"
    CREDENTIALS_ENCRYPTION_KEY: str = ""  # Fernet key; derived from SECRET_KEY if empty (dev only)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    COOKIE_SECURE: bool = False

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    PUBLIC_BASE_URL: str = "http://localhost:8000"  # tracking pixel / click / unsubscribe links
    APP_BASE_URL: str = "http://localhost:3000"

    # Storage: "local" (shared volume) or "s3" (AWS S3 / SeaweedFS / any S3-compatible)
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_DIR: str = "./data/uploads"
    S3_ENDPOINT_URL: str | None = None
    S3_BUCKET: str = "bep-assets"
    S3_PUBLIC_BASE_URL: str | None = None
    AWS_REGION: str = "eu-west-1"
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

    # Celery
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # Sending defaults
    SEND_BATCH_SIZE: int = 50
    SEND_MAX_ATTEMPTS: int = 5
    SES_WEBHOOK_VERIFY_SIGNATURE: bool = True

    # AI assistant (Anthropic Messages API). Empty key = feature disabled (HTTP 503).
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-5-5"
    LLM_API_URL: str = "https://api.anthropic.com/v1/messages"

    # Security
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    MAX_UPLOAD_MB: int = 25


settings = Settings()
