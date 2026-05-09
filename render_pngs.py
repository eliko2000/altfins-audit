"""Render screenshot-ready PNGs of the audit's headline tables for Twitter."""
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

OUT = Path(__file__).parent / "store" / "shots"
OUT.mkdir(exist_ok=True, parents=True)

# Twitter renders best at 1600x900-ish for landscape, 1080-square for portrait
plt.rcParams.update({
    "font.family": "DejaVu Sans Mono",
    "font.size": 16,
    "savefig.facecolor": "#0d1117",  # github dark
    "axes.facecolor": "#0d1117",
    "text.color": "#e6edf3",
    "axes.edgecolor": "#30363d",
    "axes.labelcolor": "#e6edf3",
})

BG = "#0d1117"
FG = "#e6edf3"
GOOD = "#2ea043"
BAD = "#f85149"
DIM = "#7d8590"
ACCENT = "#1f6feb"

conn = sqlite3.connect(Path(__file__).parent / "store" / "altfins.db")
sigs = pd.read_sql_query(
    "SELECT signal_id, side, posted_at FROM signals "
    "WHERE category IN ('directional','target')", conn,
)
rets = pd.read_sql_query("SELECT * FROM returns WHERE fwd_return IS NOT NULL", conn)
base = pd.read_sql_query("SELECT * FROM baseline_returns", conn)

df = rets.merge(sigs, on="signal_id")
df["signed"] = df.apply(
    lambda r: r["fwd_return"] if r["side"] == "long" else -r["fwd_return"], axis=1
)


def _label(h):
    return f"+{h}h" if h < 24 else f"+{h // 24}d"


def _color_for_alpha(v):
    return BAD if v < -0.001 else (GOOD if v > 0.001 else DIM)


def _color_for_acc(v):
    return BAD if v < 0.5 else GOOD


# --- 1) Forward returns vs baseline ------------------------------------------
def render_forward():
    horizons = [4, 8, 12, 24, 72, 168]
    rows = []
    for h in horizons:
        s = df[df["horizon_hours"] == h]
        b = base[base["horizon_hours"] == h]
        rows.append({
            "h": _label(h),
            "n": len(s),
            "acc": s["direction_correct"].mean(),
            "sig": s["signed"].mean() * 100,
            "base": b["fwd_return"].mean() * 100,
            "alpha": (s["signed"].mean() - b["fwd_return"].mean()) * 100,
        })

    fig, ax = plt.subplots(figsize=(16, 9), dpi=150)
    ax.set_axis_off()
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    fig.text(0.04, 0.93, "altFINS free channel — Forward returns vs baseline",
             fontsize=24, fontweight="bold", color=FG)
    fig.text(0.04, 0.87,
             "n = 395 evaluated alerts · 24 months · Binance USDT subset · baseline = random pick from same universe",
             fontsize=14, color=DIM)

    headers = ["Horizon", "n", "Direction acc.", "Signal mean", "Baseline mean", "Alpha"]
    col_x = [0.06, 0.30, 0.48, 0.66, 0.83, 0.96]
    y = 0.74
    for i, h in enumerate(headers):
        ax.text(col_x[i], y, h, fontsize=16, color=DIM, fontweight="bold",
                ha="left" if i == 0 else "right",
                transform=ax.transAxes)
    ax.plot([0.04, 0.97], [y - 0.025, y - 0.025], color="#30363d", lw=1,
            transform=ax.transAxes)

    y -= 0.09
    for r in rows:
        ax.text(col_x[0], y, r["h"], fontsize=20, color=FG,
                fontweight="bold", transform=ax.transAxes)
        ax.text(col_x[1], y, f"{r['n']}", fontsize=20, color=FG, ha="right",
                transform=ax.transAxes)
        ax.text(col_x[2], y, f"{r['acc']:.1%}", fontsize=20,
                color=_color_for_acc(r["acc"]), ha="right",
                transform=ax.transAxes, fontweight="bold")
        ax.text(col_x[3], y, f"{r['sig']:+.2f}%", fontsize=20, color=FG,
                ha="right", transform=ax.transAxes)
        ax.text(col_x[4], y, f"{r['base']:+.2f}%", fontsize=20, color=FG,
                ha="right", transform=ax.transAxes)
        ax.text(col_x[5], y, f"{r['alpha']:+.2f}%", fontsize=20,
                color=_color_for_alpha(r["alpha"]), ha="right",
                transform=ax.transAxes, fontweight="bold")
        y -= 0.09

    fig.text(0.04, 0.05,
             "Direction accuracy < 50% at every horizon. Alpha negative everywhere.",
             fontsize=15, color=BAD, style="italic")

    out = OUT / "tweet2_forward_returns.png"
    fig.savefig(out, bbox_inches="tight", facecolor=BG, dpi=150)
    plt.close(fig)
    print(f"  wrote {out}")


