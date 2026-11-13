"""Order creation / lifecycle shared by the customer portal, booking links and admin."""
from datetime import date, timedelta

from . import db, ml

MAX_QTY = 100
MAX_ADVANCE_DAYS = 60


class OrderError(ValueError):
    pass


def validate(qty: int, requested: str) -> date:
    if not 1 <= qty <= MAX_QTY:
        raise OrderError(f"Quantity must be between 1 and {MAX_QTY}.")
    try:
        d = date.fromisoformat(requested)
    except ValueError:
        raise OrderError("Please choose a valid delivery date.") from None
    if d < date.today() or d > date.today() + timedelta(days=MAX_ADVANCE_DAYS):
        raise OrderError(f"Delivery date must be within the next {MAX_ADVANCE_DAYS} days.")
    return d


def open_order(conn, customer_id: int):
    return conn.execute("SELECT * FROM orders WHERE customer_id=? AND status IN ('booked','confirmed') "
                        "ORDER BY id DESC LIMIT 1", (customer_id,)).fetchone()


def create_booking(customer_id: int, product_id: int, qty: int, requested: str, source: str,
                   notes: str = "") -> int:
    d = validate(qty, requested)
    with db.connect() as conn:
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        prod = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not cust or not prod:
            raise OrderError("Unknown customer or product.")
        if open_order(conn, customer_id):
            raise OrderError("You already have an open booking. Cancel it first to make a new one.")
        cur = conn.execute(
            """INSERT INTO orders (customer_id, product_id, qty, unit_price, unit_cost, requested_date,
               status, source, address, notes) VALUES (?,?,?,?,?,?,'booked',?,?,?)""",
            (customer_id, product_id, qty, prod["price"], prod["cost"], d.isoformat(), source,
             cust["address"], notes[:300]))
        return cur.lastrowid


def set_status(order_id: int, action: str, when: str | None = None) -> str:
    """action: confirm | deliver | cancel | paid. Returns a human message."""
    customer_id = None
    with db.connect() as conn:
        o = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            raise OrderError("Order not found.")
        today = date.today().isoformat()
        if action == "confirm" and o["status"] == "booked":
            conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (order_id,))
            return f"Order #{order_id} confirmed."
        if action == "deliver" and o["status"] in ("booked", "confirmed"):
            try:
                dd = date.fromisoformat(when) if when else date.today()
            except ValueError:
                raise OrderError("Invalid delivery date.") from None
            if dd > date.today():
                raise OrderError("Delivery date cannot be in the future.")
            conn.execute("UPDATE orders SET status='delivered', delivery_date=? WHERE id=?",
                         (dd.isoformat(), order_id))
            customer_id = o["customer_id"]
            msg = f"Order #{order_id} marked delivered."
        elif action == "cancel" and o["status"] in ("booked", "confirmed"):
            conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
            return f"Order #{order_id} cancelled."
        elif action == "paid" and o["status"] == "delivered" and o["payment_status"] == "unpaid":
            conn.execute("UPDATE orders SET payment_status='paid', paid_date=? WHERE id=?", (today, order_id))
            return f"Order #{order_id} marked paid."
        else:
            raise OrderError(f"Cannot '{action}' an order that is {o['status']}/{o['payment_status']}.")
    ml.refresh_predictions(customer_id)  # a delivery changes that customer's next restock date
    return msg
