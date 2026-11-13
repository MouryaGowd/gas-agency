import hmac
import time
from datetime import date

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from . import config, db
from .security import new_csrf

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))


def inr(value, decimals: int = 0) -> str:
    """Format using Indian digit grouping: 1234567 -> ₹12,34,567."""
    if value is None:
        return "–"
    neg = value < 0
    s = f"{abs(value):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{'-' if neg else ''}₹{whole}{'.' + frac if frac else ''}"


def num(value, decimals: int = 0) -> str:
    return "–" if value is None else f"{value:,.{decimals}f}"


def fdate(value) -> str:
    if not value:
        return "–"
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return d.strftime("%d %b %Y")


def days_from_today(value) -> int:
    return (date.fromisoformat(str(value)[:10]) - date.today()).days


templates.env.filters.update(inr=inr, num=num, fdate=fdate, multiply100=lambda v: round(v * 100, 1))
templates.env.globals.update(days_from_today=days_from_today, business_name=config.BUSINESS_NAME)


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = new_csrf()
    return request.session["csrf"]


def check_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, submitted or ""):
        raise HTTPException(403, "Invalid or expired form. Go back, refresh the page and try again.")


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = [kind, message]


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.update(user=current_user(request), csrf=csrf_token(request),
               flash=request.session.pop("flash", None), path=request.url.path)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    with db.connect() as conn:
        row = conn.execute("SELECT id, email, role FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def _redirect(url: str) -> HTTPException:
    return HTTPException(303, headers={"Location": url})


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if not user or user["role"] != "admin":
        raise _redirect("/admin/login")
    return user


def require_customer(request: Request) -> dict:
    user = current_user(request)
    if not user or user["role"] != "customer":
        raise _redirect("/login")
    with db.connect() as conn:
        cust = conn.execute("SELECT * FROM customers WHERE user_id=?", (user["id"],)).fetchone()
    if not cust:
        raise _redirect("/login")
    user["customer"] = dict(cust)
    return user


# --- tiny in-memory login throttle (per process; enough for a single-dealer deployment) ---
_FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW = 6, 600


def throttled(key: str) -> bool:
    now = time.time()
    _FAILS[key] = [t for t in _FAILS.get(key, []) if now - t < WINDOW]
    return len(_FAILS[key]) >= MAX_FAILS


def record_fail(key: str) -> None:
    _FAILS.setdefault(key, []).append(time.time())


def clear_fails(key: str) -> None:
    _FAILS.pop(key, None)
