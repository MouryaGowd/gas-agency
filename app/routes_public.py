import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from . import db, ml, orders
from .constants import SEGMENT_NAMES, SEGMENTS
from .deps import (check_csrf, clear_fails, flash, record_fail, render, throttled, current_user)
from .security import hash_password, read_booking_token, verify_password

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


@router.get("/")
def landing(request: Request):
    user = current_user(request)
    if user:
        return _go("/admin" if user["role"] == "admin" else "/portal")
    return render(request, "landing.html")


def _login(request: Request, email: str, password: str, role: str):
    email = email.strip().lower()
    key = f"{request.client.host if request.client else '?'}:{email}"
    if throttled(key):
        return "Too many failed attempts. Try again in a few minutes."
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=? AND role=?", (email, role)).fetchone()
    if not verify_password(password, row["password_hash"] if row else None) or not row:
        record_fail(key)
        return "Incorrect email or password."
    clear_fails(key)
    request.session.clear()  # new session on login (prevents fixation)
    request.session["uid"] = row["id"]
    return None


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", role="customer", error=None)


@router.post("/login")
def login_submit(request: Request, email: str = Form(""), password: str = Form(""), csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    err = _login(request, email, password, "customer")
    if err:
        return render(request, "login.html", status_code=401, role="customer", error=err, email=email)
    return _go("/portal")


@router.get("/admin/login")
def admin_login_page(request: Request):
    return render(request, "login.html", role="admin", error=None)


@router.post("/admin/login")
def admin_login_submit(request: Request, email: str = Form(""), password: str = Form(""),
                       csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    err = _login(request, email, password, "admin")
    if err:
        return render(request, "login.html", status_code=401, role="admin", error=err, email=email)
    return _go("/admin")


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    request.session.clear()
    return _go("/")


@router.get("/register")
def register_page(request: Request):
    return render(request, "register.html", segments=SEGMENT_NAMES, error=None, form={})


@router.post("/register")
def register_submit(request: Request, business_name: str = Form(""), contact_name: str = Form(""),
                    email: str = Form(""), phone: str = Form(""), address: str = Form(""),
                    segment: str = Form(""), password: str = Form(""), csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    form = dict(business_name=business_name.strip(), contact_name=contact_name.strip(),
                email=email.strip().lower(), phone=phone.strip(), address=address.strip(), segment=segment)
    error = None
    if not all([form["business_name"], form["contact_name"], form["address"]]):
        error = "Business name, contact name and address are required."
    elif not EMAIL_RE.match(form["email"]):
        error = "Enter a valid email address."
    elif segment not in SEGMENTS:
        error = "Choose your business type."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    if not error:
        with db.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email=?", (form["email"],)).fetchone():
                error = "An account with this email already exists. Try logging in."
            else:
                uid = conn.execute("INSERT INTO users (email, password_hash, role) VALUES (?,?, 'customer')",
                                   (form["email"], hash_password(password))).lastrowid
                conn.execute(
                    """INSERT INTO customers (user_id, business_name, contact_name, email, phone, address,
                       segment, credit_days) VALUES (?,?,?,?,?,?,?,?)""",
                    (uid, form["business_name"], form["contact_name"], form["email"], form["phone"],
                     form["address"], segment, SEGMENTS[segment]["credit"]))
                request.session.clear()
                request.session["uid"] = uid
    if error:
        return render(request, "register.html", status_code=400, segments=SEGMENT_NAMES, error=error, form=form)
    flash(request, "Welcome! Your account is ready.")
    return _go("/portal")


# ---- one-click booking from the reminder email -------------------------------------------------

def _link_context(token: str):
    data = read_booking_token(token)
    if not data:
        return None
    with db.connect() as conn:
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (data["c"],)).fetchone()
        prods = conn.execute("SELECT * FROM products ORDER BY size_kg").fetchall()
        existing = orders.open_order(conn, data["c"]) if cust else None
    if not cust:
        return None
    return dict(data=data, cust=dict(cust), products=[dict(p) for p in prods],
                existing=dict(existing) if existing else None)


@router.get("/book/{token}")
def book_link(request: Request, token: str):
    ctx = _link_context(token)
    if not ctx:
        return render(request, "book_link.html", status_code=410, expired=True)
    from datetime import date, timedelta
    pred_date = date.today() + timedelta(days=1)
    return render(request, "book_link.html", expired=False, token=token, error=None, done=False,
                  min_date=date.today().isoformat(), default_date=pred_date.isoformat(),
                  max_date=(date.today() + timedelta(days=orders.MAX_ADVANCE_DAYS)).isoformat(), **ctx)


@router.post("/book/{token}")
def book_link_submit(request: Request, token: str, product_id: int = Form(...), qty: int = Form(...),
                     requested_date: str = Form(""), notes: str = Form(""), csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    ctx = _link_context(token)
    if not ctx:
        return render(request, "book_link.html", status_code=410, expired=True)
    from datetime import date, timedelta
    try:
        oid = orders.create_booking(ctx["data"]["c"], product_id, qty, requested_date, "email", notes)
    except orders.OrderError as exc:
        return render(request, "book_link.html", status_code=400, expired=False, token=token, error=str(exc),
                      done=False, min_date=date.today().isoformat(), default_date=requested_date,
                      max_date=(date.today() + timedelta(days=orders.MAX_ADVANCE_DAYS)).isoformat(), **ctx)
    return render(request, "book_link.html", expired=False, done=True, order_id=oid, token=token, error=None,
                  requested_date=requested_date, qty=qty, **ctx)
