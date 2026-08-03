"""
OpenOSINT Cloud — FastAPI application entry point.

Heroku Procfile:  web: uvicorn cloud.main:app --host 0.0.0.0 --port $PORT
Local dev:        python -m cloud.main
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from cloud import db, keys
from cloud.config import DATABASE_URL, resolve_session_secret
from cloud.routes import dashboard, enrich, usage
from cloud.routes import keys as keys_route
from cloud.routes import oauth as oauth_routes
from cloud.routes.mcp_gateway import _mcp, create_mcp_asgi_app

logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s", force=True
)  # force: FastMCP's __init__ (imported above) installs a width-cropping RichHandler first


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await db.init_pool()
    keys.init_keys()
    async with _mcp.session_manager.run():
        yield
    await db.close_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenOSINT Cloud",
        version="1.0.0",
        description=(
            "Hosted OSINT gateway — no upstream API-key juggling, AI-chained results. "
            "Invite-only access — contact commercial@openosint.tech."
        ),
        lifespan=_lifespan,
    )
    # httponly + samesite=lax are Starlette's unconditional defaults; https_only
    # (the Secure flag) defaults to False and must be forced on in production
    # (DATABASE_URL set) — local/test runs over plain HTTP otherwise.
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolve_session_secret(),
        https_only=bool(DATABASE_URL),
    )
    app.include_router(enrich.router,      prefix="/v1")
    app.include_router(usage.router,       prefix="/v1")
    app.include_router(keys_route.router,  prefix="/v1")
    app.include_router(oauth_routes.router)
    app.include_router(dashboard.router)
    app.mount("/mcp", create_mcp_asgi_app())
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("cloud.main:app", host="0.0.0.0", port=port, reload=False)
