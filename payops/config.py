from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://payops@localhost/payops"
    rabbitmq_url: str = "amqp://payops@localhost:5672/%2F"
    provider_url: str = "http://simulator:8001"
    provider_timeout: float = Field(default=1.0, gt=0, le=30)
    lease_seconds: int = Field(default=15, ge=5, le=300)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_seconds: float = Field(default=2, ge=0, le=60)
    metrics_port: int = 8002

    @model_validator(mode="after")
    def timeout_fits_lease(self):
        if self.lease_seconds <= self.provider_timeout + 2:
            raise ValueError("lease_seconds must exceed provider_timeout by more than 2 seconds")
        return self


@lru_cache
def settings():
    return Settings()
