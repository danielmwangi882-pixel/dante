"""
Dante — Swing Trading Signal Generator
Supports: XAU/USD, EUR/USD, GBP/USD and more via MT5

Usage:
  python main.py            # single scan
  python main.py --loop     # scan every SCAN_INTERVAL minutes
  python main.py --demo     # force demo mode (no MT5 required)
  python main.py --report   # save CSV + HTML report after scan
"""

import sys
import time
import argparse
import schedule
from datetime import datetime

from config.settings import (
    SYMBOLS, PRIMARY_TF, CONFIRM_TF, SCAN_INTERVAL
)
from src.mt5_connector import MT5Connector
from src.indicators import apply_all
from src.signal_engine import SignalEngine
from src.notifier import notify, print_summary_table
from src.reporter import save_csv, save_html
from src.telegram_bot import send_signal, send_scan_summary


def scan(connector: MT5Connector, engine: SignalEngine,
         save_report: bool = False) -> None:
    print(f"\n{'='*60}")
    print(f"  DANTE — Swing Signal Scan  |  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Symbols: {len(SYMBOLS)}  |  TF: {PRIMARY_TF} (confirm: {CONFIRM_TF})")
    print(f"{'='*60}")

    all_signals = []

    for symbol in SYMBOLS:
        try:
            df_primary = connector.get_ohlcv(symbol, PRIMARY_TF)
            df_confirm = connector.get_ohlcv(symbol, CONFIRM_TF)

            if df_primary.empty:
                print(f"[SKIP] {symbol} — no data")
                continue

            df_primary = apply_all(df_primary)
            df_confirm = apply_all(df_confirm) if not df_confirm.empty else df_confirm

            signal = engine.analyse(df_primary, symbol, PRIMARY_TF, df_confirm)
            all_signals.append(signal)

            if signal.direction != "NEUTRAL":
                notify(signal)
                send_signal(signal)

        except Exception as exc:
            print(f"[ERROR] {symbol}: {exc}")

    print_summary_table(all_signals)
    send_scan_summary(all_signals)

    if save_report and all_signals:
        save_csv(all_signals)
        save_html(all_signals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dante Swing Signal Generator")
    parser.add_argument("--loop",   action="store_true", help="Run on schedule")
    parser.add_argument("--demo",   action="store_true", help="Demo mode (no MT5)")
    parser.add_argument("--report", action="store_true", help="Save report after scan")
    args = parser.parse_args()

    connector = MT5Connector()

    if not args.demo:
        connected = connector.connect()
        if not connected:
            print("[INFO] Falling back to demo mode.")
    else:
        print("[INFO] Demo mode active — using synthetic data.")

    engine = SignalEngine()

    if args.loop:
        print(f"[INFO] Scheduling scan every {SCAN_INTERVAL} minutes…")
        scan(connector, engine, args.report)   # immediate first run
        schedule.every(SCAN_INTERVAL).minutes.do(scan, connector, engine, args.report)
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n[INFO] Stopped by user.")
    else:
        scan(connector, engine, args.report)

    connector.disconnect()


if __name__ == "__main__":
    main()
