import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from manager.controllers import nodes, metrics
from manager.services.metrics_service import metrics_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    FastAPICache.init(InMemoryBackend())
    await metrics_service.start_collecting()
    yield
    await metrics_service.stop_collecting()


app = FastAPI(lifespan=lifespan)

CORS_ORIGINS = os.environ.get("CORS_ORIGINS")

if CORS_ORIGINS:
    origins = CORS_ORIGINS.split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(nodes.router)
app.include_router(metrics.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
