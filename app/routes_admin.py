import threading
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse

from . import analytics, config, db, ml, orders, reminders, synth
from .deps import check_csrf, flash, render, require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
_train_lock = threading.Lock()


def _back(request: Request, default: str) -> RedirectResponse:
    ref = request.headers.get("referer", "")
    base = config.BASE_URL
    # only bounce back to our own pages
    if ref.startswith(base + "/admin") or ref.startswith(str(request.base_url).rstrip("/") + "/admin"):
        return RedirectResponse(ref, status_code=303)
    return RedirectResponse(default, status_code=303)


@router.get("")
def dashboard(request: Request, days: int = Query(30)):
    days = days if days in (7, 30, 90, 180, 365) else 30
    data = analytics.dashboard(days)
    with db.connect() as conn:
        upcoming = conn.execute(
            """SELECT p.*, c.business_name, c.segment, pr.name AS product_name,
                      (SELECT COUNT(*) FROM reminders r WHERE r.customer_id=p.customer_id
                         AND r.last_order_date=p.last_order_date AND r.status IN ('sent','logged')) AS reminded
               FROM predictions p JOIN customers c ON c.id=p.customer_id
               JOIN products pr ON pr.id=p.product_id
               WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=p.customer_id
                                 AND o.status IN ('booked','confirmed'))
               ORDER BY p.predicted_date LIMIT 8""").fetchall()
    return render(request, "admin/dashboard.html", d=data, days=days, upcoming=[dict(u) for u in upcoming],
                  model=ml.load_metrics())


@router.get("/forecast")
def forecast(request: Request, show: str = Query("all")):
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT p.*, c.business_name, c.contact_name, c.segment, c.reminders_enabled, c.email,
                      pr.name AS product_name,
                      (SELECT COUNT(*) FROM orders o WHERE o.customer_id=p.customer_id
                         AND o.status IN ('booked','confirmed')) AS has_open,
                      (SELECT MAX(created_at) FROM reminders r WHERE r.customer_id=p.customer_id
                         AND r.last_order_date=p.last_order_date AND r.status IN ('sent','logged')) AS reminded_at
               FROM predictions p JOIN customers c ON c.id=p.customer_id
               JOIN products pr ON pr.id=p.product_id ORDER BY p.predicted_date""").fetchall()
    rows = [dict(r) for r in rows]
    today = date.today()
    for r in rows:
        r["days_left"] = (date.fromisoformat(r["predicted_date"]) - today).days
    if show == "due":
        rows = [r for r in rows if r["days_left"] <= config.REMINDER_DAYS and not r["has_open"]]
    elif show == "week":
        rows = [r for r in rows if r["days_left"] <= 7 and not r["has_open"]]
    elif show == "unreminded":
        rows = [r for r in rows if r["days_left"] <= config.REMINDER_DAYS and not r["has_open"]
                and not r["reminded_at"]]
    return render(request, "admin/forecast.html", rows=rows, show=show,
                  due_count=len(reminders.due_customers()), reminder_days=config.REMINDER_DAYS,
                  smtp=bool(config.SMTP_HOST), redirect=config.TEST_EMAIL_REDIRECT)


@router.post("/reminders/send-due")
def send_due(request: Request, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    c = reminders.send_all_due()
    flash(request, f"Reminders processed: {c['sent']} sent, {c['logged']} saved to outbox, "
                   f"{c['failed']} failed, {c['skipped']} skipped.", "err" if c["failed"] else "ok")
    return _back(request, "/admin/forecast")


@router.post("/reminders/send/{customer_id}")
def send_one(request: Request, customer_id: int, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    status, detail = reminders.send_reminder(customer_id, force=True)
    flash(request, f"Reminder {status}: {detail}", "err" if status == "failed" else "ok")
    return _back(request, "/admin/forecast")


@router.get("/reminders")
def reminder_log(request: Request):
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT r.*, c.business_name FROM reminders r JOIN customers c ON c.id=r.customer_id
               ORDER BY r.id DESC LIMIT 200""").fetchall()
    return render(request, "admin/reminders.html", rows=[dict(r) for r in rows])


@router.get("/reminders/{reminder_id}")
def reminder_view(request: Request, reminder_id: int):
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
    if not r:
        return RedirectResponse("/admin/reminders", status_code=303)
    return render(request, "admin/reminder_view.html", r=dict(r))


@router.get("/customers")
def customers(request: Request, q: str = Query(""), segment: str = Query("")):
    sql = """SELECT c.*, p.predicted_date,
                    COALESCE((SELECT SUM(o.qty*o.unit_price) FROM orders o WHERE o.customer_id=c.id
                              AND o.status='delivered' AND o.delivery_date >= ?),0) AS rev_90,
                    COALESCE((SELECT SUM(o.qty*o.unit_price) FROM orders o WHERE o.customer_id=c.id
                              AND o.status='delivered' AND o.payment_status='unpaid'),0) AS outstanding
             FROM customers c LEFT JOIN predictions p ON p.customer_id=c.id WHERE 1=1"""
    args: list = [(date.today() - timedelta(days=90)).isoformat()]
    if q:
        sql += " AND (c.business_name LIKE ? OR c.contact_name LIKE ? OR c.email LIKE ?)"
        args += [f"%{q}%"] * 3
    if segment:
        sql += " AND c.segment=?"
        args.append(segment)
    sql += " ORDER BY rev_90 DESC, c.business_name LIMIT 300"
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        segs = [r[0] for r in conn.execute("SELECT DISTINCT segment FROM customers ORDER BY 1")]
    return render(request, "admin/customers.html", rows=rows, q=q, segment=segment, segments=segs)


