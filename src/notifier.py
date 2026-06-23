"""Output channels: console, log file, webhook."""
import json
import logging
import os
import requests
from datetime import datetime
from colorama import Fore, Style, init as colorama_init

from config.settings import (
    NOTIFY_CONSOLE, NOTIFY_LOGFILE, NOTIFY_WEBHOOK,
    WEBHOOK_URL, LOG_DIR
)
from src.signal_engine import Signal

colorama_init(autoreset=True)

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "signals.log"),
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _color(direction: str) -> str:
    return Fore.GREEN if direction == "BUY" else Fore.RED if direction == "SELL" else Fore.YELLOW


def _strength_color(strength: str) -> str:
    return {
        "STRONG":   Fore.GREEN,
        "MODERATE": Fore.YELLOW,
        "WEAK":     Fore.WHITE,
        "NEUTRAL":  Fore.CYAN,
    }.get(strength, Fore.WHITE)


def notify(signal: Signal) -> None:
    if NOTIFY_CONSOLE:
        _console(signal)
    if NOTIFY_LOGFILE:
        _logfile(signal)
    if NOTIFY_WEBHOOK and signal.direction != "NEUTRAL":
        _webhook(signal)


def _console(sig: Signal) -> None:
    dc = _color(sig.direction)
    sc = _strength_color(sig.strength)
    sep = "─" * 60
    print(f"\n{sep}")
    print(f" {dc}{sig.direction}{Style.RESET_ALL}  {sig.symbol}  [{sig.timeframe}]  "
          f"Score: {sc}{sig.score}/10 {sig.strength}{Style.RESET_ALL}  "
          f"@ {sig.price}  |  ATR {sig.atr}")
    if sig.direction != "NEUTRAL":
        print(f"  {sig.rr_label}")
    print(f"  Reasons:")
    for r in sig.reasons[:8]:
        print(f"    • {r}")
    if sig.patterns:
        print(f"  Patterns: {', '.join(sig.patterns)}")
    if sig.pivots:
        pp = sig.pivots
        print(f"  Pivots  PP={pp['PP']}  R1={pp['R1']}  S1={pp['S1']}")
    print(sep)


def _logfile(sig: Signal) -> None:
    msg = (
        f"{sig.direction} {sig.symbol} [{sig.timeframe}] "
        f"score={sig.score} strength={sig.strength} price={sig.price} "
        f"sl={sig.sl} tp1={sig.tp1} tp2={sig.tp2} tp3={sig.tp3} "
        f"reasons={'; '.join(sig.reasons)}"
    )
    logging.info(msg)


def _webhook(sig: Signal) -> None:
    payload = {
        "symbol":    sig.symbol,
        "timeframe": sig.timeframe,
        "direction": sig.direction,
        "score":     sig.score,
        "strength":  sig.strength,
        "price":     sig.price,
        "atr":       sig.atr,
        "sl":        sig.sl,
        "tp1":       sig.tp1,
        "tp2":       sig.tp2,
        "tp3":       sig.tp3,
        "reasons":   sig.reasons,
        "patterns":  sig.patterns,
        "timestamp": sig.timestamp.isoformat(),
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code >= 400:
            print(f"[WARN] Webhook returned {resp.status_code}")
    except Exception as exc:
        print(f"[WARN] Webhook failed: {exc}")


def print_summary_table(signals: list[Signal]) -> None:
    """Print a compact summary table of all scanned signals."""
    from tabulate import tabulate
    rows = []
    for s in sorted(signals, key=lambda x: x.score, reverse=True):
        dc = _color(s.direction)
        rows.append([
            s.symbol,
            s.timeframe,
            f"{dc}{s.direction}{Style.RESET_ALL}",
            f"{s.score}/10",
            s.strength,
            f"{s.price:.5f}",
        ])
    headers = ["Symbol", "TF", "Direction", "Score", "Strength", "Price"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="rounded_outline"))
