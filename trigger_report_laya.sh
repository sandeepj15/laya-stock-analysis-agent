#!/bin/bash
# Manual Trigger for Stock Analysis Report with Laya System 1 Middle-Man (Enriched Edition)

# Ensure we are in the project folder
cd "$(dirname "$0")"

# Load environment variables if .env exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Detect Python environment (check local project virtualenvs first, then active venv, then system PATH)
if [ -x "./.venv/bin/python" ]; then
    PY="./.venv/bin/python"
elif [ -x "./venv/bin/python" ]; then
    PY="./venv/bin/python"
elif [ -x "./env/bin/python" ]; then
    PY="./env/bin/python"
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PY="$VIRTUAL_ENV/bin/python"
elif [ -n "$PYTHON_EXEC" ] && [ -x "$PYTHON_EXEC" ]; then
    PY="$PYTHON_EXEC"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "❌ Error: Python interpreter not found. Please install Python 3.10+ or set up a virtual environment."
    exit 1
fi

echo "=========================================================="
echo "🚀 STARTING ENRICHED LAYA + GEMINI STOCK INTELLIGENCE PIPELINE"
echo "=========================================================="
echo "Using Python: $PY"

# Pre-flight check: verify core dependencies are importable
if ! $PY -c "import laya, tradingview_ta, yfinance, telegram" 2>/dev/null; then
    echo ""
    echo "⚠️  Warning: Missing dependencies in detected Python ($PY)."
    echo "👉 Please set up your local virtual environment:"
    echo "   python3 -m venv .venv"
    echo "   source .venv/bin/activate"
    echo "   pip install -r requirements.txt"
    echo ""
fi

echo ""
echo "--- 1. Multi-Timeframe Market Scan (1D & 1W Enriched Technicals & Fundamentals) ---"
$PY ai_stock_agent_1d_1w.py

echo "--- 2. Laya Neural Decision Engine (4-Dimensional Middle-Man Pre-Screening) ---"
$PY laya_middleman.py --input stock_data_for_ai.json --output laya_screened_stocks.json --candidates ${CANDIDATE_LIMIT:-50} --top ${TOP_PICKS_LIMIT:-25} --device ${LAYA_DEVICE:-cpu}

echo ""
echo "--- 3. AI Deep Reasoning (Gemini via agy CLI) ---"
# Convert Laya-shortlisted stocks to enriched TOON format
DATA_TOON=$(cat laya_screened_stocks.json | $PY toon_utils.py encode)

PROMPT="Analyze these swing trade candidates pre-screened and scored by the Laya Decision Agent, represented in TOON format:
$DATA_TOON

For each stock, the columns represent:
- confirmed: 'Y' if technical strong signals are confirmed on both 1D and 1W timeframes.
- sig1d/sig1w: TradingView recommendation on 1D (Daily) and 1W (Weekly).
- laya_act: Laya System 1 decision (e.g. top_pick, neutral_mixed, avoid).
- laya_score: Laya composite conviction score (0-100).
- ema_stack: 'Y' if Price > EMA20 > EMA50 > EMA200 on 1D (bullish alignment).
- vwma_dist: % distance of price from institutional Volume Weighted Moving Average (positive = institutional accumulation above VWMA).
- macd_hist1d/macd_hist1w: MACD histogram on 1D and 1W (positive values indicate accelerating upward momentum).
- adx1d/adx1w: Average Directional Index (above 25 indicates strong trend).
- bbpower: Bull/Bear Power (positive values indicate dominant buyer control).
- di_bull: 'Y' if +DI > -DI (Buyer dominance over sellers).
- pe/fwd_pe: Trailing and Forward Price-to-Earnings ratios (lower forward PE indicates earnings growth).
- peg: Price/Earnings-to-Growth ratio (< 1.5 indicates growth at reasonable price).
- debt: Debt-to-Equity ratio (lower is safer, e.g. < 50 indicates pristine balance sheet).
- roe: Return on Equity.
- net_margin/op_margin: Net Profit Margin and Operating Margin (higher indicates pricing power).
- rev_growth/eps_growth: YoY Revenue and EPS Growth.
- inst_own: Institutional ownership percentage (FII/DII backing).

Identify the top 25 high-probability swing trades based on multi-timeframe technical confluence and fundamental health. Rank them from highest quality to lowest. Suggest integer confidence levels (0-100) for technicals (T_CONF_INT) and fundamentals (F_CONF_INT). IGNORE RSI entirely.
Prioritize:
1. Confluent 1D and 1W momentum, bullish EMA alignment, expanding MACD histograms, price > VWMA, and +DI buyer dominance.
2. High Laya decision scores and top_pick classifications.
3. High operating margins, low Debt-to-Equity, positive EPS and revenue growth.

Output ONLY in this format (no markdown formatting, no code fences, no headers, no quotes, no extra text):
TICKER, T_CONF_INT, F_CONF_INT, LOGIC
Example:
CAPLIPOINT, 95, 94, Bullish 1D/1W EMA stack, expanding MACD histogram above VWMA with 31% operating margin and negligible debt."

# Trigger AI Analysis via agy CLI
AI_OUT_RAW=$(agy --dangerously-skip-permissions -p "$PROMPT")

# Convert back to JSON for process_and_send.py
echo "$AI_OUT_RAW" | $PY toon_utils.py decode > ai_analysis_result.json

echo ""
echo "--- 4. Sending Intelligence Report to Telegram ---"
$PY process_and_send.py < ai_analysis_result.json

echo ""
echo "=========================================================="
echo "✅ ALL DONE! (Enriched Laya + Gemini Stock Report Dispatched)"
echo "=========================================================="
