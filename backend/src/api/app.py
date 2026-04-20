from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import (
    audit, auth, chat, documents, graph, integrations,
    meta, organizations, playground, sso, threads, welcome,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Ensure SQLModel tables (Document, User, AuditLog) exist on startup.
    from src.core import models  # noqa: F401 — side-effect imports tables
    from src.core.store import _get_engine

    _get_engine()
    # Ensure default org exists for multi-tenant demo
    from src.api.routers.organizations import ensure_default_org
    try:
        ensure_default_org()
    except Exception:
        pass  # table may not exist yet on first boot — that's fine
    yield


app = FastAPI(title="Prism RAG", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(threads.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(meta.router)
app.include_router(playground.router)
app.include_router(welcome.router)
app.include_router(graph.router)
app.include_router(organizations.router)
app.include_router(integrations.router)
app.include_router(sso.router)


@app.get("/")
async def root():
    return {"name": "Prism RAG", "version": app.version, "docs": "/docs"}
