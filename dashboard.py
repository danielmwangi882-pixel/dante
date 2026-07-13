"""
Dante Web Dashboard — Flask app showing live signals, history, and risk stats.

Usage:
  python dashboard.py               # starts on http://localhost:5000
  python dashboard.py --port 8080   # custom port

The dashboard auto-refreshes every 30 seconds.
It reads from logs/signals.log and logs/risk_state.json — no MT5 needed.
"""

import argparse
import json
import os
import re
from datetime import datetime

from flask import Flask, render_template_string, jsonify

from config.settings import LOG_DIR, REPORT_DIR

app = Flask(__name__)

# ── Data readers ──────────────────────────────────────────────────────────────

def read_signals(limit: int = 100) -> list[dict]:
    """Parse logs/signals.log into a list of signal dicts."""
    path = os.path.join(LOG_DIR, "signals.log")
    if not os.path.exists(path):
        return []
    signals = []
    pattern = re.compile(
        r"(?P<time>\S+ \S+) \| (?P<direction>BUY|SELL) (?P<symbol>\S+) "
        r"\[(?P<tf>\S+)\] score=(?P<score>\d+) strength=(?P<strength>\S+) "
        r"price=(?P<price>[\d.]+) sl=(?P<sl>[\d.]+) tp1=(?P<tp1>[\d.]+) "
        r"tp2=(?P<tp2>[\d.]+) tp3=(?P<tp3>[\d.]+)"
    )
    with open(path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                signals.append(m.groupdict())
    return list(reversed(signals))[:limit]


def read_risk() -> dict:
    path = os.path.join(LOG_DIR, "risk_state.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def read_charts() -> list[str]:
    chart_dir = os.path.join(REPORT_DIR, "charts")
    if not os.path.exists(chart_dir):
        return []
    files = [f for f in os.listdir(chart_dir) if f.endswith(".png")]
    files.sort(reverse=True)
    return files[:20]


# ── HTML template ─────────────────────────────────────────────────────────────

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>Dante — Trading Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body   { background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
    a      { color: #58a6ff; text-decoration: none; }
    header { background: #161b22; border-bottom: 1px solid #30363d; padding: 14px 24px;
             display: flex; align-items: center; justify-content: space-between; }
    header h1 { font-size: 1.3em; color: #f0f6fc; letter-spacing: 1px; }
    .badge    { background: #238636; color: #fff; padding: 3px 10px; border-radius: 12px; font-size: 12px; }
    .badge.warn  { background: #9e6a03; }
    .badge.halt  { background: #da3633; }
    .grid  { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
             gap: 12px; padding: 20px 24px 0; }
    .card  { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
             padding: 14px 16px; }
    .card .label { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: .5px; }
    .card .value { font-size: 1.6em; font-weight: 600; margin-top: 4px; color: #f0f6fc; }
    .card .value.green { color: #3fb950; }
    .card .value.red   { color: #f85149; }
    .card .value.gold  { color: #e3b341; }
    section { padding: 20px 24px; }
    section h2 { font-size: 1em; color: #8b949e; text-transform: uppercase;
                 letter-spacing: 1px; margin-bottom: 12px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }
    table  { width: 100%; border-collapse: collapse; }
    th     { background: #161b22; color: #8b949e; font-size: 11px; text-transform: uppercase;
             padding: 8px 12px; text-align: left; border-bottom: 1px solid #30363d; }
    td     { padding: 8px 12px; border-bottom: 1px solid #21262d; }
    tr:hover td { background: #161b22; }
    .buy   { color: #3fb950; font-weight: 600; }
    .sell  { color: #f85149; font-weight: 600; }
    .strong   { color: #e3b341; }
    .moderate { color: #58a6ff; }
    .score-bar { display: inline-block; height: 8px; border-radius: 4px;
                 background: linear-gradient(90deg, #238636, #3fb950); vertical-align: middle;
                 margin-left: 6px; }
    .chart-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; }
    .chart-grid img { width: 100%; border-radius: 6px; border: 1px solid #30363d; }
    footer { text-align: center; color: #484f58; padding: 20px; font-size: 12px; }
    @media (max-width: 600px) { .grid { grid-template-columns: 1fr 1fr; } }
  </style>
</head>
<body>

<header>
  <h1>⚡ DANTE</h1>
  <div>
    <span style="color:#8b949e; font-size:12px;">Last refresh: {{ now }}</span>
    &nbsp;
    <span class="badge {{ risk.get('status','OK')|lower }}">{{ risk.get('status','OK') }}</span>
  </div>
</header>

<!-- ── KPI cards ─────────────────────────────────────────────────────── -->
<div class="grid">
  <div class="card">
    <div class="label">Balance</div>
    <div class="value gold">${{ "{:,.2f}".format(risk.get('balance', 0)) }}</div>
  </div>
  <div class="card">
    <div class="label">Daily P&L</div>
    {% set dpnl = risk.get('daily_pnl_r', 0) %}
    <div class="value {{ 'green' if dpnl >= 0 else 'red' }}">{{ "{:+.2f}".format(dpnl) }}R</div>
  </div>
  <div class="card">
    <div class="label">Weekly P&L</div>
    {% set wpnl = risk.get('weekly_pnl_r', 0) %}
    <div class="value {{ 'green' if wpnl >= 0 else 'red' }}">{{ "{:+.2f}".format(wpnl) }}R</div>
  </div>
  <div class="card">
    <div class="label">Monthly P&L</div>
    {% set mpnl = risk.get('monthly_pnl_r', 0) %}
    <div class="value {{ 'green' if mpnl >= 0 else 'red' }}">{{ "{:+.2f}".format(mpnl) }}R</div>
  </div>
  <div class="card">
    <div class="label">Open Trades</div>
    <div class="value">{{ risk.get('open_positions', {})|length }}</div>
  </div>
  <div class="card">
    <div class="label">Daily Trades</div>
    <div class="value">{{ risk.get('daily_trades', 0) }}</div>
  </div>
  <div class="card">
    <div class="label">Max Drawdown</div>
    <div class="value red">{{ "{:.2f}".format(risk.get('max_dd_r', 0)) }}R</div>
  </div>
  <div class="card">
    <div class="label">Today's Signals</div>
    <div class="value gold">{{ signals|length }}</div>
  </div>
</div>

<!-- ── Open Positions ────────────────────────────────────────────────── -->
{% if risk.get('open_positions') %}
<section>
  <h2>Open Positions</h2>
  <table>
    <tr><th>Symbol</th><th>Direction</th></tr>
    {% for sym, dr in risk.get('open_positions', {}).items() %}
    <tr>
      <td>{{ sym }}</td>
      <td class="{{ dr|lower }}">{{ dr }}</td>
    </tr>
    {% endfor %}
  </table>
</section>
{% endif %}

<!-- ── Signal History ────────────────────────────────────────────────── -->
<section>
  <h2>Signal History</h2>
  {% if signals %}
  <table>
    <tr>
      <th>Time</th><th>Symbol</th><th>TF</th><th>Direction</th>
      <th>Score</th><th>Strength</th><th>Price</th>
      <th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
    </tr>
    {% for s in signals %}
    <tr>
      <td>{{ s.time }}</td>
      <td><b>{{ s.symbol }}</b></td>
      <td>{{ s.tf }}</td>
      <td class="{{ s.direction|lower }}">{{ s.direction }}</td>
      <td>
        {{ s.score }}/10
        <span class="score-bar" style="width:{{ (s.score|int * 16)|string }}px"></span>
      </td>
      <td class="{{ s.strength|lower }}">{{ s.strength }}</td>
      <td>{{ s.price }}</td>
      <td>{{ s.sl }}</td>
      <td>{{ s.tp1 }}</td>
      <td>{{ s.tp2 }}</td>
      <td>{{ s.tp3 }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p style="color:#8b949e; padding:12px 0;">No signals logged yet. Run <code>python main.py --loop</code> to start scanning.</p>
  {% endif %}
</section>

<!-- ── Recent Charts ─────────────────────────────────────────────────── -->
{% if charts %}
<section>
  <h2>Recent Charts</h2>
  <div class="chart-grid">
    {% for c in charts %}
    <div>
      <img src="/charts/{{ c }}" alt="{{ c }}" loading="lazy">
      <div style="font-size:11px; color:#8b949e; margin-top:4px;">{{ c }}</div>
    </div>
    {% endfor %}
  </div>
</section>
{% endif %}

<footer>Dante Signal Engine — auto-refreshes every 30s — {{ now }}</footer>

</body>
</html>
"""

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(
        TEMPLATE,
        signals=read_signals(),
        risk=read_risk(),
        charts=read_charts(),
        now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )


@app.route("/api/signals")
def api_signals():
    return jsonify(read_signals(50))


@app.route("/api/risk")
def api_risk():
    return jsonify(read_risk())


@app.route("/charts/<path:filename>")
def serve_chart(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join(REPORT_DIR, "charts"), filename)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Dante Web Dashboard")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"[DASHBOARD] Starting at http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
