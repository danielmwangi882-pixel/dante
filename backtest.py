"""
Backtesting engine — replays historical data bar by bar,
runs the signal engine, and tracks trade outcomes.

Usage:
  python backtest.py                          # all symbols, H4, last 500 bars
  python backtest.py --symbol XAUUSD --tf H4 --bars 1000
  python backtest.py --symbol EURUSD --tf D1
"""

import argparse
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd

from config.settings import (
    SYMBOLS, PRIMARY_TF, CONFIRM_TF, CANDLE_COUNT,
    STRONG_SIGNAL_MIN_SCORE, WEAK_SIGNAL_MIN_SCORE,
    REPORT_DIR,
)
from src.mt5_connector import MT5Connector
from src.indicators import apply_all
from src.signal_engine import SignalEngine

os.makedirs(REPORT_DIR, exist_ok=True)

# Minimum warm-up bars before we start trading (indicators need history)
WARMUP_BARS = 220


# ── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol:     str
    timeframe:  str
    direction:  Literal["BUY", "SELL"]
    entry_time: datetime
    entry:      float
    sl:         float
    tp1:        float
    tp2:        float
    tp3:        float
    atr:        float
    score:      int
    strength:   str
    patterns:   list[str] = field(default_factory=list)

    exit_time:   datetime | None = None
    exit_price:  float = 0.0
    outcome:     str = "OPEN"   # WIN_TP1 / WIN_TP2 / WIN_TP3 / LOSS / OPEN
    pnl_r:       float = 0.0    # P&L in R multiples


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    def __init__(self, tp1_r: float = 1.5, tp2_r: float = 3.0, tp3_r: float = 5.0):
        self.tp1_r = tp1_r
        self.tp2_r = tp2_r
        self.tp3_r = tp3_r
        self.engine = SignalEngine()

    def run(self, df_raw: pd.DataFrame, symbol: str, timeframe: str,
            df_confirm_raw: pd.DataFrame | None = None) -> list[Trade]:
        trades: list[Trade] = []
        active: Trade | None = None

        n = len(df_raw)

        for i in range(WARMUP_BARS, n):
            # Slice up to bar i (no look-ahead)
            slice_primary = apply_all(df_raw.iloc[:i + 1].copy())
            slice_confirm = (
                apply_all(df_confirm_raw.iloc[:i + 1].copy())
                if df_confirm_raw is not None and not df_confirm_raw.empty
                else None
            )

            bar = slice_primary.iloc[-1]
            bar_time = slice_primary.index[-1]

            # ── Check if active trade hit SL or TP ───────────────────────
            if active is not None:
                high = float(bar["High"])
                low  = float(bar["Low"])
                active = self._check_exit(active, high, low, bar_time)
                if active.outcome != "OPEN":
                    trades.append(active)
                    active = None
                    continue   # don't enter another trade on exit bar

            # ── Only look for new entry if no active trade ────────────────
            if active is None:
                sig = self.engine.analyse(slice_primary, symbol, timeframe, slice_confirm)
                if sig.direction in ("BUY", "SELL") and sig.score >= WEAK_SIGNAL_MIN_SCORE:
                    active = Trade(
                        symbol=symbol, timeframe=timeframe,
                        direction=sig.direction,
                        entry_time=bar_time, entry=sig.price,
                        sl=sig.sl, tp1=sig.tp1, tp2=sig.tp2, tp3=sig.tp3,
                        atr=sig.atr, score=sig.score, strength=sig.strength,
                        patterns=sig.patterns,
                    )

        # Close any open trade at end of data
        if active is not None:
            active.exit_time  = df_raw.index[-1]
            active.exit_price = float(df_raw.iloc[-1]["Close"])
            active.outcome    = "OPEN"
            active.pnl_r      = self._calc_r(active, active.exit_price)
            trades.append(active)

        return trades

    def _check_exit(self, trade: Trade, high: float, low: float,
                    bar_time: datetime) -> Trade:
        risk = abs(trade.entry - trade.sl)
        if risk == 0:
            return trade

        if trade.direction == "BUY":
            if low <= trade.sl:
                trade.exit_price = trade.sl
                trade.outcome    = "LOSS"
                trade.pnl_r      = -1.0
                trade.exit_time  = bar_time
            elif high >= trade.tp3:
                trade.exit_price = trade.tp3
                trade.outcome    = "WIN_TP3"
                trade.pnl_r      = self.tp3_r
                trade.exit_time  = bar_time
            elif high >= trade.tp2:
                trade.exit_price = trade.tp2
                trade.outcome    = "WIN_TP2"
                trade.pnl_r      = self.tp2_r
                trade.exit_time  = bar_time
            elif high >= trade.tp1:
                trade.exit_price = trade.tp1
                trade.outcome    = "WIN_TP1"
                trade.pnl_r      = self.tp1_r
                trade.exit_time  = bar_time
        else:  # SELL
            if high >= trade.sl:
                trade.exit_price = trade.sl
                trade.outcome    = "LOSS"
                trade.pnl_r      = -1.0
                trade.exit_time  = bar_time
            elif low <= trade.tp3:
                trade.exit_price = trade.tp3
                trade.outcome    = "WIN_TP3"
                trade.pnl_r      = self.tp3_r
                trade.exit_time  = bar_time
            elif low <= trade.tp2:
                trade.exit_price = trade.tp2
                trade.outcome    = "WIN_TP2"
                trade.pnl_r      = self.tp2_r
                trade.exit_time  = bar_time
            elif low <= trade.tp1:
                trade.exit_price = trade.tp1
                trade.outcome    = "WIN_TP1"
                trade.pnl_r      = self.tp1_r
                trade.exit_time  = bar_time

        return trade

    @staticmethod
    def _calc_r(trade: Trade, exit_price: float) -> float:
        risk = abs(trade.entry - trade.sl)
        if risk == 0:
            return 0.0
        if trade.direction == "BUY":
            return (exit_price - trade.entry) / risk
        return (trade.entry - exit_price) / risk


