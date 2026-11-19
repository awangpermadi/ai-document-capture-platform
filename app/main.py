from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database.init_db import initialize_database
from app.routes.documents import router as documents_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await initialize_database()
    yield


app = FastAPI(
    title="AI Document Capture Platform",
    description="API for extracting structured data from documents",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(documents_router)


@app.get("/")
async def root():
    return {
        "application": "AI Document Capture Platform",
        "status": "running",
        "version": "0.1.0"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy"
    }