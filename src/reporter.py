"""Generate HTML/CSV signal reports."""
import os
import csv
from datetime import datetime
from src.signal_engine import Signal
from config.settings import REPORT_DIR

os.makedirs(REPORT_DIR, exist_ok=True)


def save_csv(signals: list[Signal]) -> str:
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"signals_{ts}.csv")
    fields = [
        "timestamp", "symbol", "timeframe", "direction", "score",
        "strength", "price", "atr", "sl", "tp1", "tp2", "tp3",
        "patterns", "reasons"
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in signals:
            w.writerow({
                "timestamp": s.timestamp.isoformat(),
                "symbol":    s.symbol,
                "timeframe": s.timeframe,
                "direction": s.direction,
                "score":     s.score,
                "strength":  s.strength,
                "price":     s.price,
                "atr":       s.atr,
                "sl":        s.sl,
                "tp1":       s.tp1,
                "tp2":       s.tp2,
                "tp3":       s.tp3,
                "patterns":  "|".join(s.patterns),
                "reasons":   " | ".join(s.reasons),
            })
    print(f"[REPORT] CSV saved → {path}")
    return path


def save_html(signals: list[Signal]) -> str:
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"signals_{ts}.html")

    def row_color(direction):
        return {"BUY": "#d4edda", "SELL": "#f8d7da"}.get(direction, "#fff3cd")

    rows_html = ""
    for s in sorted(signals, key=lambda x: x.score, reverse=True):
        rows_html += f"""
        <tr style="background:{row_color(s.direction)}">
          <td>{s.timestamp.strftime('%H:%M UTC')}</td>
          <td><b>{s.symbol}</b></td>
          <td>{s.timeframe}</td>
          <td><b>{s.direction}</b></td>
          <td>{s.score}/10</td>
          <td>{s.strength}</td>
          <td>{s.price:.5f}</td>
          <td>{s.atr:.5f}</td>
          <td>{s.sl:.5f}</td>
          <td>{s.tp1:.5f}</td>
          <td>{s.tp2:.5f}</td>
          <td>{s.tp3:.5f}</td>
          <td>{', '.join(s.patterns) or '—'}</td>
          <td style="font-size:0.8em">{' | '.join(s.reasons[:4])}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Dante Signal Report — {ts}</title>
<style>
  body  {{ font-family: Arial, sans-serif; font-size: 13px; padding: 20px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th,td {{ border: 1px solid #ccc; padding: 6px 10px; white-space: nowrap; }}
  th    {{ background: #343a40; color: #fff; }}
</style>
</head><body>
<h2>Dante — Swing Trading Signals</h2>
<p>Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
<table>
<thead><tr>
  <th>Time</th><th>Symbol</th><th>TF</th><th>Direction</th>
  <th>Score</th><th>Strength</th><th>Price</th><th>ATR</th>
  <th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
  <th>Patterns</th><th>Reasons</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)
    print(f"[REPORT] HTML saved → {path}")
    return path
