import os
import asyncio
import json
import requests
import time
import warnings
from datetime import datetime, timedelta
import yfinance as yf
from dotenv import load_dotenv
from tradingview_ta import Interval, get_multiple_analysis
from concurrent.futures import ThreadPoolExecutor
import csv
import io

# Suppress urllib3 warning about LibreSSL
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

load_dotenv()

# --- CONFIGURATION ---
SCREENER = "india"
EXCHANGE = "NSE"
CACHE_FILE = "nse_symbols_cache.json"
FUNDAMENTAL_CACHE_FILE = "fundamental_cache.json"
DATA_OUTPUT_FILE = "stock_data_for_ai.json"
DATA_OUTPUT_FILE_1D_1W = "stock_data_1d_1w.json"

# --- 1. DYNAMIC STOCK LIST WITH CACHING ---
def fetch_index_csv(url, max_retries=3, timeout=30):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                f = io.StringIO(resp.text)
                reader = csv.DictReader(f)
                symbols = [row['Symbol'].strip() for row in reader if 'Symbol' in row]
                if symbols:
                    return symbols
            print(f"Attempt {attempt + 1} failed for {url}: Status {resp.status_code}")
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
        if attempt < max_retries - 1:
            time.sleep(2)
    return []

def get_nse_tickers_fast():
    cached_symbols = []
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                cached_symbols = cache_data.get('symbols', [])
                cache_age = datetime.now() - datetime.fromtimestamp(cache_data['timestamp'])
                # Only use cache if it is fresh (< 1 day) and contains a complete list of stocks (> 500)
                if cache_age < timedelta(days=1) and len(cached_symbols) > 500:
                    return cached_symbols
        except:
            pass

    print("Fetching NSE symbols from web (CSV)...")
    nifty500_symbols = fetch_index_csv("https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv")
    microcap_symbols = fetch_index_csv("https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv")
    
    # We require at least the Nifty 500 list to be successfully fetched to update the cache.
    if nifty500_symbols:
        all_symbols = nifty500_symbols + microcap_symbols
        unique_symbols = list(set(all_symbols))
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({'timestamp': time.time(), 'symbols': unique_symbols}, f)
            print(f"Successfully fetched and cached {len(unique_symbols)} symbols (Nifty 500: {len(nifty500_symbols)}, Microcap: {len(microcap_symbols)}).")
        except Exception as e:
            print(f"Failed to write cache file: {e}")
        return unique_symbols
    
    # Fallback to whatever is in the cache (even if older than 1 day or smaller)
    if cached_symbols:
        print(f"Failed to fetch fresh Nifty 500 constituents. Falling back to cached list ({len(cached_symbols)} symbols).")
        return cached_symbols
        
    print("Web fetch failed and no cached symbols available.")
    return []

# --- 2. MULTI-TIMEFRAME TECHNICAL SCANNER (1D & 1W) ---
def get_multi_tf_signals(tickers):
    print(f"Scanning {len(tickers)} stocks for 1D and 1W confirmation...")
    tv_symbols = [f"{EXCHANGE}:{t.replace('&', 'and')}" for t in tickers]

    signals = []
    # Batch processing (100 symbols per call to avoid TradingView timeouts)
    batch_size = 100
    for i in range(0, len(tv_symbols), batch_size):
        batch = tv_symbols[i:i + batch_size]
        try:
            # Fetch 1D and 1W concurrently using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as executor:
                f_1d = executor.submit(get_multiple_analysis, screener=SCREENER, interval=Interval.INTERVAL_1_DAY, symbols=batch)
                f_1w = executor.submit(get_multiple_analysis, screener=SCREENER, interval=Interval.INTERVAL_1_WEEK, symbols=batch)
                res_1d = f_1d.result()
                res_1w = f_1w.result()

            for key in res_1d.keys():
                analysis_1d = res_1d.get(key)
                analysis_1w = res_1w.get(key)
                if not analysis_1d: continue

                rec_1d = analysis_1d.summary.get("RECOMMENDATION", "NEUTRAL")
                rec_1w = analysis_1w.summary.get("RECOMMENDATION", "NEUTRAL") if analysis_1w else "NEUTRAL"

                is_strong_1d = "STRONG" in rec_1d
                is_strong_1w = "STRONG" in rec_1w
                double_confirmed = (is_strong_1d and is_strong_1w and rec_1d == rec_1w)

                # Filter for strong signals on 1D or 1W to keep data focused on high momentum
                if is_strong_1d or is_strong_1w:
                    signals.append({
                        "ticker": key.split(":")[1],
                        "recommendation_1d": rec_1d,
                        "recommendation_1w": rec_1w,
                        "double_confirmed": double_confirmed,
                        "tech_1d": analysis_1d.indicators,
                        "tech_1w": analysis_1w.indicators if analysis_1w else {}
                    })
        except Exception as e:
            print(f"Batch Scan Error: {e}")
            continue

    print(f"Identified {len(signals)} candidates with strong 1D or 1W signals (Double confirmed: {sum(1 for s in signals if s['double_confirmed'])}).")
    return signals

