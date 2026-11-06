"""Equity charts. Labels stay in English so a computer without Thai fonts still works."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_comparison(strategy_equity, buy_hold_equity, path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, equity, style in (
        ("Buy and hold", buy_hold_equity, {"color": "#666666", "linestyle": "--", "linewidth": 1.4}),
        ("Strategy", strategy_equity, {"color": "#0B6E4F", "linewidth": 1.8}),
    ):
        scaled = equity / float(equity.iloc[0]) * 100.0
        ax.plot(scaled.index, scaled.to_numpy(), label=name, **style)
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_ylabel("Portfolio (start = 100, log scale)")
    ax.set_xlabel("Date")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_overview(curves: dict, buy_hold, path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 6.5))
    scaled_bh = buy_hold / float(buy_hold.iloc[0]) * 100.0
    ax.plot(scaled_bh.index, scaled_bh.to_numpy(), label="Buy and hold", color="#222222", linestyle="--", linewidth=1.8)
    for name, equity in curves.items():
        scaled = equity / float(equity.iloc[0]) * 100.0
        ax.plot(scaled.index, scaled.to_numpy(), label=name, linewidth=1.2)
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_ylabel("Portfolio (start = 100, log scale)")
    ax.set_xlabel("Date")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
