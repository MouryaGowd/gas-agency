from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from . import analytics, db, orders
from .deps import check_csrf, flash, render, require_customer

router = APIRouter(prefix="/portal")


def _go(url="/portal"):
    return RedirectResponse(url, status_code=303)


@router.get("")
def portal(request: Request, user: dict = Depends(require_customer)):
    cid = user["customer"]["id"]
    with db.connect() as conn:
        pred = conn.execute(
            "SELECT p.*, pr.name AS product_name FROM predictions p JOIN products pr ON pr.id=p.product_id "
            "WHERE p.customer_id=?", (cid,)).fetchone()
        products = [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY size_kg")]
        open_o = orders.open_order(conn, cid)
        history = conn.execute(
            "SELECT o.*, p.name AS product_name FROM orders o JOIN products p ON p.id=o.product_id "
            "WHERE o.customer_id=? ORDER BY COALESCE(o.delivery_date, o.requested_date) DESC, o.id DESC LIMIT 25",
            (cid,)).fetchall()
    return render(request, "portal.html", customer=user["customer"], pred=dict(pred) if pred else None,
                  products=products, open_order=dict(open_o) if open_o else None,
                  history=[dict(h) for h in history], summary=analytics.customer_summary(cid),
                  min_date=date.today().isoformat(),
                  max_date=(date.today() + timedelta(days=orders.MAX_ADVANCE_DAYS)).isoformat(),
                  default_date=(date.today() + timedelta(days=1)).isoformat())


@router.post("/book")
def book(request: Request, product_id: int = Form(...), qty: int = Form(...), requested_date: str = Form(""),
         notes: str = Form(""), csrf_token: str = Form(""), user: dict = Depends(require_customer)):
    check_csrf(request, csrf_token)
    try:
        oid = orders.create_booking(user["customer"]["id"], product_id, qty, requested_date, "web", notes)
        flash(request, f"Booking #{oid} placed. We will confirm it shortly.")
    except orders.OrderError as exc:
        flash(request, str(exc), "err")
    return _go()


@router.post("/cancel/{order_id}")
def cancel(request: Request, order_id: int, csrf_token: str = Form(""), user: dict = Depends(require_customer)):
    check_csrf(request, csrf_token)
    with db.connect() as conn:  # a customer may only cancel their own open order
        row = conn.execute("SELECT id FROM orders WHERE id=? AND customer_id=?",
                           (order_id, user["customer"]["id"])).fetchone()
    if not row:
        flash(request, "Order not found.", "err")
        return _go()
    try:
        flash(request, orders.set_status(order_id, "cancel"))
    except orders.OrderError as exc:
        flash(request, str(exc), "err")
    return _go()


@router.post("/reminders")
def toggle_reminders(request: Request, enabled: str = Form("0"), csrf_token: str = Form(""),
                     user: dict = Depends(require_customer)):
    check_csrf(request, csrf_token)
    with db.connect() as conn:
        conn.execute("UPDATE customers SET reminders_enabled=? WHERE id=?",
                     (1 if enabled == "1" else 0, user["customer"]["id"]))
    flash(request, "Reminder emails " + ("turned on." if enabled == "1" else "turned off."))
    return _go()
