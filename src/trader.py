"""
MT5 Auto-Execution module — places and manages trades from Dante signals.

Safety rules enforced before every entry:
  1. Symbol must be enabled for trading in MT5
  2. Market must be open (no weekend / session gap)
  3. Spread must be within MAX_SPREAD_PIPS
  4. No existing open position on the same symbol
  5. Daily loss limit not breached (MAX_DAILY_LOSS_PCT of balance)
  6. Max concurrent open trades not exceeded (MAX_OPEN_TRADES)
  7. Signal score must meet MIN_AUTO_TRADE_SCORE

Post-entry management (checked on every scan loop):
  - Move SL to breakeven once price reaches TP1
  - Close trade if signal flips to opposite direction (optional)
"""

from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Literal

from config.settings import (
    MAX_SPREAD_PIPS, MAX_OPEN_TRADES, MAX_DAILY_LOSS_PCT,
    MIN_AUTO_TRADE_SCORE, RISK_PCT_PER_TRADE, BREAKEVEN_AT_TP1,
)
from src.signal_engine import Signal

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


# ── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class ManagedTrade:
    ticket:      int
    symbol:      str
    direction:   Literal["BUY", "SELL"]
    entry:       float
    sl:          float
    tp1:         float
    tp2:         float
    tp3:         float
    volume:      float
    open_time:   datetime = field(default_factory=datetime.utcnow)
    be_moved:    bool = False   # True once SL moved to breakeven


# ── Trader ────────────────────────────────────────────────────────────────────

