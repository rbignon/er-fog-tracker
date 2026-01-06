"""
SQLAlchemy models and database session management.
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# =============================================================================
# Models
# =============================================================================


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    twitch_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    twitch_username: Mapped[str] = mapped_column(String(100), nullable=False)
    twitch_display_name: Mapped[str | None] = mapped_column(String(100))
    twitch_avatar_url: Mapped[str | None] = mapped_column(String(500))
    api_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    mod_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    games: Mapped[list["Game"]] = relationship(back_populates="user", lazy="selectin")

    __table_args__ = (
        Index("idx_users_twitch_username", "twitch_username"),
        Index("idx_users_api_token", "api_token"),
        Index("idx_users_mod_token", "mod_token"),
    )


class Game(Base):
    __tablename__ = "games"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    zone_links: Mapped[list] = mapped_column(JSONB, nullable=False)
    zones: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # Zone metadata keyed by zone_id
    entity_mapping: Mapped[dict | None] = mapped_column(JSONB)  # EMEVD entity -> zone mapping
    starting_zone_id: Mapped[str | None] = mapped_column(String(100))  # Starting zone_key

    # JSONB state columns
    discovered_zone_links: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    node_positions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    game_stats: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # {great_runes: [], kindling_count: 0, death_count: 0, play_time_ms: 0}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="games", lazy="selectin")

    __table_args__ = (
        Index("idx_games_user_id", "user_id"),
        Index(
            "idx_games_not_deleted",
            "user_id",
            postgresql_where=(deleted_at.is_(None)),
        ),
        Index("idx_games_seed", "seed"),
        Index(
            "idx_games_user_updated",
            "user_id",
            updated_at.desc(),
        ),
    )


# =============================================================================
# Database Session (lazy initialization)
# =============================================================================


@lru_cache
def get_engine():
    """Get cached database engine. Lazily initialized on first call."""
    from fogtracker.config import get_settings

    return create_async_engine(get_settings().database_url, echo=False)


@lru_cache
def get_async_session_maker():
    """Get cached async session maker. Lazily initialized on first call."""
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


class _AsyncSessionProxy:
    """Lazy proxy for backward compatibility with `async with async_session() as db:`."""

    def __call__(self):
        return get_async_session_maker()()


async_session = _AsyncSessionProxy()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions."""
    async with get_async_session_maker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (for development only, use Alembic in production)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
