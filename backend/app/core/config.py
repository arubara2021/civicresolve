"""Typed application configuration.

This module is the single authority for every tunable value in the backend. It
imports nothing from the application, which keeps it free of circular imports and
safe to load before logging, persistence, or the model client exist.

Access pattern: call ``get_settings()``. The result is cached for the process, so
repeated calls are free. Tests override configuration by setting environment
variables and calling ``reload_settings()``.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment posture. Production applies non-negotiable hardening."""

    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"


class AgentRuntime(StrEnum):
    """Selectable implementation behind the agent ports."""

    DIRECT = "direct"
    ADK = "adk"
    LANGGRAPH = "langgraph"


class Settings(BaseSettings):
    """Validated environment contract.

    Field names map to ``CIVIC_<FIELD_NAME>`` environment variables. Provider
    credentials declare an explicit validation alias, which bypasses the prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="CIVIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # Application identity
    app_name: str = "CivicResolve"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = True
    service_name: str = "civicresolve-api"
    api_prefix: str = "/api"

    # Server binding
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    # Declared as a string because pydantic-settings attempts JSON decoding on
    # sequence-typed fields before validators run. A comma-separated value is
    # friendlier in .env and is parsed by the cors_origins property below.
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias="CIVIC_CORS_ORIGINS",
    )

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./civicresolve.db"
    db_echo: bool = False

    # Agent selection
    agent_runtime: AgentRuntime = AgentRuntime.DIRECT
    auditor_max_tool_calls: int = Field(default=6, ge=1, le=12)

    # Model access
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
    )
    triage_model: str = "gemini-3.5-flash"
    forensics_model: str = "gemini-3.5-flash"
    fallback_model: str = "gemini-3.5-flash"
    gemini_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    triage_timeout_s: float = Field(default=45.0, gt=0)
    forensics_timeout_s: float = Field(default=25.0, gt=0)
    gemini_max_retries: int = Field(default=3, ge=0, le=8)
    gemini_daily_cap: int = Field(default=500, ge=1)
    breaker_threshold: int = Field(default=5, ge=1)
    breaker_reset_s: float = Field(default=60.0, gt=0)

    # Forensic thresholds
    geo_tolerance_m: float = Field(default=50.0, gt=0)
    min_repair_minutes: int = Field(default=120, ge=1)
    min_repair_floor: int = Field(default=15, ge=1)
    min_repair_ceiling: int = Field(default=10080, ge=1)
    phash_threshold: int = Field(default=8, ge=0, le=64)
    dup_cosine_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    max_inconclusive: int = Field(default=1, ge=0, le=6)
    visual_min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)

    # Priority composition
    w_urgency: float = Field(default=0.45, ge=0.0, le=1.0)
    w_impact: float = Field(default=0.30, ge=0.0, le=1.0)
    w_history: float = Field(default=0.25, ge=0.0, le=1.0)
    escalate_reopens: int = Field(default=2, ge=1)
    escalate_failed_closures: int = Field(default=3, ge=1)

    # Service-level agreement for citizen response
    sla_seconds: int = Field(default=259_200, ge=1)
    demo_sla_seconds: int = Field(default=60, ge=1)
    use_demo_sla: bool = True
    scheduler_tick_s: float = Field(default=5.0, gt=0)
    reopen_window_days: int = Field(default=30, ge=1)

    # Acceptance quorum
    quorum_size: int = Field(default=2, ge=1)
    quorum_radius_m: float = Field(default=50.0, gt=0)

    # Request hardening
    rate_limit_per_min: int = Field(default=30, ge=1)
    rate_limit_burst: int = Field(default=10, ge=1)
    idempotency_ttl_s: int = Field(default=86_400, ge=1)
    max_upload_mb: int = Field(default=12, ge=1, le=100)
    allowed_mime: str = Field(
        default="image/jpeg,image/png,image/webp,image/heic",
        validation_alias="CIVIC_ALLOWED_MIME",
    )

    # Evidence storage
    upload_dir: str = "./uploads"
    thumbnail_max_px: int = Field(default=1600, ge=256)
    jpeg_quality: int = Field(default=82, ge=1, le=100)

    # Notifications
    sse_heartbeat_s: float = Field(default=15.0, gt=0)
    outbox_poll_s: float = Field(default=1.0, gt=0)
    email_enabled: bool = False
    resend_api_key: SecretStr | None = Field(default=None, validation_alias="RESEND_API_KEY")
    email_from: str = "CivicResolve <noreply@example.com>"

    # Demo affordances
    seed_on_startup: bool = True
    demo_reset_enabled: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        """Accept lowercase level names and map the common alias to stdlib naming."""
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return "WARNING" if cleaned == "WARN" else cleaned
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if value not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return value

    @field_validator("api_prefix")
    @classmethod
    def _validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("api_prefix must start with '/' and must not end with '/'")
        return value

    @model_validator(mode="after")
    def _enforce_invariants(self) -> Settings:
        """Reject configurations that would produce silently wrong behaviour."""
        weight_sum = self.w_urgency + self.w_impact + self.w_history
        if abs(weight_sum - 1.0) > 1e-6:
            raise ValueError(
                f"priority weights must sum to 1.0; got {weight_sum:.6f} "
                f"({self.w_urgency}, {self.w_impact}, {self.w_history})"
            )

        if not self.min_repair_floor <= self.min_repair_minutes <= self.min_repair_ceiling:
            raise ValueError(
                "min_repair_minutes must lie between min_repair_floor and min_repair_ceiling"
            )

        if self.demo_sla_seconds > self.sla_seconds:
            raise ValueError("demo_sla_seconds must not exceed sla_seconds")

        if self.environment is Environment.PRODUCTION:
            # Production hardening is applied rather than merely recommended, so a
            # misconfigured deployment fails closed instead of exposing demo routes.
            if not self.has_gemini_key:
                raise ValueError("GEMINI_API_KEY is required when CIVIC_ENVIRONMENT=production")
            object.__setattr__(self, "debug", False)
            object.__setattr__(self, "log_json", True)
            object.__setattr__(self, "seed_on_startup", False)
            object.__setattr__(self, "demo_reset_enabled", False)
            object.__setattr__(self, "use_demo_sla", False)

        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_sla_seconds(self) -> int:
        """The SLA actually enforced by the scheduler."""
        return self.demo_sla_seconds if self.use_demo_sla else self.sla_seconds

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_api_key.get_secret_value().strip())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir).expanduser().resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed CORS origins. An empty entry is dropped rather than treated as '*'."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_mime_types(self) -> frozenset[str]:
        return frozenset(
            item.strip().lower() for item in self.allowed_mime.split(",") if item.strip()
        )

    def gemini_key_value(self) -> str:
        """Return the raw key for the SDK. Never log the return value."""
        if not self.has_gemini_key or self.gemini_api_key is None:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        return self.gemini_api_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance, constructing it on first use."""
    return Settings()


def reload_settings() -> Settings:
    """Discard the cached instance. Intended for tests that mutate the environment."""
    get_settings.cache_clear()
    return get_settings()
