"""Automated 'time to restock' emails with a signed one-click booking link."""
from datetime import date, timedelta
from html import escape

from . import config, db, mailer
from .security import make_booking_token

OPEN_ORDER = "SELECT 1 FROM orders o WHERE o.customer_id=p.customer_id AND o.status IN ('booked','confirmed')"


def _render(c, p, product, link: str) -> tuple[str, str, str]:
    pdate = date.fromisoformat(p["predicted_date"])
    when = pdate.strftime("%A, %d %b %Y")
    overdue = pdate < date.today()
    subject = (f"{config.BUSINESS_NAME}: time to restock your cylinders"
               if not overdue else f"{config.BUSINESS_NAME}: your cylinders may be running low")
    lead = (f"Based on your usage, your cylinders are expected to run out around <b>{escape(when)}</b>."
            if not overdue else "Based on your usage, you were due for a refill and may be running low.")
    name = escape(c["contact_name"])
    suggestion = f'{p["predicted_qty"]} &times; {escape(product["name"])} cylinder(s)'
    html = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#222">
<h2 style="margin:0 0 12px">{escape(config.BUSINESS_NAME)}</h2>
<p>Hello {name},</p>
<p>{lead}</p>
<p>Suggested refill: <b>{suggestion}</b> for {escape(c["business_name"])}.</p>
<p style="margin:24px 0"><a href="{link}" style="background:#1a5fb4;color:#fff;padding:12px 22px;
text-decoration:none;border-radius:6px;font-weight:bold">Book my refill</a></p>
<p style="font-size:13px;color:#666">The link is personal to you and expires in {config.BOOKING_LINK_DAYS} days.
You can change the quantity and date before confirming. To stop these emails, reply to this message.</p></div>"""
    text = (f"Hello {c['contact_name']},\n\n"
            f"{'Your cylinders are expected to run out around ' + when + '.' if not overdue else 'You were due for a refill and may be running low.'}\n"
            f"Suggested refill: {p['predicted_qty']} x {product['name']}\n\nBook here: {link}\n\n"
            f"(Link expires in {config.BOOKING_LINK_DAYS} days.)\n")
    return subject, html, text


def send_reminder(customer_id: int, force: bool = False) -> tuple[str, str]:
    """Send one reminder. Returns (status, detail). Skips if already sent for this restock cycle
    unless force=True."""
    with db.connect() as conn:
        c = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        p = conn.execute("SELECT * FROM predictions WHERE customer_id=?", (customer_id,)).fetchone()
        if not c or not p:
            return "skipped", "no customer or prediction"
        if not force:
            if not c["reminders_enabled"]:
                return "skipped", "reminders disabled for this customer"
            if conn.execute(f"SELECT 1 FROM predictions p WHERE p.customer_id=? AND EXISTS ({OPEN_ORDER})",
                            (customer_id,)).fetchone():
                return "skipped", "customer already has an open order"
            if conn.execute("SELECT 1 FROM reminders WHERE customer_id=? AND last_order_date=? "
                            "AND status IN ('sent','logged')", (customer_id, p["last_order_date"])).fetchone():
                return "skipped", "already reminded for this cycle"
        product = conn.execute("SELECT * FROM products WHERE id=?", (p["product_id"],)).fetchone()
        token = make_booking_token(customer_id, p["product_id"], p["predicted_qty"])
        link = f"{config.BASE_URL}/book/{token}"
        subject, html, text = _render(c, p, product, link)
        # send outside of an open write transaction would be nicer, but the log row needs the result
        status, detail = mailer.send_email(c["email"], subject, html, text)
        conn.execute(
            """INSERT INTO reminders (customer_id, last_order_date, predicted_date, to_email, subject,
               body_html, status, detail) VALUES (?,?,?,?,?,?,?,?)""",
            (customer_id, p["last_order_date"], p["predicted_date"], c["email"], subject, html, status, detail))
    return status, detail


def due_customers(today: date | None = None, within_days: int | None = None) -> list[int]:
    today = today or date.today()
    horizon = (today + timedelta(days=config.REMINDER_DAYS if within_days is None else within_days)).isoformat()
    with db.connect() as conn:
        rows = conn.execute(f"""
            SELECT p.customer_id FROM predictions p JOIN customers c ON c.id=p.customer_id
            WHERE c.reminders_enabled=1 AND p.predicted_date <= ?
              AND NOT EXISTS ({OPEN_ORDER})
              AND NOT EXISTS (SELECT 1 FROM reminders r WHERE r.customer_id=p.customer_id
                              AND r.last_order_date=p.last_order_date AND r.status IN ('sent','logged'))
            ORDER BY p.predicted_date""", (horizon,)).fetchall()
    return [r[0] for r in rows]


def send_all_due() -> dict:
    counts = {"sent": 0, "logged": 0, "failed": 0, "skipped": 0}
    for cid in due_customers():
        status, _ = send_reminder(cid)
        counts[status] = counts.get(status, 0) + 1
    return counts