# --- 2) Half-year regime breakdown -------------------------------------------
def render_regime():
    df24 = df[df["horizon_hours"] == 24].copy()
    df24["posted"] = pd.to_datetime(df24["posted_at"], utc=True)
    df24["hy"] = (df24["posted"].dt.year.astype(str) + "-H" +
                  ((df24["posted"].dt.month > 6).astype(int) + 1).astype(str))
    rows = []
    for hy in sorted(df24["hy"].unique()):
        s = df24[df24["hy"] == hy]
        rows.append({"hy": hy, "n": len(s),
                     "acc": s["direction_correct"].mean(),
                     "ret": s["signed"].mean() * 100})

    fig, ax = plt.subplots(figsize=(13, 7), dpi=150)
    bars = ax.bar(
        [r["hy"] for r in rows],
        [r["acc"] * 100 for r in rows],
        color=[_color_for_acc(r["acc"]) for r in rows],
        edgecolor="#30363d", linewidth=1,
    )
    ax.axhline(50, color=DIM, linestyle="--", linewidth=2,
               label="50% (coin-flip)")
    ax.set_ylim(0, 60)
    ax.set_ylabel("Direction accuracy (24h)", fontsize=14, color=FG)
    ax.tick_params(colors=FG, labelsize=14)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#30363d")
    ax.spines["bottom"].set_color("#30363d")
    ax.grid(axis="y", color="#30363d", alpha=0.3)
    ax.legend(facecolor=BG, edgecolor=DIM, labelcolor=FG, fontsize=13)

    for bar, r in zip(bars, rows):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.2,
                f"{r['acc']:.1%}\nn={r['n']}",
                ha="center", fontsize=13, color=FG, fontweight="bold")

    fig.suptitle("altFINS free channel — Direction accuracy by half-year",
                 fontsize=22, fontweight="bold", color=FG, x=0.06, ha="left")
    fig.text(0.06, 0.91,
             "The 'near-zero' 24-month average is propped up by 2024-H2. The current half is the worst in 2 years.",
             fontsize=13, color=DIM)

    out = OUT / "tweet3_regime.png"
    fig.savefig(out, bbox_inches="tight", facecolor=BG, dpi=150)
    plt.close(fig)
    print(f"  wrote {out}")


# --- 3) Long vs short ---------------------------------------------------------
def render_long_short():
    horizons = [4, 8, 12, 24, 72, 168]
    long_alpha = []; short_alpha = []
    for h in horizons:
        b = base[base["horizon_hours"] == h]["fwd_return"].mean()
        L = df[(df["horizon_hours"] == h) & (df["side"] == "long")]["signed"].mean()
        S = df[(df["horizon_hours"] == h) & (df["side"] == "short")]["signed"].mean()
        long_alpha.append((L - b) * 100)
        short_alpha.append((S - b) * 100)

    fig, ax = plt.subplots(figsize=(13, 7), dpi=150)
    x = range(len(horizons))
    width = 0.38
    ax.bar([i - width/2 for i in x], long_alpha, width, label="Longs (n=314)",
           color="#f85149", edgecolor="#30363d")
    ax.bar([i + width/2 for i in x], short_alpha, width, label="Shorts (n=81)",
           color="#1f6feb", edgecolor="#30363d")
    ax.axhline(0, color=DIM, linewidth=1)
    ax.set_xticks(list(x))
    ax.set_xticklabels([_label(h) for h in horizons])
    ax.set_ylabel("Alpha vs baseline (%)", fontsize=14, color=FG)
    ax.tick_params(colors=FG, labelsize=14)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#30363d")
    ax.spines["bottom"].set_color("#30363d")
    ax.grid(axis="y", color="#30363d", alpha=0.3)
    ax.legend(facecolor=BG, edgecolor=DIM, labelcolor=FG, fontsize=13)

    for i, v in enumerate(long_alpha):
        ax.text(i - width/2, v + (0.02 if v >= 0 else -0.06),
                f"{v:+.2f}", ha="center", fontsize=11, color=FG)
    for i, v in enumerate(short_alpha):
        ax.text(i + width/2, v + (0.02 if v >= 0 else -0.06),
                f"{v:+.2f}", ha="center", fontsize=11, color=FG)

    fig.suptitle("altFINS — Alpha by side, across horizons",
                 fontsize=22, fontweight="bold", color=FG, x=0.06, ha="left")
    fig.text(0.06, 0.91,
             "Shorts at 8h–12h show a tiny positive alpha (only positive cell). Longs negative everywhere.",
             fontsize=13, color=DIM)

    out = OUT / "tweet_long_short_bonus.png"
    fig.savefig(out, bbox_inches="tight", facecolor=BG, dpi=150)
    plt.close(fig)
    print(f"  wrote {out}")


if __name__ == "__main__":
    render_forward()
    render_regime()
    render_long_short()
    print(f"\nAll PNGs in: {OUT}")
