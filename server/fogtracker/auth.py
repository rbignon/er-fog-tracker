"""
Twitch OAuth authentication and token validation.
"""

import secrets
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fogtracker.config import settings
from fogtracker.database import User, get_db

# =============================================================================
# Twitch OAuth
# =============================================================================


@dataclass
class TwitchUser:
    """Twitch user info from API."""

    id: str
    login: str
    display_name: str
    profile_image_url: str | None = None


def get_twitch_oauth_url(state: str) -> str:
    """Generate Twitch OAuth URL."""
    return (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={settings.twitch_client_id}"
        f"&redirect_uri={settings.twitch_redirect_uri}"
        f"&response_type=code"
        f"&scope=user:read:email"
        f"&state={state}"
    )


async def exchange_code_for_token(code: str) -> str | None:
    """Exchange OAuth code for access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.twitch_redirect_uri,
            },
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None


async def get_twitch_user(access_token: str) -> TwitchUser | None:
    """Get Twitch user info from access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": settings.twitch_client_id,
            },
        )
        if resp.status_code == 200:
            data = resp.json()["data"][0]
            return TwitchUser(
                id=data["id"],
                login=data["login"],
                display_name=data["display_name"],
                profile_image_url=data.get("profile_image_url"),
            )
        return None


def generate_api_token() -> str:
    """Generate a secure API token."""
    return secrets.token_urlsafe(32)


# =============================================================================
# User Management
# =============================================================================


async def get_or_create_user(db: AsyncSession, twitch_user: TwitchUser) -> User:
    """Get existing user or create new one."""
    result = await db.execute(select(User).where(User.twitch_id == twitch_user.id))
    user = result.scalar_one_or_none()

    if user:
        # Update user info
        user.twitch_username = twitch_user.login
        user.twitch_display_name = twitch_user.display_name
        user.twitch_avatar_url = twitch_user.profile_image_url
        await db.flush()
        return user

    # Create new user
    user = User(
        twitch_id=twitch_user.id,
        twitch_username=twitch_user.login,
        twitch_display_name=twitch_user.display_name,
        twitch_avatar_url=twitch_user.profile_image_url,
        api_token=generate_api_token(),
        mod_token=generate_api_token(),
    )
    db.add(user)
    await db.flush()
    return user


async def get_user_by_token(db: AsyncSession, token: str) -> User | None:
    """Get user by API token."""
    result = await db.execute(select(User).where(User.api_token == token))
    return result.scalar_one_or_none()


async def get_user_by_mod_token(db: AsyncSession, token: str) -> User | None:
    """Get user by mod token (used by the game mod for WebSocket auth)."""
    result = await db.execute(select(User).where(User.mod_token == token))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """Get user by Twitch username."""
    result = await db.execute(select(User).where(User.twitch_username == username.lower()))
    return result.scalar_one_or_none()


# =============================================================================
# FastAPI Dependencies
# =============================================================================

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user.
    Raises 401 if not authenticated.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    user = await get_user_by_token(db, credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    Dependency to get the current user if authenticated, None otherwise.
    """
    if not credentials:
        return None

    return await get_user_by_token(db, credentials.credentials)


async def get_current_user_by_mod_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current user authenticated via mod token.
    Used by the game mod/launcher for API access.
    Raises 401 if not authenticated.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing mod token",
        )

    user = await get_user_by_mod_token(db, credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mod token",
        )

    return user
