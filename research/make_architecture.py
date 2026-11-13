"""Draws the system architecture diagram (vector PDF for the paper, SVG + PNG for the README).

    .venv/bin/python research/make_architecture.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent
(OUT / "figures").mkdir(exist_ok=True)
DOCS = OUT.parent / "docs"
DOCS.mkdir(exist_ok=True)

INK, MUTED, PURPLE = "#0b0b0b", "#52514e", "#a64d94"
COL = {  # fill, edge
    "client": ("#e8f0fb", "#2a78d6"),
    "web": ("#e6f4ee", "#16946a"),
    "ml": ("#fdece4", "#d95926"),
    "data": ("#f0efec", "#77756f"),
    "mail": ("#f6ecf5", PURPLE),
}
plt.rcParams["font.family"] = "sans-serif"

fig, ax = plt.subplots(figsize=(12, 6.4))
ax.set_xlim(0, 116)
ax.set_ylim(0, 66)
ax.axis("off")


def band(x, y, w, h, title, kind):
    fill, edge = COL[kind]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.6",
                                fc=fill, ec=edge, lw=1.2, alpha=0.55, zorder=0))
    ax.text(x + 1.4, y + h - 2.0, title, fontsize=9.5, fontweight="bold", color=edge, va="center", zorder=3)


def box(x, y, w, h, title, sub, kind):
    edge = COL[kind][1]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.0",
                                fc="white", ec=edge, lw=1.3, zorder=2))
    ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", fontsize=8.6, fontweight="bold",
            color=INK, zorder=3)
    ax.text(x + w / 2, y + h * 0.29, sub, ha="center", va="center", fontsize=7.0, color=MUTED,
            zorder=3, linespacing=1.25)


def arrow(p, q, color=MUTED, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=11, lw=1.3, color=color,
                                 linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=4))


def label(x, y, text, color=MUTED, **kw):
    ax.text(x, y, text, fontsize=7.3, color=color, ha=kw.pop("ha", "center"), va="center", zorder=5,
            bbox=dict(fc="white", ec="none", pad=1.2, alpha=0.92), **kw)


# ---- bands ---------------------------------------------------------------------------
band(1, 47, 107, 18, "1  Presentation  (browser; server-rendered HTML with SVG charts)", "client")
band(1, 26, 107, 19.5, "2  Application  (FastAPI, Python)", "web")
band(1, 1, 40, 23.5, "3  Intelligence", "ml")
band(43, 1, 65, 23.5, "4  Data and delivery", "data")

# ---- presentation --------------------------------------------------------------------
box(4, 50, 30, 11, "Dealer (admin) portal", "KPI dashboard  -  restock forecast\norders  -  receivables  -  model", "client")
box(40, 50, 30, 11, "Customer portal", "next refill date  -  book / cancel\nhistory  -  reminder opt-out", "client")
box(76, 50, 30, 11, "One-click booking page", "opened from the emailed link\nno login needed", "client")

# ---- application ---------------------------------------------------------------------
box(4, 29, 24, 12.5, "Auth and security", "scrypt hashes  -  sessions\nCSRF  -  login throttle", "web")
box(31, 29, 24, 12.5, "Routes", "public  /  customer  /  admin\nrole guards", "web")
box(58, 29, 24, 12.5, "Order service", "booking rules  -  lifecycle\nbooked > confirmed > delivered", "web")
box(85, 29, 21, 12.5, "Analytics", "revenue  -  margin\nreceivables ageing", "web")

# ---- intelligence --------------------------------------------------------------------
box(4, 6, 16, 12, "Gradient boosting", "predicts days to\nnext refill", "ml")
box(23, 6, 16, 12, "Feature builder", "gap statistics  -  EWMA\nquantity  -  segment", "ml")

# ---- data and delivery ---------------------------------------------------------------
box(46, 6, 18, 12, "SQLite", "customers  -  orders\npredictions  -  reminders", "data")
box(70, 6, 18, 12, "Reminder scheduler", "reads predictions every 6 h\ndue in 3 days, no open order", "mail")
box(93, 6, 14, 12, "Email", "SMTP, or saved to\noutbox (demo mode)", "mail")

# ---- flows ---------------------------------------------------------------------------
arrow((19, 50), (36, 41.5))
arrow((55, 50), (43, 41.5))
arrow((91, 50), (50, 41.5))
label(30.5, 46.2, "HTTPS")
arrow((28, 35), (31, 35))
arrow((55, 35), (58, 35))
arrow((38, 29), (12, 18))
label(26, 23.6, "train / refresh")
arrow((62, 29), (58, 18))
label(66.3, 22.4, "read / write", ha="left")
arrow((90, 29), (63, 18))
label(77.5, 23.8, "aggregates")
arrow((23, 12), (20, 12))
arrow((46, 12), (39, 12))
label(42.5, 14.6, "history")
arrow((12, 6), (55, 6), rad=0.14)
label(33.5, 2.9, "predictions")
arrow((70, 12), (64, 12))
arrow((88, 12), (93, 12), color=PURPLE)

# email -> customer opens the booking page (route along the right margin, clear of every box)
ax.plot([107, 112, 112], [9, 9, 56], color=PURPLE, lw=1.3, ls="--", zorder=4)
arrow((112, 56), (106.3, 56), color=PURPLE, ls="--")
ax.text(113.6, 33, "email carries a signed booking link", fontsize=7.3, color=PURPLE, rotation=90,
        ha="center", va="center")

fig.suptitle("Restock-prediction and booking platform: system architecture", fontsize=11.5,
             fontweight="bold", color=INK, y=0.985)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT / "figures" / "fig_architecture.pdf")
fig.savefig(DOCS / "architecture.svg")
fig.savefig(DOCS / "architecture.png", dpi=170)
print("wrote figures/fig_architecture.pdf, docs/architecture.svg, docs/architecture.png")