@router.get("/customers/{customer_id}")
def customer_detail(request: Request, customer_id: int):
    with db.connect() as conn:
        c = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not c:
            return RedirectResponse("/admin/customers", status_code=303)
        pred = conn.execute("SELECT p.*, pr.name AS product_name FROM predictions p "
                            "JOIN products pr ON pr.id=p.product_id WHERE customer_id=?", (customer_id,)).fetchone()
        hist = conn.execute(
            "SELECT o.*, p.name AS product_name FROM orders o JOIN products p ON p.id=o.product_id "
            "WHERE o.customer_id=? ORDER BY COALESCE(o.delivery_date,o.requested_date) DESC, o.id DESC LIMIT 60",
            (customer_id,)).fetchall()
        deliveries = [r["delivery_date"] for r in conn.execute(
            "SELECT delivery_date FROM orders WHERE customer_id=? AND status='delivered' ORDER BY delivery_date",
            (customer_id,))]
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(deliveries, deliveries[1:])]
    return render(request, "admin/customer.html", c=dict(c), pred=dict(pred) if pred else None,
                  hist=[dict(h) for h in hist], summary=analytics.customer_summary(customer_id),
                  gaps=gaps[-24:], avg_gap=(sum(gaps) / len(gaps)) if gaps else None)


@router.post("/customers/{customer_id}/reminders")
def customer_reminders(request: Request, customer_id: int, enabled: str = Form("0"), csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    with db.connect() as conn:
        conn.execute("UPDATE customers SET reminders_enabled=? WHERE id=?", (1 if enabled == "1" else 0, customer_id))
    flash(request, "Reminder setting updated.")
    return _back(request, f"/admin/customers/{customer_id}")


@router.get("/orders")
def order_list(request: Request, status: str = Query("open")):
    where = {"open": "o.status IN ('booked','confirmed')", "delivered": "o.status='delivered'",
             "unpaid": "o.status='delivered' AND o.payment_status='unpaid'",
             "cancelled": "o.status='cancelled'", "all": "1=1"}.get(status, "1=1")
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT o.*, c.business_name, c.credit_days, p.name AS product_name
                FROM orders o JOIN customers c ON c.id=o.customer_id JOIN products p ON p.id=o.product_id
                WHERE {where} ORDER BY COALESCE(o.delivery_date, o.requested_date) DESC, o.id DESC LIMIT 200""").fetchall()
    return render(request, "admin/orders.html", rows=[dict(r) for r in rows], status=status,
                  today=date.today().isoformat())


@router.post("/orders/{order_id}/{action}")
def order_action(request: Request, order_id: int, action: str, csrf_token: str = Form(""),
                 delivery_date: str = Form("")):
    check_csrf(request, csrf_token)
    try:
        flash(request, orders.set_status(order_id, action, delivery_date or None))
    except orders.OrderError as exc:
        flash(request, str(exc), "err")
    return _back(request, "/admin/orders")


@router.get("/receivables")
def receivables(request: Request):
    with db.connect() as conn:
        r = analytics.receivables(conn)
    return render(request, "admin/receivables.html", r=r)


@router.get("/model")
def model_page(request: Request):
    with db.connect() as conn:
        counts = dict(conn.execute(
            "SELECT (SELECT COUNT(*) FROM customers) AS customers, "
            "(SELECT COUNT(*) FROM orders WHERE status='delivered') AS orders, "
            "(SELECT COUNT(*) FROM customers WHERE is_synthetic=1) AS synthetic,"
            "(SELECT COUNT(*) FROM predictions WHERE method='ml') AS ml_preds").fetchone())
    return render(request, "admin/model.html", m=ml.load_metrics(), counts=counts)


@router.post("/model/retrain")
def retrain(request: Request, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    if not _train_lock.acquire(blocking=False):
        flash(request, "Training is already running.", "err")
        return RedirectResponse("/admin/model", status_code=303)
    try:
        m = ml.train()
        ml.refresh_predictions()
        flash(request, f"Model retrained. Hold-out error: {m['mae_days']} days.")
    except RuntimeError as exc:
        flash(request, str(exc), "err")
    finally:
        _train_lock.release()
    return RedirectResponse("/admin/model", status_code=303)


@router.post("/model/regenerate")
def regenerate(request: Request, csrf_token: str = Form(""), confirm: str = Form("")):
    check_csrf(request, csrf_token)
    if confirm != "REPLACE":
        flash(request, "Type REPLACE to confirm. This deletes all synthetic customers and their orders.", "err")
        return RedirectResponse("/admin/model", status_code=303)
    if not _train_lock.acquire(blocking=False):
        flash(request, "Training is already running.", "err")
        return RedirectResponse("/admin/model", status_code=303)
    try:
        s = synth.generate()
        m = ml.train()
        ml.refresh_predictions()
        flash(request, f"Generated {s['customers']} synthetic customers / {s['orders']} orders and retrained "
                       f"(hold-out error {m['mae_days']} days).")
    except RuntimeError as exc:
        flash(request, str(exc), "err")
    finally:
        _train_lock.release()
    return RedirectResponse("/admin/model", status_code=303)