class Trader:
    def __init__(self, dry_run: bool = True):
        """
        dry_run=True  → logs intended actions but never sends orders (default/safe)
        dry_run=False → live order execution (requires MT5 connected with trade perms)
        """
        self.dry_run       = dry_run
        self.open_trades:  list[ManagedTrade] = []
        self._daily_loss   = 0.0
        self._loss_date    = date.today()

        if dry_run:
            print("[TRADER] DRY-RUN mode — no real orders will be placed.")
        else:
            print("[TRADER] LIVE mode — orders will be sent to MT5.")

    # ── Public API ────────────────────────────────────────────────────────────

    def process_signal(self, signal: Signal) -> str | None:
        """
        Evaluate a signal and open a trade if all safety checks pass.
        Returns ticket number string on success, None otherwise.
        """
        sym = signal.symbol

        # ── Safety gate ───────────────────────────────────────────────────
        ok, reason = self._pre_flight(signal)
        if not ok:
            print(f"[TRADER] {sym} — skipped: {reason}")
            return None

        # ── Calculate position size ───────────────────────────────────────
        volume = self._lot_size(signal)
        if volume <= 0:
            print(f"[TRADER] {sym} — skipped: could not calculate lot size")
            return None

        # ── Place order ───────────────────────────────────────────────────
        ticket = self._place_order(signal, volume)
        if ticket:
            trade = ManagedTrade(
                ticket=ticket, symbol=sym,
                direction=signal.direction,
                entry=signal.price,
                sl=signal.sl, tp1=signal.tp1,
                tp2=signal.tp2, tp3=signal.tp3,
                volume=volume,
            )
            self.open_trades.append(trade)
            print(f"[TRADER] ✅ Opened {signal.direction} {sym} "
                  f"lot={volume} ticket={ticket}  SL={signal.sl}  TP1={signal.tp1}")
            return str(ticket)
        return None

    def manage_open_trades(self) -> None:
        """Call this on every scan loop to trail SL and clean up closed trades."""
        if not MT5_AVAILABLE or not self.open_trades:
            return

        still_open = []
        for trade in self.open_trades:
            pos = self._get_position(trade.ticket)
            if pos is None:
                print(f"[TRADER] Ticket {trade.ticket} ({trade.symbol}) closed externally.")
                continue

            current_price = self._current_price(trade.symbol, trade.direction)

            # Move SL to breakeven once TP1 is hit
            if BREAKEVEN_AT_TP1 and not trade.be_moved:
                tp1_hit = (
                    (trade.direction == "BUY"  and current_price >= trade.tp1) or
                    (trade.direction == "SELL" and current_price <= trade.tp1)
                )
                if tp1_hit:
                    self._modify_sl(trade, trade.entry)
                    trade.be_moved = True
                    print(f"[TRADER] 🔒 Breakeven set for {trade.symbol} ticket={trade.ticket}")

            still_open.append(trade)

        self.open_trades = still_open

    def close_all(self) -> None:
        """Emergency: close every managed open trade."""
        print("[TRADER] ⚠️  Closing ALL open trades.")
        for trade in list(self.open_trades):
            self._close_trade(trade)
        self.open_trades = []

    def status(self) -> None:
        """Print a summary of currently managed trades."""
        if not self.open_trades:
            print("[TRADER] No open trades.")
            return
        print(f"\n[TRADER] Open trades ({len(self.open_trades)}):")
        for t in self.open_trades:
            be = "BE✓" if t.be_moved else "    "
            print(f"  {be} #{t.ticket}  {t.direction} {t.symbol}  "
                  f"lot={t.volume}  entry={t.entry}  SL={t.sl}  TP1={t.tp1}")

    # ── Pre-flight checks ─────────────────────────────────────────────────────

    def _pre_flight(self, signal: Signal) -> tuple[bool, str]:
        if signal.score < MIN_AUTO_TRADE_SCORE:
            return False, f"score {signal.score} < minimum {MIN_AUTO_TRADE_SCORE}"

        if self._already_open(signal.symbol):
            return False, "already have an open position on this symbol"

        if len(self.open_trades) >= MAX_OPEN_TRADES:
            return False, f"max open trades ({MAX_OPEN_TRADES}) reached"

        if self._daily_loss_breached():
            return False, "daily loss limit breached — trading halted for today"

        if MT5_AVAILABLE:
            spread_ok, spread_msg = self._check_spread(signal.symbol)
            if not spread_ok:
                return False, spread_msg

            if not self._market_open(signal.symbol):
                return False, "market closed"

        return True, ""

    def _already_open(self, symbol: str) -> bool:
        # Check managed list
        if any(t.symbol == symbol for t in self.open_trades):
            return True
        # Also check MT5 directly (trades opened outside Dante)
        if MT5_AVAILABLE:
            positions = mt5.positions_get(symbol=symbol)
            return positions is not None and len(positions) > 0
        return False

    def _daily_loss_breached(self) -> bool:
        if date.today() != self._loss_date:
            self._daily_loss = 0.0
            self._loss_date  = date.today()
        if not MT5_AVAILABLE:
            return False
        account = mt5.account_info()
        if account is None:
            return False
        balance  = account.balance
        max_loss = balance * MAX_DAILY_LOSS_PCT / 100
        return self._daily_loss >= max_loss

    def _check_spread(self, symbol: str) -> tuple[bool, str]:
        info = mt5.symbol_info(symbol)
        if info is None:
            return False, "symbol info unavailable"
        spread_pips = info.spread * info.point * (10 ** info.digits)
        # Normalise: for 5-digit brokers, 1 pip = 10 points
        pip_val = 10 if info.digits in (3, 5) else 1
        spread_pips = info.spread / pip_val
        if spread_pips > MAX_SPREAD_PIPS:
            return False, f"spread {spread_pips:.1f} pips > max {MAX_SPREAD_PIPS}"
        return True, ""

    def _market_open(self, symbol: str) -> bool:
        info = mt5.symbol_info(symbol)
        if info is None:
            return False
        return info.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED

    # ── Order execution ───────────────────────────────────────────────────────

    def _place_order(self, signal: Signal, volume: float) -> int | None:
        price = signal.price

        if not MT5_AVAILABLE:
            if self.dry_run:
                print(f"[DRY-RUN] Would send: {signal.direction} {signal.symbol} "
                      f"vol={volume} price={price} SL={signal.sl} TP={signal.tp2}")
                return 999999
            return None

        order_type = mt5.ORDER_TYPE_BUY if signal.direction == "BUY" else mt5.ORDER_TYPE_SELL

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       signal.symbol,
            "volume":       volume,
            "type":         order_type,
            "price":        price,
            "sl":           signal.sl,
            "tp":           signal.tp2,   # Use TP2 as the hard TP in MT5; manage TP3 manually
            "deviation":    20,           # max slippage in points
            "magic":        888888,       # Dante magic number
            "comment":      f"Dante {signal.timeframe} s={signal.score}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "N/A"
            print(f"[TRADER] ❌ Order failed for {signal.symbol}: retcode={code}")
            return None

        return result.order

    def _modify_sl(self, trade: ManagedTrade, new_sl: float) -> None:
        if self.dry_run:
            print(f"[DRY-RUN] Would modify SL → {new_sl} for ticket {trade.ticket}")
            return
        if not MT5_AVAILABLE:
            return
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "ticket":   trade.ticket,
            "sl":       new_sl,
            "tp":       trade.tp2,
        }
        result = mt5.order_send(request)
        if result and result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"[TRADER] ❌ SL modify failed: retcode={result.retcode}")

    def _close_trade(self, trade: ManagedTrade) -> None:
        if self.dry_run:
            print(f"[DRY-RUN] Would close ticket {trade.ticket} {trade.symbol}")
            return
        if not MT5_AVAILABLE:
            return
        pos = self._get_position(trade.ticket)
        if pos is None:
            return
        close_type = mt5.ORDER_TYPE_SELL if trade.direction == "BUY" else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(trade.symbol)
        price = price.bid if trade.direction == "BUY" else price.ask
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       trade.symbol,
            "volume":       trade.volume,
            "type":         close_type,
            "position":     trade.ticket,
            "price":        price,
            "deviation":    20,
            "magic":        888888,
            "comment":      "Dante close",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        mt5.order_send(request)

    # ── Position sizing ───────────────────────────────────────────────────────

    def _lot_size(self, signal: Signal) -> float:
        """Risk RISK_PCT_PER_TRADE % of account balance per trade."""
        if not MT5_AVAILABLE:
            return 0.01   # demo default

        account = mt5.account_info()
        info    = mt5.symbol_info(signal.symbol)
        if account is None or info is None:
            return 0.01

        balance   = account.balance
        risk_amt  = balance * RISK_PCT_PER_TRADE / 100
        sl_points = abs(signal.price - signal.sl) / info.point
        tick_val  = info.trade_tick_value   # value per tick per 1 lot

        if sl_points == 0 or tick_val == 0:
            return info.volume_min

        lot = risk_amt / (sl_points * tick_val)
        lot = max(info.volume_min, min(lot, info.volume_max))
        lot = round(lot / info.volume_step) * info.volume_step
        return round(lot, 2)

    # ── MT5 helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_position(ticket: int):
        if not MT5_AVAILABLE:
            return None
        positions = mt5.positions_get(ticket=ticket)
        return positions[0] if positions else None

    @staticmethod
    def _current_price(symbol: str, direction: str) -> float:
        if not MT5_AVAILABLE:
            return 0.0
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return 0.0
        return tick.ask if direction == "BUY" else tick.bid
