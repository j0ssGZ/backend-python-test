import os

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    database_path: str = "notifications.sqlite3"
    backlog_capacity: int = Field(default=10_000, ge=1)
    workers_enabled: bool = True
    provider_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:3001")
    provider_api_key: SecretStr | None = None
    worker_count: int = Field(default=4, ge=1, le=50)
    poll_interval: float = Field(default=0.25, gt=0)
    attempt_timeout: float = Field(default=5, gt=0)
    lease_seconds: float = Field(default=30, gt=0)
    shutdown_timeout: float = Field(default=6, gt=0)
    max_attempts: int = Field(default=5, ge=1, le=100)
    retry_base: float = Field(default=1, gt=0)
    retry_cap: float = Field(default=30, gt=0)
    rate_limit: int = Field(default=50, ge=1)
    rate_window: float = Field(default=10, gt=0)
    rate_spacing: float = Field(default=1 / 4.5, ge=0)

    @model_validator(mode="after")
    def validate_timing(self) -> "Settings":
        if self.lease_seconds <= self.attempt_timeout + 2:
            raise ValueError("lease_seconds must exceed attempt_timeout by more than two seconds")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.model_validate(
            {
                name: os.environ[f"NOTIFY_{name.upper()}"]
                for name in cls.model_fields
                if f"NOTIFY_{name.upper()}" in os.environ
            }
        )
