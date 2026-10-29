from __future__ import annotations

from contextlib import asynccontextmanager

import pymupdf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.core.config import APP_NAME, APP_VERSION, WEB_OUT_DIR, ensure_dirs
from api.routers.documents import router as documents_router
from api.routers.editor import assets_router, router as editor_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    yield


app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router, prefix="/api")
app.include_router(editor_router, prefix="/api")
app.include_router(assets_router, prefix="/api")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "engine": f"PyMuPDF {pymupdf.__version__}",
    }


if (WEB_OUT_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=WEB_OUT_DIR, html=True), name="web")
else:

    @app.get("/")
    async def dev_hint():
        return JSONResponse(
            {
                "message": "Frontend build not found. Run start.bat, or npm run dev inside web/.",
                "docs": "/docs",
            }
        )
