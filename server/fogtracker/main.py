"""
Fog Gate Tracker - Backend Server

FastAPI server with REST API and WebSocket support for real-time sync.
"""

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from fogtracker import __version__
from fogtracker.api import api_router
from fogtracker.config import settings
from fogtracker.database import init_db
from fogtracker.logging_config import configure_logging, get_logger
from fogtracker.middleware import RateLimitMiddleware
from fogtracker.websocket import HostClient, ModClient, ViewerClient
from fogtracker.zone_resolver import init_resolver

# Configure structured logging
configure_logging(
    json_output=settings.log_json,
    log_level=settings.log_level,
    log_file=settings.log_file,
    log_file_json=settings.log_file_json,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Startup: initialize database tables (dev only)
    # In production, use Alembic migrations
    await init_db()

    # Initialize zone resolver with fog randomizer data
    data_dir = Path(__file__).parent.parent / settings.data_dir
    resolver = init_resolver(data_dir)
    logger = get_logger(__name__)
    logger.info(
        "zone_resolver_initialized",
        map_rules=len(resolver.map_rules),
        zone_names=len(resolver.zone_display_names),
        grace_entries=len(resolver.grace_mapping),
    )

    yield
    # Shutdown: nothing to do


app = FastAPI(
    title="Fog Gate Tracker API",
    description="Backend for er-fog-tracker with real-time sync",
    version=__version__,
    lifespan=lifespan,
)


# Version header middleware
class VersionHeaderMiddleware(BaseHTTPMiddleware):
    """Add Server-Version header to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Server-Version"] = __version__
        return response


app.add_middleware(VersionHeaderMiddleware)
app.add_middleware(RateLimitMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Mount API routes
app.include_router(api_router)


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@app.websocket("/ws/mod/{game_id}")
async def ws_mod(websocket: WebSocket, game_id: UUID):
    """WebSocket endpoint for mod connections."""
    await ModClient.handle_connection(websocket, game_id)


@app.websocket("/ws/host/{game_id}")
async def ws_host(websocket: WebSocket, game_id: UUID):
    """WebSocket endpoint for host (streamer browser) connections."""
    await HostClient.handle_connection(websocket, game_id)


@app.websocket("/ws/viewer/{game_id}")
async def ws_viewer(websocket: WebSocket, game_id: UUID):
    """WebSocket endpoint for viewer connections."""
    await ViewerClient.handle_connection(websocket, game_id)


# =============================================================================
# Health Check
# =============================================================================


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    from fogtracker.websocket import manager

    total_rooms = len(manager.rooms)
    total_viewers = sum(len(r.viewers) for r in manager.rooms.values())
    active_hosts = sum(1 for r in manager.rooms.values() if r.host)
    active_mods = sum(1 for r in manager.rooms.values() if r.mod)

    return {
        "status": "ok",
        "rooms": total_rooms,
        "active_hosts": active_hosts,
        "active_mods": active_mods,
        "total_viewers": total_viewers,
    }


# =============================================================================
# Static Files and SPA Fallback
# =============================================================================

# Path to web directory (relative to server/ directory)
WEB_DIR = Path(__file__).parent.parent.parent / "web"


# Mount static assets (js, css, data, etc.)
app.mount("/js", StaticFiles(directory=WEB_DIR / "js"), name="js")
app.mount("/styles", StaticFiles(directory=WEB_DIR / "styles"), name="styles")
app.mount("/data", StaticFiles(directory=WEB_DIR / "data"), name="data")


@app.get("/favicon.svg")
async def favicon():
    """Serve favicon."""
    return FileResponse(WEB_DIR / "favicon.svg")


@app.get("/{full_path:path}")
async def spa_fallback(request: Request, full_path: str):
    """
    SPA fallback: serve index.html for all non-API routes.
    This enables client-side routing with History API.
    """
    # Check if it's a static file that exists
    file_path = WEB_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)

    # Otherwise serve index.html for SPA routing
    return FileResponse(WEB_DIR / "index.html")


# =============================================================================
# Main
# =============================================================================


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Fog Gate Tracker Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    print(f"Starting server on http://{args.host}:{args.port}")
    print(f"API docs: http://localhost:{args.port}/docs")

    uvicorn.run(
        "fogtracker.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
