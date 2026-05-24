"""FastAPI application entry point.

Run locally with::

    uvicorn backend.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from backend.database import SessionLocal, create_all
from backend.models import Team
from backend.routers import draft, league, players, playoffs, sim, teams, transactions

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Idempotent — safe to call even if seed.py has already populated the DB.
    create_all()
    # Fresh deploys (e.g. Render) start with an empty SQLite file — seed once.
    with SessionLocal() as db:
        team_count = db.scalar(select(func.count()).select_from(Team)) or 0
        if team_count == 0:
            from backend.seed import reset_database
            reset_database(verbose=False)
    yield


app = FastAPI(
    title="Pokémon NBA GM Simulator",
    description="Front-office simulator where Pokémon BST is salary and abilities are basketball badges.",
    version="0.1.0",
    lifespan=lifespan,
)

# Vanilla JS frontend will run from a different origin during dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teams.router)
app.include_router(players.router)
app.include_router(league.router)
app.include_router(sim.router)
app.include_router(transactions.router)
app.include_router(playoffs.router)
app.include_router(draft.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/version", tags=["meta"])
def version() -> dict[str, str]:
    return {"app": "pokeNBA", "version": app.version, "docs": "/docs"}


# --- Frontend (vanilla JS SPA) ----------------------------------------------
if FRONTEND_DIR.exists():
    # Serve every static asset (css, js, images) from /static/<file>.
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
