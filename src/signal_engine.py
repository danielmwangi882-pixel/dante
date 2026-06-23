"""
Swing trading signal engine.

Scores each symbol 0-10 and outputs BUY / SELL / NEUTRAL.

Scoring system (each condition = 1 point):
  Trend (3 pts):
    1. Price above/below EMA200
    2. EMA9 > EMA21 > EMA50 (bullish stack) or inverse
    3. ADX > 25 (trending market)

  Momentum (3 pts):
    4. RSI in range (not OB/OS for trend; OB/OS for reversal)
    5. MACD histogram direction aligned
    6. Stochastic K/D crossover in correct zone

  Volatility / Price Action (2 pts):
    7. BB position (near lower band = buy setup, upper = sell)
    8. Candlestick pattern confirmation

  Volume / Market Structure (2 pts):
    9. OBV trending in signal direction
   10. Price near S/R (pivot or Fib level within 0.5 * ATR)
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from config.settings import (
    RSI_OVERBOUGHT, RSI_OVERSOLD,
    STOCH_OB, STOCH_OS,
    CCI_OVERBOUGHT, CCI_OVERSOLD,
    WILLR_OVERBOUGHT, WILLR_OVERSOLD,
    ADX_THRESHOLD,
    STRONG_SIGNAL_MIN_SCORE, WEAK_SIGNAL_MIN_SCORE,
)
from src.indicators import pivot_points, fibonacci_levels


Direction = Literal["BUY", "SELL", "NEUTRAL"]


@dataclass
class Signal:
    symbol:     str
    timeframe:  str
    direction:  Direction
    score:      int           # 0-10
    strength:   str           # STRONG / MODERATE / WEAK / NEUTRAL
    price:      float
    atr:        float
    sl:         float         # suggested stop-loss
    tp1:        float         # TP1 (1.5R)
    tp2:        float         # TP2 (3R)
    tp3:        float         # TP3 (5R)
    reasons:    list[str] = field(default_factory=list)
    patterns:   list[str] = field(default_factory=list)
    pivots:     dict     = field(default_factory=dict)
    fibs:       dict     = field(default_factory=dict)
    timestamp:  datetime = field(default_factory=datetime.utcnow)

    @property
    def rr_label(self) -> str:
        return f"SL={self.sl:.5f}  TP1={self.tp1:.5f}  TP2={self.tp2:.5f}  TP3={self.tp3:.5f}"


class SignalEngine:
    BULL_PATTERNS = [
        "Hammer", "BullEngulf", "MorningStar", "PiercingLine",
        "InvertedHammer", "ThreeWhiteSoldiers"
    ]
    BEAR_PATTERNS = [
        "InvertedHammer", "BearEngulf", "EveningStar", "DarkCloud",
        "Hammer", "ThreeBlackCrows"
    ]
    # InvertedHammer can be bearish too depending on context — handled by direction

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str,
                confirm_df: pd.DataFrame | None = None) -> Signal:
        row = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(row["Close"])
        atr_val = float(row["ATR"]) if not np.isnan(row["ATR"]) else price * 0.001

        # Higher-timeframe trend bias
        htf_bias = self._htf_bias(confirm_df) if confirm_df is not None else "NEUTRAL"

        bull_score, bear_score = 0, 0
        reasons_bull, reasons_bear = [], []

        # ── 1. Price vs EMA200 ────────────────────────────────────────────
        if price > row["EMA200"]:
            bull_score += 1
            reasons_bull.append("Price > EMA200 (uptrend)")
        else:
            bear_score += 1
            reasons_bear.append("Price < EMA200 (downtrend)")

        # ── 2. EMA stack ──────────────────────────────────────────────────
        if row["EMA9"] > row["EMA21"] > row["EMA50"]:
            bull_score += 1
            reasons_bull.append("EMA9>21>50 bullish stack")
        elif row["EMA9"] < row["EMA21"] < row["EMA50"]:
            bear_score += 1
            reasons_bear.append("EMA9<21<50 bearish stack")

        # ── 3. ADX – market is trending ───────────────────────────────────
        if row["ADX"] > ADX_THRESHOLD:
            if row["Plus_DI"] > row["Minus_DI"]:
                bull_score += 1
                reasons_bull.append(f"ADX {row['ADX']:.1f} trending bullish")
            else:
                bear_score += 1
                reasons_bear.append(f"ADX {row['ADX']:.1f} trending bearish")

        # ── 4. RSI ────────────────────────────────────────────────────────
        rsi = row["RSI"]
        if RSI_OVERSOLD < rsi < 55 and prev["RSI"] < rsi:
            bull_score += 1
            reasons_bull.append(f"RSI {rsi:.1f} rising from oversold")
        elif rsi < RSI_OVERSOLD:
            bull_score += 1
            reasons_bull.append(f"RSI {rsi:.1f} oversold — reversal potential")
        if RSI_OVERBOUGHT > rsi > 45 and prev["RSI"] > rsi:
            bear_score += 1
            reasons_bear.append(f"RSI {rsi:.1f} falling from overbought")
        elif rsi > RSI_OVERBOUGHT:
            bear_score += 1
            reasons_bear.append(f"RSI {rsi:.1f} overbought — reversal potential")

        # ── 5. MACD histogram ─────────────────────────────────────────────
        if row["MACD_Hist"] > 0 and row["MACD_Hist"] > prev["MACD_Hist"]:
            bull_score += 1
            reasons_bull.append("MACD histogram expanding bullish")
        elif row["MACD_Hist"] < 0 and row["MACD_Hist"] < prev["MACD_Hist"]:
            bear_score += 1
            reasons_bear.append("MACD histogram expanding bearish")
        # MACD zero-line cross
        if prev["MACD"] < 0 < row["MACD"]:
            bull_score += 1
            reasons_bull.append("MACD crossed above zero")
        elif prev["MACD"] > 0 > row["MACD"]:
            bear_score += 1
            reasons_bear.append("MACD crossed below zero")

        # ── 6. Stochastic ─────────────────────────────────────────────────
        if row["Stoch_K"] > row["Stoch_D"] and prev["Stoch_K"] <= prev["Stoch_D"] and row["Stoch_K"] < STOCH_OB:
            bull_score += 1
            reasons_bull.append(f"Stoch K/D bullish cross ({row['Stoch_K']:.1f})")
        if row["Stoch_K"] < row["Stoch_D"] and prev["Stoch_K"] >= prev["Stoch_D"] and row["Stoch_K"] > STOCH_OS:
            bear_score += 1
            reasons_bear.append(f"Stoch K/D bearish cross ({row['Stoch_K']:.1f})")

        # ── CCI bonus ─────────────────────────────────────────────────────
        if row["CCI"] > 0 and prev["CCI"] <= 0:
            bull_score += 1
            reasons_bull.append(f"CCI crossed above zero ({row['CCI']:.1f})")
        elif row["CCI"] < 0 and prev["CCI"] >= 0:
            bear_score += 1
            reasons_bear.append(f"CCI crossed below zero ({row['CCI']:.1f})")

        # ── Williams %R ───────────────────────────────────────────────────
        if row["WillR"] < WILLR_OVERSOLD:
            bull_score += 1
            reasons_bull.append(f"Williams %R oversold ({row['WillR']:.1f})")
        elif row["WillR"] > WILLR_OVERBOUGHT:
            bear_score += 1
            reasons_bear.append(f"Williams %R overbought ({row['WillR']:.1f})")

        # ── 7. Bollinger Bands ────────────────────────────────────────────
        if row["BB_Pct"] < 0.2:
            bull_score += 1
            reasons_bull.append("Price near BB lower band")
        elif row["BB_Pct"] > 0.8:
            bear_score += 1
            reasons_bear.append("Price near BB upper band")

        # BB squeeze (Bollinger inside Keltner = potential breakout)
        if row["BB_Upper"] < row["KC_Upper"] and row["BB_Lower"] > row["KC_Lower"]:
            reasons_bull.append("BB squeeze detected — breakout pending")
            reasons_bear.append("BB squeeze detected — breakout pending")

        # ── 8. Candlestick patterns ───────────────────────────────────────
        active_bull_pats = [p for p in self.BULL_PATTERNS if row.get(p, False)]
        active_bear_pats = [p for p in self.BEAR_PATTERNS if row.get(p, False)]
        if active_bull_pats:
            bull_score += 1
            reasons_bull.append(f"Bullish pattern: {', '.join(active_bull_pats)}")
        if active_bear_pats:
            bear_score += 1
            reasons_bear.append(f"Bearish pattern: {', '.join(active_bear_pats)}")

        # ── 9. OBV trend ──────────────────────────────────────────────────
        if row["OBV"] > row["OBV_EMA"]:
            bull_score += 1
            reasons_bull.append("OBV above its EMA (volume supports bulls)")
        else:
            bear_score += 1
            reasons_bear.append("OBV below its EMA (volume supports bears)")

        # ── 10. S/R proximity (Pivots & Fibs) ────────────────────────────
        pvt   = pivot_points(df)
        fibs  = fibonacci_levels(df)
        near_support, near_resist = self._near_level(price, atr_val, pvt, fibs)
        if near_support:
            bull_score += 1
            reasons_bull.append(f"Price near support: {near_support}")
        if near_resist:
            bear_score += 1
            reasons_bear.append(f"Price near resistance: {near_resist}")

        # ── HTF bias adjustment ───────────────────────────────────────────
        if htf_bias == "BULL":
            bull_score = min(10, bull_score + 1)
            reasons_bull.append("Higher-TF trend: BULLISH")
        elif htf_bias == "BEAR":
            bear_score = min(10, bear_score + 1)
            reasons_bear.append("Higher-TF trend: BEARISH")

        # ── Determine direction ───────────────────────────────────────────
        max_score = max(bull_score, bear_score)
        if bull_score > bear_score and bull_score >= WEAK_SIGNAL_MIN_SCORE:
            direction: Direction = "BUY"
            score = bull_score
            reasons = reasons_bull
            patterns = active_bull_pats
            sl  = round(price - 1.5 * atr_val, 5)
            tp1 = round(price + 1.5 * atr_val, 5)
            tp2 = round(price + 3.0 * atr_val, 5)
            tp3 = round(price + 5.0 * atr_val, 5)
        elif bear_score > bull_score and bear_score >= WEAK_SIGNAL_MIN_SCORE:
            direction = "SELL"
            score = bear_score
            reasons = reasons_bear
            patterns = active_bear_pats
            sl  = round(price + 1.5 * atr_val, 5)
            tp1 = round(price - 1.5 * atr_val, 5)
            tp2 = round(price - 3.0 * atr_val, 5)
            tp3 = round(price - 5.0 * atr_val, 5)
        else:
            direction = "NEUTRAL"
            score = max_score
            reasons = list(set(reasons_bull + reasons_bear))
            patterns = list(set(active_bull_pats + active_bear_pats))
            sl = tp1 = tp2 = tp3 = 0.0

        strength = (
            "STRONG"   if score >= STRONG_SIGNAL_MIN_SCORE else
            "MODERATE" if score >= WEAK_SIGNAL_MIN_SCORE   else
            "WEAK"
        )

        return Signal(
            symbol=symbol, timeframe=timeframe, direction=direction,
            score=score, strength=strength, price=price,
            atr=round(atr_val, 5), sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            reasons=reasons, patterns=patterns,
            pivots=pvt, fibs=fibs,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _htf_bias(df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return "NEUTRAL"
        row = df.iloc[-1]
        if row["Close"] > row["EMA200"] and row["EMA9"] > row["EMA21"]:
            return "BULL"
        if row["Close"] < row["EMA200"] and row["EMA9"] < row["EMA21"]:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _near_level(price: float, atr: float, pivots: dict, fibs: dict,
                    tolerance: float = 0.5) -> tuple[str | None, str | None]:
        threshold = tolerance * atr
        support  = None
        resist   = None
        all_levels = {**pivots, **fibs}
        for name, level in all_levels.items():
            if isinstance(level, float) and abs(price - level) <= threshold:
                if level < price:
                    support = name
                else:
                    resist  = name
        return support, resist
