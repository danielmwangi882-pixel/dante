"""
Chart generation — saves an annotated candlestick chart for each signal.
Shows: price, EMA9/21/50/200, Bollinger Bands, RSI, MACD, volume,
and marks the entry price, SL, TP1, TP2, TP3 with horizontal lines.
"""

from __future__ import annotations
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")   # non-interactive backend for headless/server use
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd

from config.settings import REPORT_DIR
from src.signal_engine import Signal

os.makedirs(os.path.join(REPORT_DIR, "charts"), exist_ok=True)

# Candles to display on chart
CHART_BARS = 80


def generate_chart(df: pd.DataFrame, signal: Signal) -> str:
    """
    Generate a multi-panel chart for the signal and save it as PNG.
    Returns the file path.
    """
    df = df.tail(CHART_BARS).copy()

    fig = plt.figure(figsize=(16, 10), facecolor="#0d1117")
    fig.subplots_adjust(hspace=0.05)

    gs = gridspec.GridSpec(4, 1, height_ratios=[5, 1.5, 1.5, 1.5], figure=fig)
    ax_price  = fig.add_subplot(gs[0])
    ax_vol    = fig.add_subplot(gs[1], sharex=ax_price)
    ax_rsi    = fig.add_subplot(gs[2], sharex=ax_price)
    ax_macd   = fig.add_subplot(gs[3], sharex=ax_price)

    x = np.arange(len(df))
    dates = df.index

    # ── Candlestick ───────────────────────────────────────────────────────────
    for i, (_, row) in enumerate(df.iterrows()):
        color = "#26a69a" if row["Close"] >= row["Open"] else "#ef5350"
        ax_price.plot([i, i], [row["Low"], row["High"]], color=color, linewidth=0.8)
        ax_price.add_patch(plt.Rectangle(
            (i - 0.3, min(row["Open"], row["Close"])),
            0.6, abs(row["Close"] - row["Open"]),
            facecolor=color, edgecolor=color, linewidth=0
        ))

    # ── EMAs ─────────────────────────────────────────────────────────────────
    for col, color, lw, label in [
        ("EMA9",   "#f7c948", 1.0, "EMA9"),
        ("EMA21",  "#4fc3f7", 1.0, "EMA21"),
        ("EMA50",  "#81c784", 1.2, "EMA50"),
        ("EMA200", "#ef9a9a", 1.5, "EMA200"),
    ]:
        if col in df.columns:
            ax_price.plot(x, df[col], color=color, linewidth=lw, label=label, alpha=0.85)

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if "BB_Upper" in df.columns:
        ax_price.fill_between(x, df["BB_Upper"], df["BB_Lower"],
                              color="#7986cb", alpha=0.08)
        ax_price.plot(x, df["BB_Upper"], color="#7986cb", linewidth=0.6, linestyle="--", alpha=0.5)
        ax_price.plot(x, df["BB_Lower"], color="#7986cb", linewidth=0.6, linestyle="--", alpha=0.5)

    # ── Entry / SL / TP lines ─────────────────────────────────────────────────
    level_styles = [
        (signal.price, "#ffffff", "--", 1.5, f"Entry {signal.price:.5f}"),
        (signal.sl,    "#ef5350", "-",  1.2, f"SL {signal.sl:.5f}"),
        (signal.tp1,   "#66bb6a", "-",  1.0, f"TP1 {signal.tp1:.5f}"),
        (signal.tp2,   "#26a69a", "-",  1.0, f"TP2 {signal.tp2:.5f}"),
        (signal.tp3,   "#4fc3f7", "-",  1.0, f"TP3 {signal.tp3:.5f}"),
    ]
    for price, color, ls, lw, label in level_styles:
        if price:
            ax_price.axhline(price, color=color, linestyle=ls, linewidth=lw,
                             alpha=0.85, label=label)

    # ── Chart title ───────────────────────────────────────────────────────────
    dir_color  = "#26a69a" if signal.direction == "BUY" else "#ef5350"
    title = (f"{signal.symbol}  [{signal.timeframe}]  "
             f"{signal.direction}  Score: {signal.score}/10 {signal.strength}  "
             f"@ {signal.price:.5f}  |  ATR {signal.atr:.5f}")
    ax_price.set_title(title, color=dir_color, fontsize=11, pad=8, fontweight="bold")

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_colors = ["#26a69a" if df["Close"].iloc[i] >= df["Open"].iloc[i] else "#ef5350"
                  for i in range(len(df))]
    ax_vol.bar(x, df["Volume"], color=vol_colors, alpha=0.7, width=0.8)
    ax_vol.set_ylabel("Volume", color="#aaaaaa", fontsize=8)

    # ── RSI ───────────────────────────────────────────────────────────────────
    if "RSI" in df.columns:
        ax_rsi.plot(x, df["RSI"], color="#ce93d8", linewidth=1.0)
        ax_rsi.axhline(70, color="#ef5350", linewidth=0.6, linestyle="--", alpha=0.6)
        ax_rsi.axhline(30, color="#26a69a", linewidth=0.6, linestyle="--", alpha=0.6)
        ax_rsi.fill_between(x, df["RSI"], 70, where=(df["RSI"] >= 70), alpha=0.15, color="#ef5350")
        ax_rsi.fill_between(x, df["RSI"], 30, where=(df["RSI"] <= 30), alpha=0.15, color="#26a69a")
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI", color="#aaaaaa", fontsize=8)

    # ── MACD ─────────────────────────────────────────────────────────────────
    if "MACD" in df.columns:
        hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_Hist"]]
        ax_macd.bar(x, df["MACD_Hist"], color=hist_colors, alpha=0.7, width=0.8)
        ax_macd.plot(x, df["MACD"],        color="#4fc3f7", linewidth=0.9)
        ax_macd.plot(x, df["MACD_Signal"], color="#f7c948", linewidth=0.9)
        ax_macd.axhline(0, color="#555555", linewidth=0.5)
        ax_macd.set_ylabel("MACD", color="#aaaaaa", fontsize=8)

    # ── X-axis labels ─────────────────────────────────────────────────────────
    tick_every = max(1, len(df) // 10)
    ax_macd.set_xticks(x[::tick_every])
    ax_macd.set_xticklabels(
        [dates[i].strftime("%m/%d %H:%M") for i in range(0, len(df), tick_every)],
        rotation=30, ha="right", fontsize=7, color="#aaaaaa"
    )

    # ── Shared style ──────────────────────────────────────────────────────────
    for ax in [ax_price, ax_vol, ax_rsi, ax_macd]:
        ax.set_facecolor("#0d1117")
        ax.tick_params(colors="#aaaaaa", labelsize=7)
        ax.spines["bottom"].set_color("#333333")
        ax.spines["top"].set_color("#333333")
        ax.spines["left"].set_color("#333333")
        ax.spines["right"].set_color("#333333")
        ax.yaxis.tick_right()

    plt.setp(ax_price.get_xticklabels(), visible=False)
    plt.setp(ax_vol.get_xticklabels(),   visible=False)
    plt.setp(ax_rsi.get_xticklabels(),   visible=False)

    ax_price.legend(loc="upper left", fontsize=7, facecolor="#1a1f2e",
                    labelcolor="white", framealpha=0.8, ncol=3)

    # ── Save ─────────────────────────────────────────────────────────────────
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, "charts",
                        f"{signal.symbol}_{signal.timeframe}_{signal.direction}_{ts}.png")
    plt.savefig(path, dpi=120, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    print(f"[CHART] Saved → {path}")
    return path


def send_chart_to_telegram(chart_path: str, signal: Signal) -> None:
    """Send the chart image via Telegram bot."""
    import os, requests
    token   = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    caption = (f"{signal.direction} {signal.symbol} [{signal.timeframe}] "
               f"Score {signal.score}/10 | SL={signal.sl:.5f} TP1={signal.tp1:.5f}")
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(chart_path, "rb") as f:
            requests.post(url, data={"chat_id": chat_id, "caption": caption},
                          files={"photo": f}, timeout=15)
    except Exception as exc:
        print(f"[WARN] Chart Telegram send failed: {exc}")
