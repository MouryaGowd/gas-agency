import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import config, db, ml, reminders, synth
from .deps import render
from .routes_admin import router as admin_router
from .routes_customer import router as customer_router
from .routes_public import router as public_router
from .security import hash_password

log = logging.getLogger("gas")


def bootstrap() -> None:
    db.init_db()
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            conn.execute("INSERT INTO users (email, password_hash, role) VALUES (?,?, 'admin')",
                         (config.ADMIN_EMAIL.lower(), hash_password(config.ADMIN_PASSWORD)))
        empty = not conn.execute("SELECT 1 FROM orders LIMIT 1").fetchone()
    if empty:
        log.info("Empty database: generating synthetic data and training the model")
        synth.generate()
        ml.train()
        ml.refresh_predictions()
    elif not config.MODEL_PATH.exists():
        ml.train()
        ml.refresh_predictions()


async def reminder_loop():
    while True:
        await asyncio.sleep(config.REMINDER_CHECK_HOURS * 3600)
        try:
            counts = await asyncio.to_thread(reminders.send_all_due)
            log.info("Scheduled reminder run: %s", counts)
        except Exception:  # noqa: BLE001
            log.exception("Scheduled reminder run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(bootstrap)
    task = asyncio.create_task(reminder_loop()) if config.AUTO_REMINDERS else None
    yield
    if task:
        task.cancel()


app = FastAPI(title=config.BUSINESS_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, same_site="lax",
                   https_only=config.HTTPS_ONLY, max_age=60 * 60 * 12, session_cookie="gas_session")
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
app.include_router(public_router)
app.include_router(customer_router)
app.include_router(admin_router)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code in (301, 302, 303, 307):  # used by auth guards to redirect
        from fastapi.responses import RedirectResponse
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return HTMLResponse(
        render(request, "error.html", status_code=exc.status_code, code=exc.status_code,
               message=exc.detail if isinstance(exc.detail, str) else "Something went wrong").body,
        status_code=exc.status_code)
