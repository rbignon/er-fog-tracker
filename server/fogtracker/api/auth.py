"""
Authentication routes (Twitch OAuth).
"""

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fogtracker.auth import (
    exchange_code_for_token,
    generate_api_token,
    get_current_user,
    get_or_create_user,
    get_twitch_oauth_url,
    get_twitch_user,
)
from fogtracker.database import User, get_db
from fogtracker.models import UserMe

router = APIRouter()

# In-memory state storage (for OAuth CSRF protection)
# States expire after 10 minutes
_oauth_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _cleanup_expired_states() -> None:
    """Remove OAuth states older than TTL."""
    cutoff = time.time() - _STATE_TTL_SECONDS
    expired = [k for k, v in _oauth_states.items() if v < cutoff]
    for k in expired:
        del _oauth_states[k]


@router.get("/twitch")
async def auth_twitch_redirect():
    """Redirect to Twitch OAuth."""
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = time.time()

    # Lazy cleanup of expired states
    _cleanup_expired_states()

    return RedirectResponse(url=get_twitch_oauth_url(state))


@router.get("/twitch/callback")
async def auth_twitch_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle Twitch OAuth callback."""
    # Handle error from Twitch
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Twitch OAuth error: {error}",
        )

    # Validate state (also checks expiration via TTL)
    if not state or state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )
    del _oauth_states[state]

    # Validate code
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth code",
        )

    # Exchange code for token
    access_token = await exchange_code_for_token(code)
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange code for token",
        )

    # Get Twitch user info
    twitch_user = await get_twitch_user(access_token)
    if not twitch_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get Twitch user info",
        )

    # Get or create user in our database
    user = await get_or_create_user(db, twitch_user)

    # Redirect to dashboard with token in URL fragment
    # The frontend will extract the token and store it
    return RedirectResponse(
        url=f"/dashboard?token={user.api_token}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/me", response_model=UserMe)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info."""
    return UserMe(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        api_token=user.api_token,
        mod_token=user.mod_token,
    )


@router.post("/regenerate-mod-token", response_model=UserMe)
async def regenerate_mod_token(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the mod token for current user."""
    user.mod_token = generate_api_token()
    await db.flush()

    return UserMe(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        api_token=user.api_token,
        mod_token=user.mod_token,
    )


@router.post("/logout")
async def logout():
    """Logout (client-side only, just returns success)."""
    return {"status": "ok"}
