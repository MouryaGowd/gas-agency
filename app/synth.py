"""Synthetic commercial-gas customers and ~18 months of order history.

Each customer has its own refill rhythm (segment baseline x a personal factor), weekday
habits (deliveries skip Sundays), seasonality (catering/hotels peak Oct-Feb wedding and
festival season), a slow growth/decline trend and random noise. That gives the ML model
real structure to learn while staying noisy enough that the prediction isn't trivial.
"""
import random
from datetime import date, timedelta

from . import db
from .constants import SEGMENTS, SEGMENT_NAMES
from .security import hash_password

HISTORY_DAYS = 730
DEFAULT_CUSTOMERS = 150
DEMO_CUSTOMER_PASSWORD = "customer123"

_PREFIX = ["Sri", "Royal", "Annapurna", "Spice", "Green", "Golden", "Blue", "Lakshmi", "City",
           "Madhuri", "Taj", "Urban", "Sagar", "Krishna", "Metro", "Classic", "Fresh", "Grand",
           "Ruchi", "Delhi", "Udupi", "Coastal", "Heritage", "Sunrise", "Pearl"]
_SUFFIX = {
    "Restaurant": ["Restaurant", "Dhaba", "Kitchen", "Bistro", "Biryani House"],
    "Hotel": ["Residency", "Inn", "Hotel", "Lodge", "Grand Hotel"],
    "Bakery": ["Bakery", "Sweets & Bakes", "Cake House", "Bake Shop"],
    "Catering": ["Caterers", "Catering Services", "Events Kitchen", "Banquets"],
    "Canteen / Hostel": ["College Canteen", "Hostel Mess", "Corporate Canteen", "Mess Hall"],
    "Street Food": ["Chaat Corner", "Tiffin Centre", "Juice & Snacks", "Fast Food Stall"],
    "Industrial": ["Industries", "Foods Pvt Ltd", "Processing Unit", "Fabricators"],
}
_FIRST = ["Ravi", "Suresh", "Anita", "Kiran", "Meena", "Rahul", "Priya", "Arjun", "Sunita",
          "Vijay", "Deepa", "Manoj", "Lakshmi", "Imran", "Farhan", "Neha", "Ramesh", "Geeta"]
_LAST = ["Kumar", "Reddy", "Sharma", "Patel", "Naidu", "Rao", "Khan", "Gupta", "Iyer", "Singh"]


def _seasonal(segment: str, d: date) -> float:
    """>1 means consumption is higher than usual (so refill interval is shorter)."""
    if segment in ("Catering", "Hotel"):
        return 1.35 if d.month in (10, 11, 12, 1, 2) else (0.85 if d.month in (6, 7) else 1.0)
    if segment == "Canteen / Hostel":
        return 0.6 if d.month in (5, 6) else 1.0  # vacations
    if segment == "Bakery":
        return 1.3 if d.month in (12, 1) else 1.0  # festive baking
    return 1.0


def generate(n_customers: int = DEFAULT_CUSTOMERS, seed: int = 42, today: date | None = None,
             noise_scale: float = 1.0) -> dict:
    """noise_scale multiplies each customer's refill-gap noise (1.0 = the default demo data)."""
    rng = random.Random(seed)
    today = today or date.today()
    start_floor = today - timedelta(days=HISTORY_DAYS)
    pw_hash = hash_password(DEMO_CUSTOMER_PASSWORD)

    with db.connect() as conn:
        conn.execute("DELETE FROM reminders WHERE customer_id IN (SELECT id FROM customers WHERE is_synthetic=1)")
        conn.execute("DELETE FROM predictions WHERE customer_id IN (SELECT id FROM customers WHERE is_synthetic=1)")
        conn.execute("DELETE FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE is_synthetic=1)")
        user_ids = [r[0] for r in conn.execute(
            "SELECT user_id FROM customers WHERE is_synthetic=1 AND user_id IS NOT NULL")]
        conn.execute("DELETE FROM customers WHERE is_synthetic=1")
        conn.executemany("DELETE FROM users WHERE id=?", [(u,) for u in user_ids])

        products = {r["name"]: r for r in conn.execute("SELECT * FROM products")}
        weights = [4, 3, 3, 3, 2, 2, 1.5]
        n_orders = 0

        for i in range(n_customers):
            segment = rng.choices(SEGMENT_NAMES, weights=weights)[0]
            seg = SEGMENTS[segment]
            name = f"{rng.choice(_PREFIX)} {rng.choice(_SUFFIX[segment])}"
            contact = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
            email = f"customer{i + 1:03d}@example.com"
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'customer')",
                (email, pw_hash))
            uid = cur.lastrowid
            cur = conn.execute(
                """INSERT INTO customers (user_id, business_name, contact_name, email, phone, address,
                   segment, credit_days, is_synthetic) VALUES (?,?,?,?,?,?,?,?,1)""",
                (uid, name, contact, email, f"9{rng.randint(100000000, 999999999)}",
                 f"{rng.randint(1, 120)}, {rng.choice(['MG Road', 'Station Road', 'Market Street', 'Ring Road', 'Industrial Area'])}",
                 segment, seg["credit"]))
            cid = cur.lastrowid

            # personal behaviour
            personal = rng.uniform(0.7, 1.4)
            base_interval = seg["interval"] * personal
            base_qty = max(1.0, seg["qty"] * rng.uniform(0.6, 1.6))
            trend = rng.uniform(-0.15, 0.25)           # consumption change over the history
            regularity = rng.uniform(0.05, 0.22) * noise_scale  # relative noise
            pays_late = rng.random() < 0.2
            product = products[seg["product"]]
            if rng.random() < 0.2 and seg["product"] == "19 kg":  # bigger kitchens use 33 kg instead
                product = products["33 kg"]
                base_qty = max(1.0, base_qty * 0.6)

            d = start_floor + timedelta(days=rng.randint(0, int(base_interval)))
            while d <= today:
                if d.weekday() == 6:
                    d += timedelta(days=1)
                    continue
                qty = max(1, round(rng.gauss(base_qty, base_qty * 0.2)))
                status = "delivered"
                pay_status, paid_date = "paid", None
                gap = max(0, round(rng.gauss(seg["credit"] * (1.6 if pays_late else 0.6),
                                             3 + seg["credit"] * 0.2)))
                if seg["credit"] == 0:
                    paid_date = d
                else:
                    paid_date = d + timedelta(days=gap)
                if paid_date and paid_date > today:
                    pay_status, paid_date = "unpaid", None
                conn.execute(
                    """INSERT INTO orders (customer_id, product_id, qty, unit_price, unit_cost,
                       requested_date, delivery_date, status, payment_status, paid_date, source, address)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, product["id"], qty, product["price"], product["cost"], d.isoformat(),
                     d.isoformat(), status, pay_status, paid_date.isoformat() if paid_date else None,
                     rng.choice(["web", "phone", "phone", "whatsapp"]), ""))
                n_orders += 1

                progress = (d - start_floor).days / HISTORY_DAYS
                rate = _seasonal(segment, d) * (1 + trend * progress)
                interval = base_interval / max(rate, 0.3)
                interval *= max(0.4, rng.gauss(1.0, regularity))
                d += timedelta(days=max(2, round(interval)))

        # keep only history up to today; account for the customer's own address
        conn.execute("UPDATE orders SET address=(SELECT address FROM customers c WHERE c.id=orders.customer_id) WHERE address=''")
    return {"customers": n_customers, "orders": n_orders}
