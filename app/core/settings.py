"""Конфигурация приложения.

Значения читаются из переменных окружения и файла `.env`. Пороги и веса аналитики
здесь — стартовые; рабочие значения хранятся в таблице `settings` и меняются на экране «Настройки».
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки окружения."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    secret_key: str = "change-me-please-32-characters-min"
    database_url: str = "sqlite:///./pulse.db"
    session_hours: int = 12
    invite_days: int = 7
    login_attempts_per_minute: int = 5
    demo_mode: bool = True
    demo_password: str = "pulse-demo-2026"

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    ollama_timeout: float = 60.0
    llm_enabled: bool = True

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    yandex_forms_token: str = ""
    yandex_form_id: str = ""
    google_forms_credentials: str = ""
    google_form_id: str = ""
    forms_poll_seconds: int = 15

    @property
    def is_dev(self) -> bool:
        """Режим разработки: включает OpenAPI на /docs."""
        return self.app_env == "dev"


DEFAULT_ANALYTICS: dict[str, float] = {
    "level_threshold": 0.25,
    "level_months": 2,
    "growth_slope": 0.05,
    "lag_drop": 0.10,
    "words_score": 0.70,
    "words_anxiety": 0.60,
    "program_drop": 0.10,
    "program_share": 0.60,
    "red_zone": 0.50,
    "w_level": 60,
    "w_growth": 250,
    "w_drop": 60,
    "w_low": 120,
    "low_level": 0.60,
    "w_words": 30,
    "w_lag": 5,
    "w_missing": 8,
    "index_floor": 5,
    "alert_health": 50,
    "alert_delta": 0.40,
    "alert_days": 3,
}


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный объект настроек."""
    return Settings()
