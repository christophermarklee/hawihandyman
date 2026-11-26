"""HaleClock — scheduling, time tracking, and cash invoicing for Hawi Handyman."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .auth import RequiresLogin, login_redirect
from .auth import router as auth_router
from .database import init_db
from .routers import catalog, clock, invoices, public, schedule, timecards


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="HaleClock", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.secret_key(),
    max_age=60 * 60 * 24 * 30,  # 30-day session so job-site logins stick (PRD §4)
    https_only=True,
    same_site="lax",
)


@app.exception_handler(RequiresLogin)
async def requires_login_handler(request: Request, _exc: RequiresLogin):
    return login_redirect(request)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(public.router)
app.include_router(clock.router)
app.include_router(schedule.router)
app.include_router(timecards.router)
app.include_router(invoices.router)
app.include_router(catalog.router)
