"""
Authentication routes (Twitch OAuth).
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fogvizu.auth import (
    exchange_code_for_token,
    generate_api_token,
    get_current_user,
    get_or_create_user,
    get_twitch_oauth_url,
    get_twitch_user,
)
from fogvizu.database import User, get_db
from fogvizu.models import UserMe

router = APIRouter()

# In-memory state storage (for OAuth CSRF protection)
# In production, use Redis or similar
_oauth_states: set[str] = set()


@router.get("/twitch")
async def auth_twitch_redirect():
    """Redirect to Twitch OAuth."""
    state = secrets.token_urlsafe(16)
    _oauth_states.add(state)

    # Clean up old states (keep last 1000)
    if len(_oauth_states) > 1000:
        _oauth_states.clear()

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

    # Validate state
    if not state or state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )
    _oauth_states.discard(state)

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