# --- 3. DATA PREPARATION WITH ENRICHED TECHNICALS & FUNDAMENTALS ---
def prepare_data_for_ai(strong_movers):
    print(f"Preparing enriched multi-timeframe data for {len(strong_movers)} stocks...")
    
    # Load fundamental cache
    fund_cache = {}
    if os.path.exists(FUNDAMENTAL_CACHE_FILE):
        try:
            with open(FUNDAMENTAL_CACHE_FILE, 'r') as f:
                fund_cache = json.load(f)
        except:
            fund_cache = {}

    ai_payload = []
    junk_keys = ['longBusinessSummary', 'address1', 'city', 'phone', 'website', 'companyOfficers']
    
    # Comprehensive indicator lists for 1D and 1W
    tech_keys_1d = [
        'close', 'change', 'volume', 'VWMA',
        'EMA20', 'EMA50', 'EMA200', 'SMA200',
        'RSI', 'MACD.macd', 'MACD.signal',
        'ADX', 'ADX+DI', 'ADX-DI',
        'BBPower', 'P.SAR', 'Ichimoku.BLine',
        'BB.upper', 'BB.lower', 'Stoch.K', 'Stoch.D',
        'Recommend.All'
    ]

    tech_keys_1w = [
        'close', 'change', 'volume', 'VWMA',
        'EMA20', 'EMA50', 'EMA200',
        'RSI', 'MACD.macd', 'MACD.signal',
        'ADX', 'ADX+DI', 'ADX-DI',
        'BBPower', 'Ichimoku.BLine',
        'Recommend.All'
    ]

    for s in strong_movers:
        try:
            ticker = s['ticker']
            ticker_ns = f"{ticker}.NS"
            
            # Check fundamental cache first (valid for 7 days)
            cached_entry = fund_cache.get(ticker)
            now = time.time()
            if cached_entry and (now - cached_entry.get('timestamp', 0) < 60*60*24*7):
                clean_fundamentals = cached_entry['data']
            else:
                stock = yf.Ticker(ticker_ns)
                full_info = stock.info
                clean_fundamentals = {k: v for k, v in full_info.items() if k not in junk_keys and v is not None}
                # Update cache
                fund_cache[ticker] = {'timestamp': now, 'data': clean_fundamentals}

            # Fast price check
            price = 0
            try:
                price = round(s['tech_1d'].get('close', 0), 2)
                if price == 0:
                   price_data = yf.download(ticker_ns, period="1d", interval="1m", progress=False)
                   if not price_data.empty:
                       price = round(float(price_data['Close'].iloc[-1]), 2)
            except:
                pass

            t1d_raw = s['tech_1d']
            t1w_raw = s['tech_1w']

            # Enriched technical extraction
            tech_1d = {k: t1d_raw.get(k) for k in tech_keys_1d}
            # Precompute derived technical metrics for 1D
            macd_1d = tech_1d.get('MACD.macd')
            signal_1d = tech_1d.get('MACD.signal')
            tech_1d['macd_hist'] = round(macd_1d - signal_1d, 3) if (macd_1d is not None and signal_1d is not None) else None

            vwma_1d = tech_1d.get('VWMA')
            tech_1d['vwma_dist_pct'] = round(((price - vwma_1d) / vwma_1d) * 100, 2) if (vwma_1d and vwma_1d > 0) else None

            di_plus_1d = tech_1d.get('ADX+DI')
            di_minus_1d = tech_1d.get('ADX-DI')
            tech_1d['di_buyer_dominance'] = (di_plus_1d > di_minus_1d) if (di_plus_1d is not None and di_minus_1d is not None) else None

            ema20_1d = tech_1d.get('EMA20')
            ema50_1d = tech_1d.get('EMA50')
            ema200_1d = tech_1d.get('EMA200')
            tech_1d['bullish_ema_stack'] = bool(price > ema20_1d > ema50_1d > ema200_1d) if (ema20_1d and ema50_1d and ema200_1d) else False

            # Enriched technical extraction for 1W
            tech_1w = {k: t1w_raw.get(k) for k in tech_keys_1w}
            macd_1w = tech_1w.get('MACD.macd')
            signal_1w = tech_1w.get('MACD.signal')
            tech_1w['macd_hist'] = round(macd_1w - signal_1w, 3) if (macd_1w is not None and signal_1w is not None) else None

            ema20_1w = tech_1w.get('EMA20')
            ema50_1w = tech_1w.get('EMA50')
            ema200_1w = tech_1w.get('EMA200')
            tech_1w['bullish_ema_stack'] = bool(price > ema20_1w > ema50_1w > ema200_1w) if (ema20_1w and ema50_1w and ema200_1w) else False

            ai_payload.append({
                "ticker": ticker,
                "price": price,
                "is_double_confirmed": s['double_confirmed'],
                "signals": {
                    "1D": s['recommendation_1d'],
                    "1W": s['recommendation_1w']
                },
                "tech_1d": tech_1d,
                "tech_1w": tech_1w,
                "sector": clean_fundamentals.get('sector', 'Others'),
                "industry": clean_fundamentals.get('industry', 'N/A'),
                "fundamentals": {
                    "trailingPE": clean_fundamentals.get('trailingPE'),
                    "forwardPE": clean_fundamentals.get('forwardPE'),
                    "priceToBook": clean_fundamentals.get('priceToBook'),
                    "pegRatio": clean_fundamentals.get('pegRatio'),
                    "debtToEquity": clean_fundamentals.get('debtToEquity'),
                    "returnOnEquity": clean_fundamentals.get('returnOnEquity'),
                    "returnOnAssets": clean_fundamentals.get('returnOnAssets'),
                    "profitMargins": clean_fundamentals.get('profitMargins'),
                    "operatingMargins": clean_fundamentals.get('operatingMargins'),
                    "grossMargins": clean_fundamentals.get('grossMargins'),
                    "revenueGrowth": clean_fundamentals.get('revenueGrowth'),
                    "earningsGrowth": clean_fundamentals.get('earningsGrowth') or clean_fundamentals.get('earningsQuarterlyGrowth'),
                    "currentRatio": clean_fundamentals.get('currentRatio'),
                    "freeCashflow": clean_fundamentals.get('freeCashflow'),
                    "operatingCashflow": clean_fundamentals.get('operatingCashflow'),
                    "marketCap": clean_fundamentals.get('marketCap'),
                    "heldPercentInstitutions": clean_fundamentals.get('heldPercentInstitutions'),
                    "heldPercentInsiders": clean_fundamentals.get('heldPercentInsiders'),
                    "beta": clean_fundamentals.get('beta'),
                    "dividendYield": clean_fundamentals.get('dividendYield')
                }
            })
        except Exception as e:
            continue

    # Save updated fundamental cache
    with open(FUNDAMENTAL_CACHE_FILE, 'w') as f:
        json.dump(fund_cache, f)

    # Save primary output and dedicated 1D/1W copy
    with open(DATA_OUTPUT_FILE, 'w') as f:
        json.dump(ai_payload, f, indent=2)
    with open(DATA_OUTPUT_FILE_1D_1W, 'w') as f:
        json.dump(ai_payload, f, indent=2)
    print(f"Data saved to {DATA_OUTPUT_FILE} and {DATA_OUTPUT_FILE_1D_1W} ({len(ai_payload)} stocks).")

# --- MAIN ---
if __name__ == "__main__":
    tickers = get_nse_tickers_fast()
    strong_movers = get_multi_tf_signals(tickers)
    if strong_movers:
        prepare_data_for_ai(strong_movers)
    else:
        print("No strong signals found today.")
