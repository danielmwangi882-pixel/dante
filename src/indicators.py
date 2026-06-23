"""All technical indicators for swing trading."""
import numpy as np
import pandas as pd
from config.settings import (
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    EMA_FAST, EMA_MED, EMA_SLOW, EMA_TREND,
    STOCH_K, STOCH_D, STOCH_SMOOTH,
    BB_PERIOD, BB_STD, ATR_PERIOD, ADX_PERIOD,
    CCI_PERIOD, WILLR_PERIOD, KC_EMA_PERIOD, KC_ATR_MULT,
    FIB_LEVELS
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()

def _true_range(df: pd.DataFrame) -> pd.Series:
    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift()).abs()
    lpc = (df["Low"]  - df["Close"].shift()).abs()
    return pd.concat([hl, hpc, lpc], axis=1).max(axis=1)


# ── Trend Indicators ─────────────────────────────────────────────────────────

def ema_all(df: pd.DataFrame) -> pd.DataFrame:
    df["EMA9"]   = _ema(df["Close"], EMA_FAST)
    df["EMA21"]  = _ema(df["Close"], EMA_MED)
    df["EMA50"]  = _ema(df["Close"], EMA_SLOW)
    df["EMA200"] = _ema(df["Close"], EMA_TREND)
    return df


def macd(df: pd.DataFrame) -> pd.DataFrame:
    fast = _ema(df["Close"], MACD_FAST)
    slow = _ema(df["Close"], MACD_SLOW)
    df["MACD"]        = fast - slow
    df["MACD_Signal"] = _ema(df["MACD"], MACD_SIGNAL)
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]
    return df


def adx(df: pd.DataFrame) -> pd.DataFrame:
    tr  = _true_range(df)
    up  = df["High"].diff()
    dn  = -df["Low"].diff()

    plus_dm  = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    atr14     = tr.ewm(span=ADX_PERIOD, adjust=False).mean()
    plus_di   = 100 * pd.Series(plus_dm,  index=df.index).ewm(span=ADX_PERIOD, adjust=False).mean() / atr14
    minus_di  = 100 * pd.Series(minus_dm, index=df.index).ewm(span=ADX_PERIOD, adjust=False).mean() / atr14
    dx        = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    df["ADX"]       = dx.ewm(span=ADX_PERIOD, adjust=False).mean()
    df["Plus_DI"]   = plus_di
    df["Minus_DI"]  = minus_di
    return df


# ── Momentum Indicators ───────────────────────────────────────────────────────

def rsi(df: pd.DataFrame) -> pd.DataFrame:
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - 100 / (1 + rs)
    return df


def stochastic(df: pd.DataFrame) -> pd.DataFrame:
    low_min  = df["Low"].rolling(STOCH_K).min()
    high_max = df["High"].rolling(STOCH_K).max()
    k_raw    = 100 * (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    df["Stoch_K"] = k_raw.rolling(STOCH_SMOOTH).mean()
    df["Stoch_D"] = df["Stoch_K"].rolling(STOCH_D).mean()
    return df


def cci(df: pd.DataFrame) -> pd.DataFrame:
    tp          = (df["High"] + df["Low"] + df["Close"]) / 3
    sma_tp      = tp.rolling(CCI_PERIOD).mean()
    mean_dev    = tp.rolling(CCI_PERIOD).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["CCI"]   = (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))
    return df


def williams_r(df: pd.DataFrame) -> pd.DataFrame:
    high_max  = df["High"].rolling(WILLR_PERIOD).max()
    low_min   = df["Low"].rolling(WILLR_PERIOD).min()
    df["WillR"] = -100 * (high_max - df["Close"]) / (high_max - low_min).replace(0, np.nan)
    return df


# ── Volatility Indicators ─────────────────────────────────────────────────────

def atr(df: pd.DataFrame) -> pd.DataFrame:
    df["ATR"] = _true_range(df).ewm(span=ATR_PERIOD, adjust=False).mean()
    return df


def bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    sma         = _sma(df["Close"], BB_PERIOD)
    std         = df["Close"].rolling(BB_PERIOD).std()
    df["BB_Mid"]   = sma
    df["BB_Upper"] = sma + BB_STD * std
    df["BB_Lower"] = sma - BB_STD * std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"]
    df["BB_Pct"]   = (df["Close"] - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"]).replace(0, np.nan)
    return df


def keltner_channel(df: pd.DataFrame) -> pd.DataFrame:
    ema_mid           = _ema(df["Close"], KC_EMA_PERIOD)
    atr_val           = _true_range(df).ewm(span=KC_EMA_PERIOD, adjust=False).mean()
    df["KC_Mid"]      = ema_mid
    df["KC_Upper"]    = ema_mid + KC_ATR_MULT * atr_val
    df["KC_Lower"]    = ema_mid - KC_ATR_MULT * atr_val
    return df


# ── Volume Indicators ─────────────────────────────────────────────────────────

def obv(df: pd.DataFrame) -> pd.DataFrame:
    direction = np.sign(df["Close"].diff()).fillna(0)
    df["OBV"] = (direction * df["Volume"]).cumsum()
    df["OBV_EMA"] = _ema(df["OBV"], 21)
    return df


def vwap(df: pd.DataFrame) -> pd.DataFrame:
    tp            = (df["High"] + df["Low"] + df["Close"]) / 3
    df["VWAP"]    = (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()
    return df


# ── Support / Resistance ──────────────────────────────────────────────────────

def pivot_points(df: pd.DataFrame) -> dict:
    """Classic pivot points from the last completed candle."""
    last = df.iloc[-2]
    h, l, c = last["High"], last["Low"], last["Close"]
    pp = (h + l + c) / 3
    return {
        "PP":  round(pp, 5),
        "R1":  round(2 * pp - l, 5),
        "R2":  round(pp + (h - l), 5),
        "R3":  round(h + 2 * (pp - l), 5),
        "S1":  round(2 * pp - h, 5),
        "S2":  round(pp - (h - l), 5),
        "S3":  round(l - 2 * (h - pp), 5),
    }


def fibonacci_levels(df: pd.DataFrame, lookback: int = 100) -> dict:
    """Fib retracement over the last `lookback` bars."""
    window = df.tail(lookback)
    swing_high = window["High"].max()
    swing_low  = window["Low"].min()
    diff = swing_high - swing_low
    levels = {}
    for lvl in FIB_LEVELS:
        label = f"Fib_{int(lvl * 1000):04d}"   # e.g. Fib_0618
        levels[label] = round(swing_high - lvl * diff, 5)
    levels["swing_high"] = swing_high
    levels["swing_low"]  = swing_low
    return levels


# ── Candlestick Pattern Detection ─────────────────────────────────────────────

def candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    body    = (c - o).abs()
    rng     = h - l
    avg_body = body.rolling(10).mean()

    # Doji
    df["Doji"] = (body <= 0.1 * rng) & (rng > 0)

    # Hammer / Hanging Man  (small body at top, long lower wick)
    lower_wick = np.where(c >= o, o - l, c - l)
    upper_wick = np.where(c >= o, h - c, h - o)
    df["Hammer"] = (
        (lower_wick >= 2 * body) &
        (upper_wick <= 0.3 * body) &
        (body >= 0.3 * avg_body)
    )

    # Inverted Hammer / Shooting Star
    df["InvertedHammer"] = (
        (upper_wick >= 2 * body) &
        (lower_wick <= 0.3 * body) &
        (body >= 0.3 * avg_body)
    )

    # Bullish Engulfing
    df["BullEngulf"] = (
        (c > o) &
        (c.shift() < o.shift()) &
        (c > o.shift()) &
        (o < c.shift())
    )

    # Bearish Engulfing
    df["BearEngulf"] = (
        (c < o) &
        (c.shift() > o.shift()) &
        (c < o.shift()) &
        (o > c.shift())
    )

    # Morning Star (3-bar bullish reversal)
    df["MorningStar"] = (
        (c.shift(2) < o.shift(2)) &                         # bar-2: big bearish
        (body.shift(1) < 0.5 * avg_body.shift(1)) &         # bar-1: small body
        (c > o) &                                            # bar-0: bullish
        (c > (o.shift(2) + c.shift(2)) / 2)                 # closes above midpoint
    )

    # Evening Star (3-bar bearish reversal)
    df["EveningStar"] = (
        (c.shift(2) > o.shift(2)) &
        (body.shift(1) < 0.5 * avg_body.shift(1)) &
        (c < o) &
        (c < (o.shift(2) + c.shift(2)) / 2)
    )

    # Piercing Line (bullish)
    df["PiercingLine"] = (
        (c.shift() < o.shift()) &
        (c > o) &
        (o < c.shift()) &
        (c > (o.shift() + c.shift()) / 2)
    )

    # Dark Cloud Cover (bearish)
    df["DarkCloud"] = (
        (c.shift() > o.shift()) &
        (c < o) &
        (o > c.shift()) &
        (c < (o.shift() + c.shift()) / 2)
    )

    # Three White Soldiers (strong bullish)
    df["ThreeWhiteSoldiers"] = (
        (c > o) & (c.shift() > o.shift()) & (c.shift(2) > o.shift(2)) &
        (c > c.shift()) & (c.shift() > c.shift(2)) &
        (o > o.shift()) & (o.shift() > o.shift(2))
    )

    # Three Black Crows (strong bearish)
    df["ThreeBlackCrows"] = (
        (c < o) & (c.shift() < o.shift()) & (c.shift(2) < o.shift(2)) &
        (c < c.shift()) & (c.shift() < c.shift(2)) &
        (o < o.shift()) & (o.shift() < o.shift(2))
    )

    return df


# ── Master: apply all indicators ─────────────────────────────────────────────

def apply_all(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = ema_all(df)
    df = macd(df)
    df = adx(df)
    df = rsi(df)
    df = stochastic(df)
    df = cci(df)
    df = williams_r(df)
    df = atr(df)
    df = bollinger_bands(df)
    df = keltner_channel(df)
    df = obv(df)
    df = vwap(df)
    df = candlestick_patterns(df)
    return df
