import sqlite3
from contextlib import contextmanager

from . import config
from .constants import PRODUCTS

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'customer')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    business_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    segment TEXT NOT NULL,
    credit_days INTEGER NOT NULL DEFAULT 0,
    reminders_enabled INTEGER NOT NULL DEFAULT 1,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    size_kg REAL NOT NULL,
    price REAL NOT NULL,
    cost REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty INTEGER NOT NULL CHECK (qty > 0),
    unit_price REAL NOT NULL,
    unit_cost REAL NOT NULL,
    requested_date TEXT NOT NULL,
    delivery_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('booked', 'confirmed', 'delivered', 'cancelled')),
    payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'paid')),
    paid_date TEXT,
    source TEXT NOT NULL DEFAULT 'web',
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_cust ON orders(customer_id, delivery_date);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE TABLE IF NOT EXISTS predictions (
    customer_id INTEGER PRIMARY KEY REFERENCES customers(id),
    last_order_date TEXT NOT NULL,
    predicted_date TEXT NOT NULL,
    interval_days REAL NOT NULL,
    window_low TEXT NOT NULL,
    window_high TEXT NOT NULL,
    predicted_qty INTEGER NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    method TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    last_order_date TEXT NOT NULL,
    predicted_date TEXT NOT NULL,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_html TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rem_cust ON reminders(customer_id, last_order_date);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        if not db.execute("SELECT 1 FROM products LIMIT 1").fetchone():
            db.executemany(
                "INSERT INTO products (name, size_kg, price, cost) VALUES (?, ?, ?, ?)", PRODUCTS
            )
