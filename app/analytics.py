"""Admin dashboard numbers. Revenue is recognised on delivery date for delivered orders."""
from datetime import date, timedelta

from . import db

DELIVERED = "o.status='delivered'"


def _one(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()


def _period(conn, start: date, end: date) -> dict:
    r = _one(conn, f"""
        SELECT COALESCE(SUM(o.qty*o.unit_price),0) AS revenue,
               COALESCE(SUM(o.qty*o.unit_cost),0)  AS cost,
               COALESCE(SUM(o.qty),0)              AS cylinders,
               COUNT(*)                            AS orders,
               COUNT(DISTINCT o.customer_id)       AS customers
        FROM orders o WHERE {DELIVERED} AND o.delivery_date BETWEEN ? AND ?""",
             (start.isoformat(), end.isoformat()))
    d = dict(r)
    d["profit"] = d["revenue"] - d["cost"]
    d["margin_pct"] = d["profit"] / d["revenue"] * 100 if d["revenue"] else 0
    d["avg_per_order"] = d["cylinders"] / d["orders"] if d["orders"] else 0
    d["avg_order_value"] = d["revenue"] / d["orders"] if d["orders"] else 0
    d["revenue_per_cylinder"] = d["revenue"] / d["cylinders"] if d["cylinders"] else 0
    days = max((end - start).days + 1, 1)
    months = days / 30.4
    d["avg_per_customer_month"] = d["cylinders"] / d["customers"] / months if d["customers"] else 0
    return d


def _pct(new, old):
    return None if not old else (new - old) / old * 100


def monthly(conn, months: int = 12, today: date | None = None) -> list[dict]:
    today = today or date.today()
    first = date(today.year, today.month, 1)
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    rows = conn.execute(f"""
        SELECT substr(o.delivery_date,1,7) AS m,
               SUM(o.qty*o.unit_price) AS revenue, SUM(o.qty*o.unit_cost) AS cost, SUM(o.qty) AS cylinders
        FROM orders o WHERE {DELIVERED} AND o.delivery_date >= ? GROUP BY m""",
                        (first.isoformat(),)).fetchall()
    by = {r["m"]: r for r in rows}
    out, cur = [], first
    for _ in range(months):
        key = cur.strftime("%Y-%m")
        r = by.get(key)
        rev = r["revenue"] if r else 0
        cost = r["cost"] if r else 0
        out.append({"month": cur.strftime("%b %y"), "revenue": rev, "cost": cost,
                    "profit": rev - cost, "cylinders": r["cylinders"] if r else 0})
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def receivables(conn, today: date | None = None) -> dict:
    today = today or date.today()
    rows = conn.execute(f"""
        SELECT o.id, o.customer_id, c.business_name, o.delivery_date, c.credit_days,
               o.qty*o.unit_price AS amount
        FROM orders o JOIN customers c ON c.id=o.customer_id
        WHERE {DELIVERED} AND o.payment_status='unpaid' ORDER BY o.delivery_date""").fetchall()
    buckets = {"Not yet due": 0.0, "1-30 days late": 0.0, "31-60 days late": 0.0, "60+ days late": 0.0}
    per_customer: dict[int, dict] = {}
    total = overdue = 0.0
    for r in rows:
        due = date.fromisoformat(r["delivery_date"]) + timedelta(days=r["credit_days"])
        late = (today - due).days
        key = ("Not yet due" if late <= 0 else "1-30 days late" if late <= 30
               else "31-60 days late" if late <= 60 else "60+ days late")
        buckets[key] += r["amount"]
        total += r["amount"]
        if late > 0:
            overdue += r["amount"]
        pc = per_customer.setdefault(r["customer_id"], {
            "customer_id": r["customer_id"], "business_name": r["business_name"],
            "outstanding": 0.0, "overdue": 0.0, "oldest_days_late": -9999, "invoices": 0})
        pc["outstanding"] += r["amount"]
        pc["invoices"] += 1
        if late > 0:
            pc["overdue"] += r["amount"]
        pc["oldest_days_late"] = max(pc["oldest_days_late"], late)
    top = sorted(per_customer.values(), key=lambda x: (-x["overdue"], -x["outstanding"]))
    return {"total": total, "overdue": overdue, "buckets": buckets, "customers": top}


def dashboard(range_days: int = 30, today: date | None = None) -> dict:
    today = today or date.today()
    start = today - timedelta(days=range_days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=range_days - 1)
    with db.connect() as conn:
        cur = _period(conn, start, today)
        prev = _period(conn, prev_start, prev_end)
        seg = conn.execute(f"""
            SELECT c.segment, SUM(o.qty*o.unit_price) AS revenue, SUM(o.qty) AS cylinders
            FROM orders o JOIN customers c ON c.id=o.customer_id
            WHERE {DELIVERED} AND o.delivery_date BETWEEN ? AND ?
            GROUP BY c.segment ORDER BY revenue DESC""",
                            (start.isoformat(), today.isoformat())).fetchall()
        top = conn.execute(f"""
            SELECT c.id, c.business_name, c.segment, SUM(o.qty*o.unit_price) AS revenue,
                   SUM(o.qty) AS cylinders, COUNT(*) AS orders
            FROM orders o JOIN customers c ON c.id=o.customer_id
            WHERE {DELIVERED} AND o.delivery_date BETWEEN ? AND ?
            GROUP BY c.id ORDER BY revenue DESC LIMIT 10""",
                           (start.isoformat(), today.isoformat())).fetchall()
        recv = receivables(conn, today)
        paid = _one(conn, """SELECT AVG(julianday(paid_date)-julianday(delivery_date)) AS d
                             FROM orders WHERE payment_status='paid' AND paid_date IS NOT NULL
                             AND delivery_date BETWEEN ? AND ?""",
                    ((today - timedelta(days=180)).isoformat(), today.isoformat()))
        collected = _one(conn, "SELECT COALESCE(SUM(qty*unit_price),0) AS v FROM orders "
                               "WHERE payment_status='paid' AND paid_date BETWEEN ? AND ?",
                         (start.isoformat(), today.isoformat()))["v"]
        pipeline = _one(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(qty),0) AS q, "
                              "COALESCE(SUM(qty*unit_price),0) AS v FROM orders "
                              "WHERE status IN ('booked','confirmed')")
        stats = _one(conn, "SELECT COUNT(*) AS n FROM customers")
        horizon = (today + timedelta(days=7)).isoformat()
        due_soon = _one(conn, """SELECT COUNT(*) AS n FROM predictions p WHERE p.predicted_date BETWEEN ? AND ?
            AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=p.customer_id
                            AND o.status IN ('booked','confirmed'))""",
                        (today.isoformat(), horizon))["n"]
        overdue_restock = _one(conn, """SELECT COUNT(*) AS n FROM predictions p WHERE p.predicted_date < ?
            AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=p.customer_id
                            AND o.status IN ('booked','confirmed'))""", (today.isoformat(),))["n"]
        months = monthly(conn, 12, today)
    return {
        "range_days": range_days, "start": start, "end": today,
        "cur": cur, "prev": prev,
        "delta": {k: _pct(cur[k], prev[k]) for k in ("revenue", "profit", "cylinders", "orders")},
        "segments": [dict(r) for r in seg], "top": [dict(r) for r in top],
        "recv": recv, "avg_days_to_pay": paid["d"], "collected": collected,
        "pipeline": dict(pipeline), "customers_total": stats["n"],
        "due_soon": due_soon, "overdue_restock": overdue_restock, "months": months,
    }


def customer_summary(customer_id: int) -> dict:
    with db.connect() as conn:
        r = _one(conn, f"""
            SELECT COALESCE(SUM(o.qty*o.unit_price),0) AS revenue, COALESCE(SUM(o.qty),0) AS cylinders,
                   COUNT(*) AS orders, MIN(o.delivery_date) AS first_order, MAX(o.delivery_date) AS last_order
            FROM orders o WHERE {DELIVERED} AND o.customer_id=?""", (customer_id,))
        out = _one(conn, f"""SELECT COALESCE(SUM(qty*unit_price),0) AS v FROM orders o
                             WHERE {DELIVERED} AND payment_status='unpaid' AND customer_id=?""",
                   (customer_id,))["v"]
        return {**dict(r), "outstanding": out}
