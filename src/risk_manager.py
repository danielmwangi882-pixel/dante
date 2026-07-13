"""
Risk Management module — portfolio-level controls on top of per-trade sizing.

Responsibilities:
  - Track daily / weekly / monthly P&L in R and currency
  - Correlation filter (block correlated pairs trading same direction)
  - Drawdown monitor with escalating alerts
  - Daily trade count limit
  - Session filter (only trade London / NY sessions)
  - Exposure report
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from typing import Literal

import pytz

from config.settings import (
    RISK_PCT_PER_TRADE, MAX_DAILY_LOSS_PCT, MAX_OPEN_TRADES,
    LOG_DIR, REPORT_DIR,
)

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# ── Correlation groups ─────────────────────────────────────────────────────────
# Pairs in the same group are considered correlated.
# Dante will not open two trades in the same direction within a group.
CORRELATION_GROUPS: list[list[str]] = [
    ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"],   # USD weakness / strength
    ["USDJPY", "USDCAD", "USDCHF"],              # USD strength / weakness
    ["GBPUSD", "GBPJPY"],                        # GBP exposure
    ["EURUSD", "EURJPY"],                        # EUR exposure
    ["XAUUSD"],                                  # Gold — always standalone
]

# ── Trading sessions (UTC) ─────────────────────────────────────────────────────
SESSIONS = {
    "London":   (dtime(7, 0),  dtime(16, 0)),
    "New York": (dtime(12, 0), dtime(21, 0)),
}
SESSION_FILTER_ENABLED = os.getenv("SESSION_FILTER", "false").lower() == "true"

# ── Drawdown alert thresholds (% of balance) ──────────────────────────────────
DD_WARN  = float(os.getenv("DD_WARN_PCT",  "3.0"))
DD_HALT  = float(os.getenv("DD_HALT_PCT",  "5.0"))   # same as MAX_DAILY_LOSS_PCT


# ── Structs ───────────────────────────────────────────────────────────────────

@dataclass
class RiskSnapshot:
    timestamp:        datetime
    open_trades:      int
    daily_pnl_r:      float
    weekly_pnl_r:     float
    monthly_pnl_r:    float
    daily_trades:     int
    max_dd_r:         float
    status:           Literal["OK", "WARN", "HALT"]
    blocked_reasons:  list[str] = field(default_factory=list)


# ── Risk Manager ──────────────────────────────────────────────────────────────

class RiskManager:
    def __init__(self, balance: float = 10_000.0):
        self.balance         = balance
        self._today          = date.today()
        self._daily_pnl_r    = 0.0
        self._weekly_pnl_r   = 0.0
        self._monthly_pnl_r  = 0.0
        self._daily_trades   = 0
        self._peak_balance   = balance
        self._max_dd_r       = 0.0
        self._open_positions: dict[str, str] = {}   # symbol → direction
        self._trade_log: list[dict] = []
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    def can_trade(self, symbol: str, direction: str) -> tuple[bool, str]:
        """Return (True, '') if trade is allowed, else (False, reason)."""
        self._roll_periods()

        # Session filter
        if SESSION_FILTER_ENABLED and not self._in_active_session():
            return False, "outside London/NY trading hours"

        # Daily loss halt
        max_loss_r = (self.balance * MAX_DAILY_LOSS_PCT / 100) / self._r_value()
        if self._daily_pnl_r <= -max_loss_r:
            return False, f"daily loss limit reached ({self._daily_pnl_r:.2f}R)"

        # Max open trades
        if len(self._open_positions) >= MAX_OPEN_TRADES:
            return False, f"max open trades ({MAX_OPEN_TRADES}) reached"

        # Duplicate symbol
        if symbol in self._open_positions:
            return False, f"already have open position on {symbol}"

        # Correlation filter
        blocked = self._correlation_block(symbol, direction)
        if blocked:
            return False, f"correlated with open trade: {blocked}"

        return True, ""

    def register_open(self, symbol: str, direction: str) -> None:
        self._open_positions[symbol] = direction
        self._daily_trades += 1
        self._save_state()

    def register_close(self, symbol: str, pnl_r: float,
                       pnl_currency: float = 0.0) -> None:
        self._open_positions.pop(symbol, None)
        self._daily_pnl_r   += pnl_r
        self._weekly_pnl_r  += pnl_r
        self._monthly_pnl_r += pnl_r
        self.balance        += pnl_currency

        # Update max drawdown
        if self.balance > self._peak_balance:
            self._peak_balance = self.balance
        dd_r = (self._peak_balance - self.balance) / self._r_value()
        if dd_r > self._max_dd_r:
            self._max_dd_r = dd_r

        self._trade_log.append({
            "time":    datetime.utcnow().isoformat(),
            "symbol":  symbol,
            "pnl_r":   pnl_r,
            "balance": self.balance,
        })
        self._save_state()

    def snapshot(self) -> RiskSnapshot:
        self._roll_periods()
        status  = "OK"
        reasons = []
        max_loss_r = (self.balance * MAX_DAILY_LOSS_PCT / 100) / self._r_value()
        warn_r     = (self.balance * DD_WARN / 100) / self._r_value()

        if self._daily_pnl_r <= -max_loss_r:
            status = "HALT"
            reasons.append(f"Daily loss limit hit ({self._daily_pnl_r:.2f}R)")
        elif self._daily_pnl_r <= -warn_r:
            status = "WARN"
            reasons.append(f"Approaching daily loss limit ({self._daily_pnl_r:.2f}R)")

        return RiskSnapshot(
            timestamp       = datetime.utcnow(),
            open_trades     = len(self._open_positions),
            daily_pnl_r     = round(self._daily_pnl_r, 2),
            weekly_pnl_r    = round(self._weekly_pnl_r, 2),
            monthly_pnl_r   = round(self._monthly_pnl_r, 2),
            daily_trades    = self._daily_trades,
            max_dd_r        = round(self._max_dd_r, 2),
            status          = status,
            blocked_reasons = reasons,
        )

    def print_report(self) -> None:
        s = self.snapshot()
        sep = "─" * 50
        status_color = {"OK": "✅", "WARN": "⚠️ ", "HALT": "🛑"}.get(s.status, "")
        print(f"\n{sep}")
        print(f"  RISK REPORT  {status_color} {s.status}  "
              f"[{s.timestamp.strftime('%H:%M UTC')}]")
        print(f"{sep}")
        print(f"  Balance      : ${self.balance:,.2f}")
        print(f"  Open trades  : {s.open_trades} / {MAX_OPEN_TRADES}")
        print(f"  Daily trades : {s.daily_trades}")
        print(f"  Daily P&L    : {s.daily_pnl_r:+.2f}R")
        print(f"  Weekly P&L   : {s.weekly_pnl_r:+.2f}R")
        print(f"  Monthly P&L  : {s.monthly_pnl_r:+.2f}R")
        print(f"  Max Drawdown : {s.max_dd_r:.2f}R")
        if self._open_positions:
            print(f"  Positions    :")
            for sym, dr in self._open_positions.items():
                print(f"    • {sym} {dr}")
        if s.blocked_reasons:
            for r in s.blocked_reasons:
                print(f"  ⚠️  {r}")
        print(sep)

    def save_report(self) -> str:
        s   = self.snapshot()
        ts  = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REPORT_DIR, f"risk_{ts}.json")
        with open(path, "w") as f:
            json.dump({
                "timestamp":      s.timestamp.isoformat(),
                "balance":        self.balance,
                "open_trades":    s.open_trades,
                "daily_pnl_r":    s.daily_pnl_r,
                "weekly_pnl_r":   s.weekly_pnl_r,
                "monthly_pnl_r":  s.monthly_pnl_r,
                "daily_trades":   s.daily_trades,
                "max_drawdown_r": s.max_dd_r,
                "status":         s.status,
                "trade_log":      self._trade_log[-50:],
            }, f, indent=2)
        return path

    # ── Internals ─────────────────────────────────────────────────────────────

    def _r_value(self) -> float:
        """1R in currency based on current balance and risk %."""
        return max(self.balance * RISK_PCT_PER_TRADE / 100, 0.01)

    def _roll_periods(self) -> None:
        today = date.today()
        if today != self._today:
            self._daily_pnl_r  = 0.0
            self._daily_trades = 0
            self._today        = today
        if today.isocalendar()[1] != self._today.isocalendar()[1]:
            self._weekly_pnl_r = 0.0
        if today.month != self._today.month:
            self._monthly_pnl_r = 0.0

    def _correlation_block(self, symbol: str, direction: str) -> str | None:
        for group in CORRELATION_GROUPS:
            if symbol not in group:
                continue
            for open_sym, open_dir in self._open_positions.items():
                if open_sym in group and open_dir == direction:
                    return open_sym
        return None

    @staticmethod
    def _in_active_session() -> bool:
        now = datetime.utcnow().time()
        for _, (start, end) in SESSIONS.items():
            if start <= now <= end:
                return True
        return False

    # ── Persistence ───────────────────────────────────────────────────────────

    def _state_path(self) -> str:
        return os.path.join(LOG_DIR, "risk_state.json")

    def _save_state(self) -> None:
        state = {
            "date":           self._today.isoformat(),
            "balance":        self.balance,
            "peak_balance":   self._peak_balance,
            "daily_pnl_r":   self._daily_pnl_r,
            "weekly_pnl_r":  self._weekly_pnl_r,
            "monthly_pnl_r": self._monthly_pnl_r,
            "daily_trades":  self._daily_trades,
            "max_dd_r":      self._max_dd_r,
            "open_positions": self._open_positions,
            "trade_log":     self._trade_log,
        }
        with open(self._state_path(), "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self) -> None:
        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                s = json.load(f)
            saved_date = date.fromisoformat(s.get("date", "2000-01-01"))
            if saved_date == date.today():
                self._daily_pnl_r  = s.get("daily_pnl_r", 0.0)
                self._daily_trades = s.get("daily_trades", 0)
            self._weekly_pnl_r   = s.get("weekly_pnl_r", 0.0)
            self._monthly_pnl_r  = s.get("monthly_pnl_r", 0.0)
            self.balance         = s.get("balance", self.balance)
            self._peak_balance   = s.get("peak_balance", self.balance)
            self._max_dd_r       = s.get("max_dd_r", 0.0)
            self._open_positions = s.get("open_positions", {})
            self._trade_log      = s.get("trade_log", [])
        except Exception:
            pass   # corrupt state — start fresh