# ── Statistics ────────────────────────────────────────────────────────────────

def compute_stats(trades: list[Trade]) -> dict:
    closed = [t for t in trades if t.outcome != "OPEN"]
    if not closed:
        return {"total": 0}

    wins   = [t for t in closed if t.pnl_r > 0]
    losses = [t for t in closed if t.pnl_r <= 0]

    pnl_series = [t.pnl_r for t in closed]
    cumulative = list(np.cumsum(pnl_series))
    peak       = cumulative[0]
    max_dd     = 0.0
    for v in cumulative:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    gross_profit = sum(t.pnl_r for t in wins)
    gross_loss   = abs(sum(t.pnl_r for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

    avg_win  = gross_profit / len(wins)  if wins   else 0
    avg_loss = gross_loss   / len(losses) if losses else 0

    # Sharpe (annualised, assuming H4 bars = 6 per day, 252 trading days)
    if len(pnl_series) > 1:
        mean_r = np.mean(pnl_series)
        std_r  = np.std(pnl_series, ddof=1)
        sharpe = (mean_r / std_r * math.sqrt(len(pnl_series))) if std_r else 0.0
    else:
        sharpe = 0.0

    by_outcome = {}
    for t in closed:
        by_outcome[t.outcome] = by_outcome.get(t.outcome, 0) + 1

    return {
        "total":          len(closed),
        "open":           len([t for t in trades if t.outcome == "OPEN"]),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(len(wins) / len(closed) * 100, 1),
        "net_r":          round(sum(pnl_series), 2),
        "avg_win_r":      round(avg_win, 2),
        "avg_loss_r":     round(avg_loss, 2),
        "profit_factor":  round(profit_factor, 2),
        "max_drawdown_r": round(max_dd, 2),
        "sharpe":         round(sharpe, 2),
        "by_outcome":     by_outcome,
    }


# ── Report writers ────────────────────────────────────────────────────────────

def _outcome_color(outcome: str) -> str:
    return {
        "WIN_TP1": "#c3e6cb", "WIN_TP2": "#85d48f",
        "WIN_TP3": "#28a745", "LOSS": "#f5c6cb", "OPEN": "#ffeeba",
    }.get(outcome, "#fff")


def save_backtest_html(all_trades: list[Trade], all_stats: dict,
                       symbol: str, timeframe: str) -> str:
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"backtest_{symbol}_{timeframe}_{ts}.html")

    stats = all_stats
    rows  = ""
    for t in all_trades:
        rows += f"""
        <tr style="background:{_outcome_color(t.outcome)}">
          <td>{t.entry_time.strftime('%Y-%m-%d %H:%M') if t.entry_time else ''}</td>
          <td>{t.direction}</td>
          <td>{t.entry:.5f}</td>
          <td>{t.sl:.5f}</td>
          <td>{t.tp1:.5f}</td>
          <td>{t.tp2:.5f}</td>
          <td>{t.tp3:.5f}</td>
          <td>{t.exit_time.strftime('%Y-%m-%d %H:%M') if t.exit_time else '—'}</td>
          <td>{f"{t.exit_price:.5f}" if t.exit_price else '—'}</td>
          <td>{t.outcome}</td>
          <td>{t.pnl_r:+.2f}R</td>
          <td>{t.score}/10</td>
          <td>{', '.join(t.patterns) or '—'}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Dante Backtest — {symbol} {timeframe}</title>
<style>
  body  {{ font-family: Arial, sans-serif; font-size: 12px; padding:20px; }}
  table {{ border-collapse:collapse; width:100%; }}
  th,td {{ border:1px solid #ccc; padding:5px 8px; white-space:nowrap; }}
  th    {{ background:#343a40; color:#fff; }}
  .stat {{ display:inline-block; margin:8px 20px 8px 0; }}
  .stat span {{ font-size:1.6em; font-weight:bold; }}
</style>
</head><body>
<h2>Dante Backtest — {symbol} [{timeframe}]</h2>
<p>Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>

<div>
  <div class="stat">Trades<br><span>{stats.get('total',0)}</span></div>
  <div class="stat">Win Rate<br><span>{stats.get('win_rate',0)}%</span></div>
  <div class="stat">Net R<br><span>{stats.get('net_r',0):+.2f}R</span></div>
  <div class="stat">Profit Factor<br><span>{stats.get('profit_factor',0)}</span></div>
  <div class="stat">Max DD<br><span>{stats.get('max_drawdown_r',0):.2f}R</span></div>
  <div class="stat">Sharpe<br><span>{stats.get('sharpe',0)}</span></div>
  <div class="stat">Avg Win<br><span>{stats.get('avg_win_r',0):+.2f}R</span></div>
  <div class="stat">Avg Loss<br><span>{stats.get('avg_loss_r',0):.2f}R</span></div>
</div>

<h3>Outcome breakdown</h3>
<p>{' | '.join(f"{k}: {v}" for k,v in stats.get('by_outcome',{}).items())}</p>

<h3>Trade Log</h3>
<table>
<thead><tr>
  <th>Entry Time</th><th>Dir</th><th>Entry</th><th>SL</th>
  <th>TP1</th><th>TP2</th><th>TP3</th>
  <th>Exit Time</th><th>Exit</th><th>Outcome</th><th>P&L</th>
  <th>Score</th><th>Patterns</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)
    return path


def save_backtest_csv(trades: list[Trade], symbol: str, timeframe: str) -> str:
    import csv
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"backtest_{symbol}_{timeframe}_{ts}.csv")
    fields = ["entry_time","direction","entry","sl","tp1","tp2","tp3",
              "exit_time","exit_price","outcome","pnl_r","score","patterns"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow({
                "entry_time":  t.entry_time,
                "direction":   t.direction,
                "entry":       t.entry,
                "sl":          t.sl,
                "tp1":         t.tp1,
                "tp2":         t.tp2,
                "tp3":         t.tp3,
                "exit_time":   t.exit_time or "",
                "exit_price":  t.exit_price,
                "outcome":     t.outcome,
                "pnl_r":       t.pnl_r,
                "score":       t.score,
                "patterns":    "|".join(t.patterns),
            })
    return path


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Dante Backtester")
    parser.add_argument("--symbol", default=None,    help="Single symbol (default: all)")
    parser.add_argument("--tf",     default=PRIMARY_TF, help="Timeframe (default: H4)")
    parser.add_argument("--bars",   type=int, default=CANDLE_COUNT, help="Bars of history")
    parser.add_argument("--demo",   action="store_true", help="Use synthetic data")
    args = parser.parse_args()

    connector = MT5Connector()
    if not args.demo:
        connected = connector.connect()
        if not connected:
            print("[INFO] Falling back to demo mode.")
    else:
        print("[INFO] Demo mode — synthetic data.")

    backtester = Backtester()
    symbols    = [args.symbol] if args.symbol else SYMBOLS

    grand_trades = []

    for symbol in symbols:
        df_raw  = connector.get_ohlcv(symbol, args.tf, args.bars)
        df_conf = connector.get_ohlcv(symbol, CONFIRM_TF, args.bars)

        if df_raw.empty or len(df_raw) < WARMUP_BARS + 10:
            print(f"[SKIP] {symbol} — insufficient data ({len(df_raw)} bars)")
            continue

        print(f"\n[BACKTEST] {symbol} [{args.tf}] — {len(df_raw)} bars …", flush=True)
        trades = backtester.run(df_raw, symbol, args.tf, df_conf)
        stats  = compute_stats(trades)
        grand_trades.extend(trades)

        # Per-symbol summary
        if stats.get("total", 0) == 0:
            print("  No trades generated.")
            continue

        print(f"  Trades: {stats['total']}  |  Win Rate: {stats['win_rate']}%  "
              f"|  Net R: {stats['net_r']:+.2f}  |  PF: {stats['profit_factor']}  "
              f"|  MaxDD: {stats['max_drawdown_r']:.2f}R  |  Sharpe: {stats['sharpe']}")

        html_path = save_backtest_html(trades, stats, symbol, args.tf)
        csv_path  = save_backtest_csv(trades, symbol, args.tf)
        print(f"  Reports → {html_path}")
        print(f"           {csv_path}")

    # Aggregate stats across all symbols
    if len(symbols) > 1 and grand_trades:
        print(f"\n{'='*60}")
        print("  AGGREGATE RESULTS (all symbols)")
        print(f"{'='*60}")
        agg = compute_stats(grand_trades)
        print(f"  Total Trades : {agg['total']}")
        print(f"  Win Rate     : {agg['win_rate']}%")
        print(f"  Net R        : {agg['net_r']:+.2f}R")
        print(f"  Profit Factor: {agg['profit_factor']}")
        print(f"  Max Drawdown : {agg['max_drawdown_r']:.2f}R")
        print(f"  Sharpe Ratio : {agg['sharpe']}")
        print(f"  Outcomes     : {agg['by_outcome']}")

    connector.disconnect()


if __name__ == "__main__":
    main()
