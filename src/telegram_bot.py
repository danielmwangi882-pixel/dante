"""
Telegram alert integration for Dante signal generator.

Setup:
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Start a chat with your bot, then run:
       python -c "from src.telegram_bot import get_chat_id; get_chat_id()"
  3. Add TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to your .env file
"""

import os
import requests
from datetime import datetime
from config.settings import TELEGRAM_MIN_SCORE
from src.signal_engine import Signal

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api(method: str, payload: dict) -> dict | None:
    if not TELEGRAM_TOKEN:
        print("[WARN] TELEGRAM_TOKEN not set — skipping Telegram alert.")
        return None
    url = _BASE.format(token=TELEGRAM_TOKEN, method=method)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            print(f"[WARN] Telegram API error: {data.get('description')}")
        return data
    except Exception as exc:
        print(f"[WARN] Telegram request failed: {exc}")
        return None


def send_message(text: str, chat_id: str | None = None,
                 parse_mode: str = "HTML") -> None:
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        print("[WARN] TELEGRAM_CHAT_ID not set — skipping Telegram alert.")
        return
    _api("sendMessage", {"chat_id": cid, "text": text, "parse_mode": parse_mode})


def send_signal(signal: Signal) -> None:
    """Format a Signal as a Telegram message and send it."""
    if signal.direction == "NEUTRAL" or signal.score < TELEGRAM_MIN_SCORE:
        return

    emoji = "🟢" if signal.direction == "BUY" else "🔴"
    strength_emoji = {
        "STRONG":   "🔥",
        "MODERATE": "⚡",
        "WEAK":     "⚠️",
    }.get(signal.strength, "")

    # TP/SL block
    tp_block = (
        f"🎯 <b>TP1:</b> {signal.tp1:.5f}\n"
        f"🎯 <b>TP2:</b> {signal.tp2:.5f}\n"
        f"🎯 <b>TP3:</b> {signal.tp3:.5f}\n"
        f"🛑 <b>SL :</b> {signal.sl:.5f}"
    )

    # Reasons (max 5)
    reasons_block = "\n".join(f"  • {r}" for r in signal.reasons[:5])

    # Patterns
    patterns_block = (
        f"\n🕯 <b>Patterns:</b> {', '.join(signal.patterns)}"
        if signal.patterns else ""
    )

    # Pivot nearest levels
    pp = signal.pivots
    pivot_line = (
        f"\n📊 <b>Pivots:</b> PP={pp.get('PP')}  R1={pp.get('R1')}  S1={pp.get('S1')}"
        if pp else ""
    )

    text = (
        f"{emoji} <b>{signal.direction}  {signal.symbol}</b>  [{signal.timeframe}]\n"
        f"{strength_emoji} Score: <b>{signal.score}/10</b>  ({signal.strength})\n"
        f"💰 <b>Price:</b> {signal.price:.5f}  |  ATR: {signal.atr:.5f}\n\n"
        f"{tp_block}\n\n"
        f"📋 <b>Reasons:</b>\n{reasons_block}"
        f"{patterns_block}"
        f"{pivot_line}\n\n"
        f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )

    send_message(text)


def send_scan_summary(signals: list[Signal]) -> None:
    """Send a compact summary of all non-neutral signals after a scan."""
    actionable = [s for s in signals if s.direction != "NEUTRAL"]
    if not actionable:
        return

    lines = ["📡 <b>Dante Scan Summary</b>  "
             f"({datetime.utcnow().strftime('%H:%M UTC')})\n"]

    for s in sorted(actionable, key=lambda x: x.score, reverse=True):
        emoji = "🟢" if s.direction == "BUY" else "🔴"
        lines.append(
            f"{emoji} <b>{s.symbol}</b> [{s.timeframe}]  "
            f"{s.direction}  {s.score}/10  @ {s.price:.5f}"
        )

    send_message("\n".join(lines))


def get_chat_id() -> None:
    """Helper — prints your chat ID so you can add it to .env"""
    if not TELEGRAM_TOKEN:
        print("Set TELEGRAM_TOKEN in your .env first, then re-run.")
        return
    data = _api("getUpdates", {})
    if not data or not data.get("result"):
        print("No messages found. Send any message to your bot first, then re-run.")
        return
    for update in data["result"]:
        msg = update.get("message") or update.get("channel_post")
        if msg:
            cid  = msg["chat"]["id"]
            name = msg["chat"].get("first_name") or msg["chat"].get("title", "")
            print(f"Chat ID: {cid}  ({name})")
            print(f"Add to .env:  TELEGRAM_CHAT_ID={cid}")
            return
    print("No chat found in updates. Send a message to your bot and retry.")
