"""
Dante — Swing Trading Signal Generator
Supports: XAU/USD, EUR/USD, GBP/USD and more via MT5

Usage:
  python main.py                       # single scan, signals only
  python main.py --loop                # scan every SCAN_INTERVAL minutes
  python main.py --demo                # force demo mode (no MT5 required)
  python main.py --report              # save CSV + HTML report after scan
  python main.py --charts              # generate signal charts
  python main.py --live                # enable auto-execution (dry-run)
  python main.py --live --no-dry-run   # REAL orders — use with caution
  python main.py --close-all           # emergency: close all Dante trades

  python dashboard.py                  # open web dashboard at localhost:5000
"""

import time
import argparse
import schedule
from datetime import datetime

from config.settings import SYMBOLS, PRIMARY_TF, CONFIRM_TF, SCAN_INTERVAL
from src.mt5_connector import MT5Connector
from src.indicators import apply_all
from src.signal_engine import SignalEngine
from src.notifier import notify, print_summary_table
from src.reporter import save_csv, save_html
from src.telegram_bot import send_signal, send_scan_summary
from src.trader import Trader
from src.risk_manager import RiskManager
from src.charting import generate_chart, send_chart_to_telegram


def scan(connector: MT5Connector, engine: SignalEngine,
         trader: Trader | None = None,
         risk: RiskManager | None = None,
         save_report: bool = False,
         make_charts: bool = False) -> None:

    print(f"\n{'='*60}")
    print(f"  DANTE — Swing Signal Scan  |  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    mode = "LIVE" if (trader and not trader.dry_run) else ("DRY-RUN" if trader else "SIGNAL-ONLY")
    print(f"  Symbols: {len(SYMBOLS)}  |  TF: {PRIMARY_TF}  |  Mode: {mode}")
    print(f"{'='*60}")

    # Risk report + trade management
    if risk:
        risk.print_report()
    if trader:
        trader.manage_open_trades()
        trader.status()

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

                # Generate + send chart
                if make_charts:
                    try:
                        chart_path = generate_chart(df_primary, signal)
                        send_chart_to_telegram(chart_path, signal)
                    except Exception as e:
                        print(f"[WARN] Chart failed for {symbol}: {e}")

                # Risk check before executing
                if trader and risk:
                    ok, reason = risk.can_trade(signal.symbol, signal.direction)
                    if ok:
                        ticket = trader.process_signal(signal)
                        if ticket:
                            risk.register_open(signal.symbol, signal.direction)
                    else:
                        print(f"[RISK] {symbol} blocked — {reason}")
                elif trader:
                    trader.process_signal(signal)

        except Exception as exc:
            print(f"[ERROR] {symbol}: {exc}")

    print_summary_table(all_signals)
    send_scan_summary(all_signals)

    if save_report and all_signals:
        save_csv(all_signals)
        save_html(all_signals)

    if risk:
        risk.save_report()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dante Swing Signal Generator")
    parser.add_argument("--loop",       action="store_true", help="Run on schedule")
    parser.add_argument("--demo",       action="store_true", help="Demo mode (no MT5)")
    parser.add_argument("--report",     action="store_true", help="Save HTML/CSV report")
    parser.add_argument("--charts",     action="store_true", help="Generate signal charts")
    parser.add_argument("--live",       action="store_true", help="Enable auto-execution")
    parser.add_argument("--no-dry-run", action="store_true", help="Send REAL orders (needs --live)")
    parser.add_argument("--close-all",  action="store_true", help="Emergency close all trades")
    parser.add_argument("--balance",    type=float, default=10000.0, help="Account balance for risk manager")
    args = parser.parse_args()

    connector = MT5Connector()

    if not args.demo:
        connected = connector.connect()
        if not connected:
            print("[INFO] Falling back to demo mode.")
    else:
        print("[INFO] Demo mode active — using synthetic data.")

    engine = SignalEngine()
    risk   = RiskManager(balance=args.balance)
    trader = None

    if args.live:
        dry_run = not args.no_dry_run
        trader  = Trader(dry_run=dry_run)

        if args.close_all:
            trader.close_all()
            connector.disconnect()
            return

        if not dry_run:
            print("\n" + "!" * 60)
            print("  ⚠️  LIVE TRADING ENABLED — real orders will be placed")
            print("  Press Ctrl+C within 5 seconds to abort.")
            print("!" * 60 + "\n")
            try:
                time.sleep(5)
            except KeyboardInterrupt:
                print("[ABORTED]")
                connector.disconnect()
                return

    elif args.close_all:
        print("[WARN] --close-all requires --live flag.")
        return

    scan_args = (connector, engine, trader, risk, args.report, args.charts)

    if args.loop:
        print(f"[INFO] Scheduling scan every {SCAN_INTERVAL} minutes…")
        scan(*scan_args)
        schedule.every(SCAN_INTERVAL).minutes.do(scan, *scan_args)
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n[INFO] Stopped by user.")
            if trader:
                trader.status()
            risk.print_report()
    else:
        scan(*scan_args)

    connector.disconnect()


if __name__ == "__main__":
    main()
