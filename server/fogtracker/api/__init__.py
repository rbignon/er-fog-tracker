"""
API routes package.
"""

from fastapi import APIRouter

from fogtracker.api.auth import router as auth_router
from fogtracker.api.games import router as games_router
from fogtracker.api.mod import router as mod_router
from fogtracker.api.spoiler import router as spoiler_router
from fogtracker.api.users import router as users_router

api_router = APIRouter()

# Mount sub-routers
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(games_router, prefix="/api", tags=["games"])
api_router.include_router(users_router, prefix="/api", tags=["users"])
api_router.include_router(mod_router, prefix="/api", tags=["mod"])
api_router.include_router(spoiler_router, prefix="/api", tags=["spoiler"])
