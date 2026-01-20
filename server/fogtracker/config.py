"""
Application configuration loaded from environment variables.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str

    # Twitch OAuth
    twitch_client_id: str
    twitch_client_secret: str
    twitch_redirect_uri: str = "http://localhost:8000/auth/twitch/callback"

    # Server
    secret_key: str
    cors_origins: list[str] = ["http://localhost:8000"]

    # Logging
    log_level: str = "INFO"
    log_json: bool = False  # Output JSON logs to console (for production)
    log_file: str | None = None  # Optional file path for logging
    log_file_json: bool = True  # Output JSON logs to file (easier to parse)

    # Data files (fog randomizer data)
    data_dir: str = "data"

    # Directory to store uploaded mod logs (reports)
    reports_dir: str | None = None

    # WebSocket
    heartbeat_interval: int = 15
    heartbeat_timeout: int = 10

    # Limits
    max_games_per_user: int = 10
    max_viewers_per_game: int = 10

    # Discord integration (optional)
    discord_webhook_url: str | None = None

    # Base URL for external links (used in Discord notifications)
    base_url: str = "https://fogtracker.malenia.win"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance. Lazily initialized on first call."""
    return Settings()


# Backward compatibility alias (deprecated, use get_settings() instead)
# This is a lazy proxy that only evaluates when accessed
class _SettingsProxy:
    """Lazy proxy for backward compatibility with `from config import settings`."""

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
