import json
import sys
import re

def safe_round(val, decimals=2):
    if val is None or val == 'N/A':
        return 'N/A'
    try:
        return round(float(val), decimals)
    except:
        return 'N/A'

def json_to_toon(json_data):
    """Converts the stock JSON data into TOON format for LLM input."""
    if not json_data:
        return ""

    # Check if 1W or laya analysis is present
    has_laya = any('laya_analysis' in s for s in json_data)
    has_1w = any('1W' in s.get('signals', {}) for s in json_data)

    if has_laya or has_1w:
        header = "{ticker,price,chg,confirmed,sig1d,sig1w,laya_act,laya_score,ema_stack,vwma_dist,macd_hist1d,macd_hist1w,adx1d,adx1w,bbpower,di_bull,pe,fwd_pe,peg,debt,roe,net_margin,op_margin,rev_growth,eps_growth,inst_own}"
        rows = []
        for s in json_data:
            t1d = s.get('tech_1d', {})
            t1w = s.get('tech_1w', {})
            f = s.get('fundamentals', {})
            la = s.get('laya_analysis', {})
            row = (
                f"{s['ticker']},"
                f"{s['price']},"
                f"{safe_round(t1d.get('change'), 1)},"
                f"{'Y' if s.get('is_double_confirmed') else 'N'},"
                f"{s['signals'].get('1D', 'N/A')},"
                f"{s['signals'].get('1W', s['signals'].get('4H', 'N/A'))},"
                f"{la.get('choice', 'N/A')},"
                f"{safe_round(la.get('composite_score', 'N/A'), 1)},"
                f"{'Y' if t1d.get('bullish_ema_stack') else 'N'},"
                f"{safe_round(t1d.get('vwma_dist_pct'), 1)},"
                f"{safe_round(t1d.get('macd_hist'), 2)},"
                f"{safe_round(t1w.get('macd_hist'), 2)},"
                f"{safe_round(t1d.get('ADX'), 1)},"
                f"{safe_round(t1w.get('ADX'), 1)},"
                f"{safe_round(t1d.get('BBPower'), 1)},"
                f"{'Y' if t1d.get('di_buyer_dominance') else 'N'},"
                f"{safe_round(f.get('trailingPE'), 1)},"
                f"{safe_round(f.get('forwardPE'), 1)},"
                f"{safe_round(f.get('pegRatio'), 2)},"
                f"{safe_round(f.get('debtToEquity'), 2)},"
                f"{safe_round(f.get('returnOnEquity'), 3)},"
                f"{safe_round(f.get('profitMargins'), 3)},"
                f"{safe_round(f.get('operatingMargins'), 3)},"
                f"{safe_round(f.get('revenueGrowth'), 3)},"
                f"{safe_round(f.get('earningsGrowth'), 3)},"
                f"{safe_round(f.get('heldPercentInstitutions'), 3)}"
            )
            rows.append(row)
        return f"stocks[{len(json_data)}]{header}:\n  " + "\n  ".join(rows)

    # Legacy format for 1D/4H
    header = "{ticker,price,confirmed,sig1d,sig4h,rsi1d,ema20_1d,ema50_1d,ema200_1d,macd1d,adx1d,vol1d,pe,pb,debt,roe,cr,margin,growth}"
    rows = []
    for s in json_data:
        t1d = s.get('tech_1d', {})
        f = s.get('fundamentals', {})
        row = (
            f"{s['ticker']},"
            f"{s['price']},"
            f"{'Y' if s.get('is_double_confirmed') else 'N'},"
            f"{s['signals'].get('1D', 'N/A')},"
            f"{s['signals'].get('4H', 'N/A')},"
            f"{safe_round(t1d.get('RSI'), 1)},"
            f"{safe_round(t1d.get('EMA20'), 1)},"
            f"{safe_round(t1d.get('EMA50'), 1)},"
            f"{safe_round(t1d.get('EMA200'), 1)},"
            f"{safe_round(t1d.get('MACD.macd'), 2)},"
            f"{safe_round(t1d.get('ADX'), 1)},"
            f"{t1d.get('volume', 'N/A')},"
            f"{safe_round(f.get('trailingPE'), 1)},"
            f"{safe_round(f.get('priceToBook'), 2)},"
            f"{safe_round(f.get('debtToEquity'), 2)},"
            f"{safe_round(f.get('returnOnEquity'), 3)},"
            f"{safe_round(f.get('currentRatio'), 2)},"
            f"{safe_round(f.get('profitMargins'), 3)},"
            f"{safe_round(f.get('revenueGrowth'), 3)}"
        )
        rows.append(row)
    return f"stocks[{len(json_data)}]{header}:\n  " + "\n  ".join(rows)

def extract_number(s):
    """Extracts a number and converts decimals (0.8) to percentages (80)."""
    try:
        match = re.search(r"[-+]?\d*\.\d+|\d+", str(s))
        if match:
            val = float(match.group())
            if 0 < val <= 1.0:
                return int(val * 100)
            return int(val)
    except:
        pass
    return 50

def toon_to_json(toon_str):
    """Converts TOON back to JSON list for Telegram."""
    results = []
    # Remove header line and empty lines
    lines = [l.strip() for l in toon_str.split('\n') if ',' in l and '{ticker' not in l.lower()]
    for line in lines:
        clean_line = re.sub(r'^[-*#\d\.\s]+\s+', '', line) if (line and not line[0].isalpha()) else line
        parts = [p.strip() for p in clean_line.split(',', 3)]
        if len(parts) >= 4:
            ticker_clean = re.sub(r'[^A-Z0-9&]', '', parts[0].upper())
            if ticker_clean in ('TICKER', 'SYMBOL', 'NAME', ''):
                continue
            results.append({
                "ticker": ticker_clean,
                "t_conf": extract_number(parts[1]),
                "f_conf": extract_number(parts[2]),
                "logic": parts[3].strip('"` \t')
            })
    return results

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(1)
    mode = sys.argv[1]
    input_data = sys.stdin.read()
    if mode == 'encode':
        print(json_to_toon(json.loads(input_data)))
    elif mode == 'decode':
        print(json.dumps(toon_to_json(input_data)))
