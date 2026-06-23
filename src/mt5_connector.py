"""MT5 connection and data fetching."""
import sys
import pandas as pd
from datetime import datetime
from config.settings import (
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH,
    CANDLE_COUNT, TIMEFRAMES
)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


class MT5Connector:
    def __init__(self):
        self.connected = False

    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            print("[WARN] MetaTrader5 package not installed. Running in demo/offline mode.")
            return False

        kwargs = {}
        if MT5_PATH:
            kwargs["path"] = MT5_PATH

        if not mt5.initialize(**kwargs):
            print(f"[ERROR] MT5 initialize failed: {mt5.last_error()}")
            return False

        if MT5_LOGIN:
            if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                print(f"[ERROR] MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                return False

        self.connected = True
        info = mt5.terminal_info()
        print(f"[OK] Connected to MT5 — {info.name} build {info.build}")
        return True

    def disconnect(self):
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False

    def get_ohlcv(self, symbol: str, timeframe_str: str, count: int = CANDLE_COUNT) -> pd.DataFrame:
        if not self.connected:
            return self._demo_ohlcv(symbol, count)

        tf = getattr(mt5, TIMEFRAMES[timeframe_str])
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            print(f"[WARN] No data for {symbol} {timeframe_str}: {mt5.last_error()}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={
            "open": "Open", "high": "High",
            "low": "Low", "close": "Close",
            "tick_volume": "Volume"
        }, inplace=True)
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def get_symbol_info(self, symbol: str) -> dict:
        if not self.connected:
            return {"symbol": symbol, "digits": 5, "point": 0.00001}
        info = mt5.symbol_info(symbol)
        if info is None:
            return {}
        return {
            "symbol":  info.name,
            "digits":  info.digits,
            "point":   info.point,
            "spread":  info.spread,
            "bid":     info.bid,
            "ask":     info.ask,
        }

    # ------------------------------------------------------------------
    # Demo mode: generate synthetic OHLCV so the engine runs without MT5
    # ------------------------------------------------------------------
    @staticmethod
    def _demo_ohlcv(symbol: str, count: int) -> pd.DataFrame:
        import numpy as np
        np.random.seed(hash(symbol) % (2**31))
        base = 1950.0 if "XAU" in symbol else 1.10
        dates = pd.date_range(end=datetime.utcnow(), periods=count, freq="4h")
        close = base + np.cumsum(np.random.randn(count) * base * 0.002)
        high  = close + np.abs(np.random.randn(count) * base * 0.001)
        low   = close - np.abs(np.random.randn(count) * base * 0.001)
        open_ = close + np.random.randn(count) * base * 0.0005
        vol   = np.random.randint(100, 2000, count).astype(float)
        return pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
            index=dates
        )
