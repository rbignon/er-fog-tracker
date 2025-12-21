"""
Application configuration loaded from environment variables.
"""

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
    log_file: str | None = None  # Optional file path for logging

    # Data files (fog randomizer data)
    data_dir: str = "data"

    # WebSocket
    heartbeat_interval: int = 15
    heartbeat_timeout: int = 10

    # Limits
    max_games_per_user: int = 10
    max_viewers_per_game: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
