"""
Fog Gate Visualizer - Backend Server

FastAPI server with REST API and WebSocket support for real-time sync.
"""

import argparse
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fogvizu.api import api_router
from fogvizu.config import settings
from fogvizu.database import init_db
from fogvizu.websocket import (
    handle_host_connection,
    handle_mod_connection,
    handle_viewer_connection,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Startup: initialize database tables (dev only)
    # In production, use Alembic migrations
    await init_db()
    yield
    # Shutdown: nothing to do


app = FastAPI(
    title="Fog Gate Visualizer API",
    description="Backend for er-fog-vizu with real-time sync",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(api_router)


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@app.websocket("/ws/mod/{game_id}")
async def ws_mod(websocket: WebSocket, game_id: UUID):
    """WebSocket endpoint for mod connections."""
    await handle_mod_connection(websocket, game_id)


@app.websocket("/ws/host/{game_id}")
async def ws_host(websocket: WebSocket, game_id: UUID):
    """WebSocket endpoint for host (streamer browser) connections."""
    await handle_host_connection(websocket, game_id)


@app.websocket("/ws/viewer/{game_id}")
async def ws_viewer(websocket: WebSocket, game_id: UUID):
    """WebSocket endpoint for viewer connections."""
    await handle_viewer_connection(websocket, game_id)


# =============================================================================
# Health Check
# =============================================================================


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    from fogvizu.websocket import manager

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

    parser = argparse.ArgumentParser(description="Fog Gate Visualizer Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    print(f"Starting server on http://{args.host}:{args.port}")
    print(f"API docs: http://localhost:{args.port}/docs")

    uvicorn.run(
        "fogvizu.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
