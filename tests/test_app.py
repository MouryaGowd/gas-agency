"""End-to-end tests against a throwaway data directory. Run: .venv/bin/pytest -q"""
import os
import re
import tempfile
from datetime import date, timedelta

import pytest

os.environ["GAS_DATA_DIR"] = tempfile.mkdtemp(prefix="gas_test_")
os.environ["AUTO_REMINDERS"] = "0"
os.environ["SMTP_HOST"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, reminders  # noqa: E402
from app.main import app  # noqa: E402
from app.security import make_booking_token  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs startup: synthetic data + model training
        yield c


def csrf(client, url):
    html = client.get(url).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client, role="admin"):
    url, email, pw = (("/admin/login", config.ADMIN_EMAIL, config.ADMIN_PASSWORD) if role == "admin"
                      else ("/login", "customer001@example.com", "customer123"))
    r = client.post(url, data={"email": email, "password": pw, "csrf_token": csrf(client, url)},
                    follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    return r


def test_bootstrap_created_data_and_model(client):
    assert config.MODEL_PATH.exists()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 150
        assert conn.execute("SELECT COUNT(*) FROM predictions WHERE method='ml'").fetchone()[0] == 150
        names = {r[0]: r[1] for r in conn.execute("SELECT name, price FROM products")}
        assert names == {"19 kg": 2900, "33 kg": 4500}


def test_admin_pages_require_login(client):
    client.cookies.clear()
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


def test_customer_cannot_access_admin(client):
    client.cookies.clear()
    login(client, "customer")
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"


def test_wrong_password_rejected(client):
    client.cookies.clear()
    r = client.post("/admin/login", data={"email": config.ADMIN_EMAIL, "password": "nope",
                                          "csrf_token": csrf(client, "/admin/login")})
    assert r.status_code == 401 and "Incorrect" in r.text


def test_csrf_required(client):
    client.cookies.clear()
    r = client.post("/login", data={"email": "x@y.z", "password": "p", "csrf_token": "bad"})
    assert r.status_code == 403


@pytest.mark.parametrize("path", ["/admin", "/admin?days=7", "/admin?days=365", "/admin/forecast",
                                  "/admin/forecast?show=due", "/admin/orders", "/admin/orders?status=unpaid",
                                  "/admin/customers", "/admin/customers?q=Hotel", "/admin/customers/1",
                                  "/admin/receivables", "/admin/reminders", "/admin/model"])
def test_admin_pages_render(client, path):
    client.cookies.clear()
    login(client)
    r = client.get(path)
    assert r.status_code == 200, r.text[:500]


def test_reminder_flow_and_booking_link(client):
    client.cookies.clear()
    login(client)
    due = reminders.due_customers()
    assert due, "synthetic data should always have someone due"
    r = client.post("/admin/reminders/send-due", data={"csrf_token": csrf(client, "/admin/forecast")})
    assert r.status_code == 200 and "saved to outbox" in r.text
    assert reminders.due_customers() == []          # each cycle is reminded only once
    assert list(config.OUTBOX_DIR.glob("*.eml"))

    with db.connect() as conn:
        rem = conn.execute("SELECT * FROM reminders ORDER BY id LIMIT 1").fetchone()
    token = re.search(r"/book/([A-Za-z0-9_.\-]+)", rem["body_html"]).group(1)
    client.cookies.clear()                            # booking link works without logging in
    page = client.get(f"/book/{token}")
    assert page.status_code == 200 and "Book your refill" in page.text
    tok = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    pid = re.search(r'<option value="(\d+)" selected', page.text).group(1)
    r = client.post(f"/book/{token}", data={"product_id": pid, "qty": 2, "csrf_token": tok,
                                            "requested_date": (date.today() + timedelta(days=1)).isoformat()})
    assert r.status_code == 200 and "Booking received" in r.text
    # second use shows the existing booking instead of double-booking
    assert "already have an open booking" in client.get(f"/book/{token}").text


def test_tampered_booking_link_rejected(client):
    token = make_booking_token(1, 2, 3)
    assert client.get(f"/book/{token[:-2]}xx").status_code == 410


def test_customer_portal_book_cancel(client):
    client.cookies.clear()
    login(client, "customer")
    page = client.get("/portal")
    assert page.status_code == 200 and "Next refill expected" in page.text
    tok = csrf(client, "/portal")
    with db.connect() as conn:  # make sure customer 1 has no open booking from other tests
        conn.execute("UPDATE orders SET status='cancelled' WHERE customer_id=1 AND status IN ('booked','confirmed')")
    bad = client.post("/portal/book", data={"product_id": 2, "qty": 0, "csrf_token": tok,
                                            "requested_date": date.today().isoformat()})
    assert "Quantity must be" in bad.text
    ok = client.post("/portal/book", data={"product_id": 2, "qty": 3, "csrf_token": tok,
                                           "requested_date": date.today().isoformat()})
    assert "Booking #" in ok.text
    oid = int(re.search(r"Booking #(\d+)", ok.text).group(1))
    r = client.post(f"/portal/cancel/{oid}", data={"csrf_token": tok})
    assert "cancelled" in r.text


def test_customer_cannot_cancel_others_order(client):
    with db.connect() as conn:
        other = conn.execute("INSERT INTO orders (customer_id, product_id, qty, unit_price, unit_cost, "
                             "requested_date, status) VALUES (2, 2, 1, 1850, 1660, ?, 'booked')",
                             (date.today().isoformat(),)).lastrowid
    client.cookies.clear()
    login(client, "customer")
    r = client.post(f"/portal/cancel/{other}", data={"csrf_token": csrf(client, "/portal")})
    assert "Order not found" in r.text
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM orders WHERE id=?", (other,)).fetchone()[0] == "booked"


def test_admin_delivery_updates_prediction(client):
    client.cookies.clear()
    login(client)
    with db.connect() as conn:
        o = conn.execute("SELECT * FROM orders WHERE status IN ('booked','confirmed') LIMIT 1").fetchone()
    tok = csrf(client, "/admin/orders")
    client.post(f"/admin/orders/{o['id']}/confirm", data={"csrf_token": tok})
    client.post(f"/admin/orders/{o['id']}/deliver", data={"csrf_token": tok,
                                                          "delivery_date": date.today().isoformat()})
    with db.connect() as conn:
        p = conn.execute("SELECT * FROM predictions WHERE customer_id=?", (o["customer_id"],)).fetchone()
    assert p["last_order_date"] == date.today().isoformat()
    assert p["predicted_date"] > date.today().isoformat()
    r = client.post(f"/admin/orders/{o['id']}/paid", data={"csrf_token": tok})
    assert "marked paid" in r.text


def test_register_new_customer(client):
    client.cookies.clear()
    tok = csrf(client, "/register")
    r = client.post("/register", data={"business_name": "Test Dhaba", "contact_name": "T", "email": "new@shop.in",
                                       "phone": "", "address": "1 Road", "segment": "Restaurant",
                                       "password": "longenough", "csrf_token": tok})
    assert r.status_code == 200 and "Test Dhaba" in r.text
    dup = client.post("/register", data={"business_name": "X", "contact_name": "T", "email": "new@shop.in",
                                         "address": "1", "segment": "Restaurant", "password": "longenough",
                                         "csrf_token": csrf(client, "/register")})
    assert "already exists" in dup.text


def test_retrain(client):
    client.cookies.clear()
    login(client)
    r = client.post("/admin/model/retrain", data={"csrf_token": csrf(client, "/admin/model")})
    assert "Model retrained" in r.text
