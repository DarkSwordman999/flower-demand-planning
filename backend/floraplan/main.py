"""Приложение FastAPI: REST API (OpenAPI 3 — /api/docs) и веб-интерфейс."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from . import __version__, db
from .config import get_settings
from .errors import DomainError

STATIC = Path(__file__).resolve().parent / "static"


def _routers():
    from .api import admin, auth, inventory, nsi, onec, sales
    return [m.router for m in (auth, admin, nsi, inventory, sales, onec)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().ensure_dirs()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="ФлораПлан API", version=__version__, lifespan=lifespan,
                  description="Информационная система планирования закупок и продаж цветочной продукции. "
                              "Методы интернет-магазина: GET /api/shop/stock, GET /api/shop/prices, POST /api/shop/orders.",
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")],
                           allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message, **exc.data})

    for r in _routers():
        app.include_router(r)

    @app.get("/api/health", tags=["Служебное"])
    def health():
        with db.engine().connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    # веб-интерфейс (сборка React кладётся в floraplan/static)
    if (STATIC / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (STATIC / path).resolve()
            if path and f.is_file() and STATIC in f.parents:
                return FileResponse(f)
            return FileResponse(STATIC / "index.html")
    return app


app = create_app()
