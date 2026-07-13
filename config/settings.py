from dotenv import load_dotenv
import os

load_dotenv()

# MT5 connection
MT5_LOGIN = int(os.getenv("MT5_LOGIN", 0))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")  # Path to terminal64.exe if needed

# Symbols to scan
SYMBOLS = [
    "XAUUSD",   # Gold
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "GBPJPY",
    "EURJPY",
]

# Timeframes for swing trading (H4 primary, D1 confirmation)
TIMEFRAMES = {
    "H1":  "TIMEFRAME_H1",
    "H4":  "TIMEFRAME_H4",
    "D1":  "TIMEFRAME_D1",
    "W1":  "TIMEFRAME_W1",
}

PRIMARY_TF   = "H4"   # Signal generation timeframe
CONFIRM_TF   = "D1"   # Higher timeframe confirmation

# Candles to fetch
CANDLE_COUNT = 500

# Signal scan interval (minutes)
SCAN_INTERVAL = 15

# Signal strength thresholds
STRONG_SIGNAL_MIN_SCORE = 7   # out of 10
WEAK_SIGNAL_MIN_SCORE   = 4

# RSI
RSI_PERIOD     = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30

# MACD
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# EMAs
EMA_FAST   = 9
EMA_MED    = 21
EMA_SLOW   = 50
EMA_TREND  = 200

# Stochastic
STOCH_K      = 14
STOCH_D      = 3
STOCH_SMOOTH = 3
STOCH_OB     = 80
STOCH_OS     = 20

# Bollinger Bands
BB_PERIOD = 20
BB_STD    = 2.0

# ATR
ATR_PERIOD = 14

# ADX
ADX_PERIOD    = 14
ADX_THRESHOLD = 25   # Above = trending, below = ranging

# CCI
CCI_PERIOD     = 20
CCI_OVERBOUGHT = 100
CCI_OVERSOLD   = -100

# Williams %R
WILLR_PERIOD     = 14
WILLR_OVERBOUGHT = -20
WILLR_OVERSOLD   = -80

# Keltner Channel
KC_EMA_PERIOD = 20
KC_ATR_MULT   = 2.0

# Pivot Points
PIVOT_TYPE = "classic"   # classic | camarilla | woodie | fibonacci

# Fibonacci retracement levels
FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

# Notifications
NOTIFY_CONSOLE  = True
NOTIFY_LOGFILE  = True
NOTIFY_WEBHOOK  = bool(os.getenv("WEBHOOK_URL"))
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "")

# Telegram
NOTIFY_TELEGRAM     = bool(os.getenv("TELEGRAM_TOKEN"))
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
# Minimum signal score to send Telegram alert (avoid noise)
TELEGRAM_MIN_SCORE  = int(os.getenv("TELEGRAM_MIN_SCORE", 6))

LOG_DIR    = "logs"
REPORT_DIR = "reports"

# ── Auto-execution (trader.py) ────────────────────────────────────────────────

# Minimum signal score required to place a real trade
MIN_AUTO_TRADE_SCORE = int(os.getenv("MIN_AUTO_TRADE_SCORE", 7))

# Risk per trade as % of account balance
RISK_PCT_PER_TRADE = float(os.getenv("RISK_PCT_PER_TRADE", 1.0))

# Maximum number of concurrently open Dante-managed trades
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", 5))

# Maximum allowed spread in pips before skipping entry
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS", 3.0))

# Stop daily auto-trading if losses reach this % of account balance
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", 5.0))

# Move SL to breakeven automatically once TP1 is hit
BREAKEVEN_AT_TP1 = os.getenv("BREAKEVEN_AT_TP1", "true").lower() == "true"
