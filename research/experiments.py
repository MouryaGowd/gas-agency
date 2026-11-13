"""Reproduces every number and figure in the paper.

    .venv/bin/python research/experiments.py            # full run (about 10 minutes)
    .venv/bin/python research/experiments.py --quick    # 2 seeds, 2 noise levels (about 1 minute)

Writes research/results.json, research/results.tex (LaTeX macros + tables) and research/figures/*.pdf
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from app import config, db, ml, synth  # noqa: E402
from app.constants import SEGMENT_NAMES  # noqa: E402

QUICK = "--quick" in sys.argv
SEEDS = [1, 2] if QUICK else [1, 2, 3, 4, 5]
NOISE = [1.0, 2.0] if QUICK else [0.5, 1.0, 2.0, 3.0]
BASE_NOISE = 1.0
LEADS = [0, 1, 2, 3, 5, 7]
OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"
FIG.mkdir(exist_ok=True)

MODELS = ["Segment mean", "Own mean", "Last gap", "EWMA", "Ridge", "Random forest", "Gradient boosting"]
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#898781"


def point_to(directory: Path) -> None:
    config.DATA_DIR = directory
    config.DB_PATH = directory / "gas.db"
    config.MODEL_PATH = directory / "model.joblib"
    config.METRICS_PATH = directory / "metrics.json"


def fit_predict(name, tr, te):
    X_tr, y_tr, X_te = tr[ml.FEATURES], tr["target"], te[ml.FEATURES]
    if name == "Segment mean":
        return te["seg_interval"].to_numpy()
    if name == "Own mean":
        return te["mean_int"].to_numpy()
    if name == "Last gap":
        return te["last_int"].to_numpy()
    if name == "EWMA":
        return te["ewm_int"].to_numpy()
    if name == "Ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(X_tr, y_tr).predict(X_te)
    if name == "Random forest":
        return RandomForestRegressor(n_estimators=200, min_samples_leaf=5, random_state=7, n_jobs=-1
                                     ).fit(X_tr, y_tr).predict(X_te)
    # same hyper-parameters as app/ml.py
    return GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8,
                                     loss="absolute_error", random_state=7).fit(X_tr, y_tr).predict(X_te)


def run_one(seed: int, noise: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="gas_exp_") as tmp:
        point_to(Path(tmp))
        db.init_db()
        stats = synth.generate(150, seed=seed, noise_scale=noise)
        table = ml._training_table(ml.load_delivered()).sort_values("as_of").reset_index(drop=True)
    cut = int(len(table) * 0.8)  # chronological split
    tr, te = table.iloc[:cut], table.iloc[cut:]
    y = te["target"].to_numpy()
    res = {"orders": stats["orders"], "train": len(tr), "test": len(te), "mae": {}, "errors": {}}
    for m in MODELS:
        p = fit_predict(m, tr, te)
        res["mae"][m] = float(np.mean(np.abs(y - p)))
        res["errors"][m] = (y - p).tolist()  # positive = customer reordered later than predicted
    gb = np.array(res["errors"]["Gradient boosting"])
    res["gb_within2"] = float(np.mean(np.abs(gb) <= 2))
    res["gb_rmse"] = float(np.sqrt(np.mean(gb ** 2)))
    lo, hi = np.quantile(gb, 0.1), np.quantile(gb, 0.9)
    res["gb_bias"] = float(gb.mean())
    res["segments"] = {}
    for s in SEGMENT_NAMES:
        mask = (te["segment"] == s).to_numpy()
        if mask.sum() >= 20:
            res["segments"][s] = {
                "n": int(mask.sum()),
                "gb": float(np.mean(np.abs(gb[mask]))),
                "own": float(np.mean(np.abs(np.array(res["errors"]["Own mean"])[mask]))),
                "gap": float(te["target"][mask].mean()),
            }
    res["window_coverage_10_90"] = float(np.mean((gb >= lo) & (gb <= hi)))  # in-sample by construction
    res["importance"] = None
    if noise == BASE_NOISE and seed == SEEDS[0]:
        gbr = GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8,
                                        loss="absolute_error", random_state=7).fit(tr[ml.FEATURES], tr["target"])
        res["importance"] = dict(zip(ml.FEATURES, map(float, gbr.feature_importances_)))
    return res


def coverage(err: np.ndarray, lead: int) -> tuple[float, float]:
    """Reminder is sent `lead` days before the predicted date. Useful if sent before the customer reorders
    (err >= -lead). Returns (share of reminders that are useful, mean days of notice they give)."""
    ok = err >= -lead
    return float(ok.mean()), float((err[ok] + lead).mean()) if ok.any() else 0.0


def main() -> None:
    t0 = time.time()
    runs = {}
    for noise in NOISE:
        for seed in SEEDS:
            print(f"noise={noise} seed={seed} ...", flush=True)
            runs[(noise, seed)] = run_one(seed, noise)
    print(f"experiments done in {time.time() - t0:.0f}s")

    def agg(noise, f):
        v = np.array([f(runs[(noise, s)]) for s in SEEDS])
        return float(v.mean()), float(v.std(ddof=1)) if len(v) > 1 else 0.0

    mae_by_noise = {n: {m: agg(n, lambda r, m=m: r["mae"][m]) for m in MODELS} for n in NOISE}
    base = {m: mae_by_noise[BASE_NOISE][m] for m in MODELS}
    pooled = {m: np.concatenate([runs[(BASE_NOISE, s)]["errors"][m] for s in SEEDS]) for m in MODELS}
    cov = {m: {L: coverage(pooled[m], L) for L in LEADS} for m in ("Own mean", "EWMA", "Gradient boosting")}
    seg = {}
    for s in SEGMENT_NAMES:
        rows = [runs[(BASE_NOISE, sd)]["segments"].get(s) for sd in SEEDS]
        rows = [r for r in rows if r]
        if rows:
            seg[s] = {k: float(np.mean([r[k] for r in rows])) for k in ("n", "gb", "own", "gap")}
    importance = next(runs[(BASE_NOISE, s)]["importance"] for s in SEEDS if runs[(BASE_NOISE, s)]["importance"])
    r0 = runs[(BASE_NOISE, SEEDS[0])]
    summary = {
        "seeds": SEEDS, "noise_levels": NOISE, "orders": r0["orders"], "train": r0["train"], "test": r0["test"],
        "mae_by_noise": {str(n): v for n, v in mae_by_noise.items()},
        "within2": agg(BASE_NOISE, lambda r: r["gb_within2"]),
        "rmse": agg(BASE_NOISE, lambda r: r["gb_rmse"]),
        "bias": agg(BASE_NOISE, lambda r: r["gb_bias"]),
        "coverage": {m: {str(L): v for L, v in d.items()} for m, d in cov.items()},
        "segments": seg, "importance": importance,
    }
    (OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_tex(summary, base, mae_by_noise, cov, seg, importance)
    make_figures(mae_by_noise, pooled, cov)
    print("wrote results.json, results.tex, figures/")


def fmt(ms):
    return f"{ms[0]:.2f}\\,$\\pm$\\,{ms[1]:.2f}"


def write_tex(S, base, mae_by_noise, cov, seg, importance):
    gb, own, ewma = base["Gradient boosting"][0], base["Own mean"][0], base["EWMA"][0]
    L = []
    mac = lambda n, v: L.append(f"\\newcommand{{\\{n}}}{{{v}}}")  # noqa: E731
    mac("NOrders", f"{S['orders']:,}")
    mac("NTrain", f"{S['train']:,}")
    mac("NTest", f"{S['test']:,}")
    mac("NSeeds", len(S["seeds"]))
    mac("MaeGB", f"{gb:.2f}")
    mac("MaeOwn", f"{own:.2f}")
    mac("MaeEWMA", f"{ewma:.2f}")
    mac("MaeSeg", f"{base['Segment mean'][0]:.2f}")
    mac("GainOwn", f"{(1 - gb / own) * 100:.1f}")
    mac("GainEWMA", f"{(1 - gb / ewma) * 100:.1f}")
    mac("WithinTwo", f"{S['within2'][0] * 100:.1f}")
    mac("Rmse", f"{S['rmse'][0]:.2f}")
    mac("CovGBThree", f"{cov['Gradient boosting'][3][0] * 100:.1f}")
    mac("CovGBThreeLead", f"{cov['Gradient boosting'][3][1]:.1f}")
    mac("CovGBZero", f"{cov['Gradient boosting'][0][0] * 100:.1f}")
    mac("CovOwnThree", f"{cov['Own mean'][3][0] * 100:.1f}")
    top = sorted(importance.items(), key=lambda kv: -kv[1])
    mac("TopFeature", top[0][0].replace("_", "\\_"))
    mac("TopFeatureShare", f"{top[0][1] * 100:.0f}")
    mac("TopTwoShare", f"{(top[0][1] + top[1][1]) * 100:.0f}")

    # Table: MAE by model and noise level
    cols = "l" + "c" * len(S["noise_levels"])
    T = ["\\begin{tabular}{" + cols + "}", "\\toprule",
         "Model & " + " & ".join(f"$\\sigma\\times${n:g}" for n in S["noise_levels"]) + " \\\\", "\\midrule"]
    for m in MODELS:
        best = min(mae_by_noise[n][m][0] for n in S["noise_levels"])
        cells = []
        for n in S["noise_levels"]:
            v = mae_by_noise[n][m]
            cell = f"{v[0]:.2f}\\,$\\pm$\\,{v[1]:.2f}"
            col_best = min(mae_by_noise[n][k][0] for k in MODELS)
            cells.append(f"\\textbf{{{cell}}}" if abs(v[0] - col_best) < 1e-9 else cell)
        T.append(m + " & " + " & ".join(cells) + " \\\\")
    T += ["\\bottomrule", "\\end{tabular}"]
    L.append("\\newcommand{\\TableMae}{%\n" + "\n".join(T) + "}")

    # Table: reminder lead time
    T = ["\\begin{tabular}{c" + "cc" * 2 + "}", "\\toprule",
         "Lead & \\multicolumn{2}{c}{Own mean} & \\multicolumn{2}{c}{Gradient boosting} \\\\",
         "(days) & Useful (\\%) & Notice (d) & Useful (\\%) & Notice (d) \\\\", "\\midrule"]
    for lead in LEADS:
        a, b = cov["Own mean"][lead], cov["Gradient boosting"][lead]
        T.append(f"{lead} & {a[0] * 100:.1f} & {a[1]:.1f} & {b[0] * 100:.1f} & {b[1]:.1f} \\\\")
    T += ["\\bottomrule", "\\end{tabular}"]
    L.append("\\newcommand{\\TableLead}{%\n" + "\n".join(T) + "}")

    # Table: by segment
    T = ["\\begin{tabular}{lrrr}", "\\toprule",
         "Segment & Gap & Own & GB \\\\", "\\midrule"]
    for s, v in sorted(seg.items(), key=lambda kv: kv[1]["gap"]):
        T.append(f"{s.replace('&', '\\&').replace('/', '/')} & {v['gap']:.1f} & {v['own']:.2f} & {v['gb']:.2f} \\\\")
    T += ["\\bottomrule", "\\end{tabular}"]
    L.append("\\newcommand{\\TableSeg}{%\n" + "\n".join(T) + "}")
    (OUT / "results.tex").write_text("\n".join(L) + "\n", encoding="utf-8")


def style():
    plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#e1e0d9", "grid.linewidth": 0.6,
                         "axes.axisbelow": True, "legend.frameon": False, "font.family": "serif"})


def make_figures(mae_by_noise, pooled, cov):
    style()
    ns = sorted(mae_by_noise)
    # Fig: MAE vs noise
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    for m, c, mk in (("Segment mean", GREY, "s"), ("Own mean", ORANGE, "^"), ("EWMA", AQUA, "D"),
                     ("Gradient boosting", BLUE, "o")):
        y = [mae_by_noise[n][m][0] for n in ns]
        e = [mae_by_noise[n][m][1] for n in ns]
        ax.errorbar(ns, y, yerr=e, color=c, marker=mk, ms=4, lw=1.4, capsize=2, label=m)
    ax.set_xlabel("Behavioural noise (multiple of default)")
    ax.set_ylabel("MAE (days)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "fig_mae_noise.pdf")
    plt.close(fig)

    # Fig: reminder usefulness vs lead
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    for m, c, mk in (("Own mean", ORANGE, "^"), ("Gradient boosting", BLUE, "o")):
        ax.plot(LEADS, [cov[m][L][0] * 100 for L in LEADS], color=c, marker=mk, ms=4, lw=1.4, label=m)
    ax.axvline(3, color=GREY, ls="--", lw=0.8)
    ax.text(3.15, 8, "deployed\n(3 days)", fontsize=7, color=GREY, va="bottom")
    ax.set_xlabel("Reminder lead (days before predicted date)")
    ax.set_ylabel("Reminders sent in time (%)")
    ax.set_ylim(0, 103)
    ax.legend(fontsize=7, loc="center right")
    fig.tight_layout()
    fig.savefig(FIG / "fig_lead.pdf")
    plt.close(fig)

    # Fig: error histogram
    fig, ax = plt.subplots(figsize=(3.4, 2.2))
    e = np.clip(pooled["Gradient boosting"], -10, 10)
    ax.hist(e, bins=np.arange(-10.5, 11.5, 1), color=BLUE, edgecolor="white", linewidth=0.5)
    ax.axvline(0, color="#0b0b0b", lw=0.8)
    ax.set_xlabel("Actual minus predicted gap (days; clipped at $\\pm$10)")
    ax.set_ylabel("Held-out orders")
    fig.tight_layout()
    fig.savefig(FIG / "fig_error_hist.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
