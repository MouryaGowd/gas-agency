"""Restock-date prediction.

Task: given a customer's order history up to (and including) order k, predict the number
of days until order k+1. Model: gradient boosting on interval/quantity/seasonality
features. It is evaluated on a chronological hold-out against two naive baselines
(segment average and the customer's own mean interval), and the hold-out residuals give
an honest prediction window (10th-90th percentile of the error).

Predicted restock date = last delivery date + predicted interval.
"""
import json
from datetime import date, datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from . import config, db
from .constants import SEGMENT_NAMES, SEGMENTS

MIN_HISTORY = 3  # delivered orders needed before the model is used for a customer
FEATURES = (
    ["last_int", "prev_int", "prev2_int", "mean_int", "ewm_int", "std_int", "last_qty", "mean_qty",
     "n_orders", "tenure_days", "last_dow", "last_month", "seg_interval"]
    + [f"seg_{s}" for s in SEGMENT_NAMES]
)


def _features(hist: pd.DataFrame, segment: str) -> dict | None:
    """hist: delivered orders for one customer, sorted by date (>= MIN_HISTORY rows)."""
    dates = pd.to_datetime(hist["delivery_date"]).reset_index(drop=True)
    ints = dates.diff().dt.days.dropna().to_numpy(dtype=float)
    if len(ints) < MIN_HISTORY - 1:
        return None
    qty = hist["qty"].to_numpy(dtype=float)
    last = dates.iloc[-1]
    row = {
        "last_int": ints[-1],
        "prev_int": ints[-2],
        "prev2_int": ints[-3] if len(ints) >= 3 else ints[-2],
        "mean_int": ints.mean(),
        "ewm_int": pd.Series(ints).ewm(alpha=0.5).mean().iloc[-1],
        "std_int": ints.std() if len(ints) > 1 else 0.0,
        "last_qty": qty[-1],
        "mean_qty": qty.mean(),
        "n_orders": len(hist),
        "tenure_days": (last - dates.iloc[0]).days,
        "last_dow": last.day_of_week,
        "last_month": last.month,
        "seg_interval": SEGMENTS[segment]["interval"],
    }
    for s in SEGMENT_NAMES:
        row[f"seg_{s}"] = 1.0 if s == segment else 0.0
    return row


def load_delivered() -> pd.DataFrame:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT o.customer_id, o.delivery_date, o.qty, o.product_id, c.segment
               FROM orders o JOIN customers c ON c.id = o.customer_id
               WHERE o.status='delivered' AND o.delivery_date IS NOT NULL
               ORDER BY o.customer_id, o.delivery_date, o.id"""
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def _training_table(df: pd.DataFrame) -> pd.DataFrame:
    recs = []
    for cid, g in df.groupby("customer_id"):
        g = g.reset_index(drop=True)
        segment = g["segment"].iloc[0]
        for k in range(MIN_HISTORY, len(g)):
            f = _features(g.iloc[:k], segment)
            if f is None:
                continue
            gap = (pd.to_datetime(g.loc[k, "delivery_date"]) - pd.to_datetime(g.loc[k - 1, "delivery_date"])).days
            f.update(target=float(gap), customer_id=cid, as_of=g.loc[k - 1, "delivery_date"],
                     segment=segment)
            recs.append(f)
    return pd.DataFrame(recs)


def train() -> dict:
    df = load_delivered()
    if df.empty:
        raise RuntimeError("No delivered orders to train on. Generate the synthetic data first.")
    table = _training_table(df).sort_values("as_of").reset_index(drop=True)
    if len(table) < 100:
        raise RuntimeError(f"Only {len(table)} training rows; need at least 100.")

    cut = int(len(table) * 0.8)  # chronological split: never train on the future
    tr, te = table.iloc[:cut], table.iloc[cut:]

    def fit(data):
        m = GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3,
                                      subsample=0.8, loss="absolute_error", random_state=7)
        return m.fit(data[FEATURES], data["target"])

    model = fit(tr)
    pred = model.predict(te[FEATURES])
    err = te["target"].to_numpy() - pred
    mae = float(np.mean(np.abs(err)))
    base_seg = float(np.mean(np.abs(te["target"] - te["seg_interval"])))
    base_own = float(np.mean(np.abs(te["target"] - te["mean_int"])))
    base_last = float(np.mean(np.abs(te["target"] - te["last_int"])))
    within2 = float(np.mean(np.abs(err) <= 2))
    lo, hi = (float(np.quantile(err, 0.10)), float(np.quantile(err, 0.90)))

    final = fit(table)  # refit on everything for production use
    metrics = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "algorithm": "GradientBoostingRegressor (MAE loss)",
        "train_rows": int(len(tr)), "test_rows": int(len(te)), "total_rows": int(len(table)),
        "mae_days": round(mae, 2),
        "baseline_segment_mae": round(base_seg, 2),
        "baseline_own_mean_mae": round(base_own, 2),
        "baseline_last_interval_mae": round(base_last, 2),
        "improvement_vs_own_mean_pct": round((1 - mae / base_own) * 100, 1),
        "within_2_days_pct": round(within2 * 100, 1),
        "window_low_offset": round(lo, 2), "window_high_offset": round(hi, 2),
        "importances": sorted(
            ({"feature": f, "importance": round(float(i), 4)}
             for f, i in zip(FEATURES, final.feature_importances_)),
            key=lambda x: -x["importance"])[:8],
    }
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "lo": lo, "hi": hi}, config.MODEL_PATH)
    config.METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def load_metrics() -> dict | None:
    try:
        return json.loads(config.METRICS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def refresh_predictions(customer_id: int | None = None) -> dict:
    """Recompute the next-restock prediction for every customer (or just one) and store it."""
    bundle = joblib.load(config.MODEL_PATH) if config.MODEL_PATH.exists() else None
    df = load_delivered()
    n_model = n_fallback = 0
    now = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        if customer_id is None:
            customers = conn.execute("SELECT id, segment FROM customers").fetchall()
            conn.execute("DELETE FROM predictions")
        else:
            customers = conn.execute(
                "SELECT id, segment FROM customers WHERE id=?", (customer_id,)).fetchall()
            conn.execute("DELETE FROM predictions WHERE customer_id=?", (customer_id,))
        for c in customers:
            g = df[df["customer_id"] == c["id"]].reset_index(drop=True) if not df.empty else df
            if g.empty:
                continue
            last_date = date.fromisoformat(g["delivery_date"].iloc[-1])
            feats = _features(g, c["segment"]) if len(g) >= MIN_HISTORY else None
            if bundle and feats:
                interval = float(bundle["model"].predict(pd.DataFrame([feats])[FEATURES])[0])
                lo, hi = bundle["lo"], bundle["hi"]
                method = "ml"
                n_model += 1
            else:
                ints = pd.to_datetime(g["delivery_date"]).diff().dt.days.dropna()
                interval = float(ints.mean()) if len(ints) else float(SEGMENTS[c["segment"]]["interval"])
                lo, hi, method = -3.0, 3.0, "heuristic"
                n_fallback += 1
            interval = max(2.0, interval)
            pdate = last_date + timedelta(days=round(interval))
            qty = int(max(1, round(g["qty"].tail(4).mean())))
            product_id = int(g["product_id"].mode().iloc[0])
            conn.execute(
                """INSERT INTO predictions (customer_id, last_order_date, predicted_date, interval_days,
                   window_low, window_high, predicted_qty, product_id, method, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (c["id"], last_date.isoformat(), pdate.isoformat(), round(interval, 1),
                 (pdate + timedelta(days=round(lo))).isoformat(),
                 (pdate + timedelta(days=round(hi))).isoformat(), qty, product_id, method, now))
    return {"model": n_model, "heuristic": n_fallback}
