import os
import sys
import json
import asyncio
import telegram
import re
import html
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
DATA_FILE = "stock_data_for_ai.json"

async def main():
    if not sys.stdin or sys.stdin.isatty():
        print("Error: No AI input received from stdin.")
        return

    ai_input = sys.stdin.read()
    
    try:
        # Extract JSON list using regex
        match = re.search(r"(\[.*\])", ai_input.replace("\n", " "), re.DOTALL)
        if match:
            clean_json = match.group(1)
            ai_results = json.loads(clean_json)
        else:
            print("No JSON list found in AI output.")
            return
    except Exception as e:
        print(f"Error parsing AI JSON: {e}")
        return

    if not ai_results:
        print("Warning: AI results list is empty. Skipping Telegram notification.")
        return

    with open(DATA_FILE, 'r') as f:
        original_data = json.load(f)
        
    stock_map = {s['ticker']: s for s in original_data}

    # Also load Laya screened stocks if available
    laya_map = {}
    if os.path.exists("laya_screened_stocks.json"):
        try:
            with open("laya_screened_stocks.json", 'r') as lf:
                laya_data = json.load(lf)
                laya_map = {s['ticker']: s for s in laya_data}
        except Exception:
            pass

    processed_results = []
    for r in ai_results:
        ticker = r.get('ticker')
        if ticker not in stock_map: continue
        
        orig = stock_map[ticker]
        laya_info = laya_map.get(ticker, {})
        r['laya_score'] = laya_info.get('laya_score')
        r['laya_action'] = laya_info.get('laya_action')
        r['total'] = (r.get('t_conf', 0) + r.get('f_conf', 0)) / 2
        prefix = "⚡" if orig.get('is_double_confirmed') else ""
        r['display_ticker'] = f"{prefix}{ticker}"
        r['sig_label'] = "BUY" if "BUY" in orig.get('signals', {}).get('1D', '') else "SELL"
        r['price'] = orig.get('price', 0)
        r['sector'] = orig.get('sector', 'Others')
        r['logic'] = html.escape(r.get('logic', 'No logic provided'))
        processed_results.append(r)

    if not processed_results:
        print("Warning: No matching stocks found in processed results. Skipping Telegram notification.")
        return

    # Sort and pick top 25
    processed_results.sort(key=lambda x: x['total'], reverse=True)
    top_25 = processed_results[:25]

    sectors = {}
    for r in top_25:
        sec = r['sector']
        if sec not in sectors: sectors[sec] = []
        sectors[sec].append(r)

    report_body = ""
    idx = 1
    for sec, stocks in sectors.items():
        report_body += f"\n<b>📁 Sector: {sec}</b>\n<pre>"
        report_body += f"{'#':<2} | {'TICKER':<10} | {'PRICE':<8} | {'SIG':<4} | {'T':<2} | {'F':<2} | {'TOT'}\n"
        report_body += "-" * 42 + "\n"
        for r in stocks:
            report_body += f"{idx:<2} | {r['display_ticker'][:10]:<10} | {r['price']:<8} | {r['sig_label']:<4} | {r['t_conf']:<2} | {r['f_conf']:<2} | {r['total']:<4.1f}\n"
            idx += 1
        report_body += "</pre>"

    summary = "\n\n<b>🔥 Top High-Conviction Trades 🔥</b>\n"
    for i, r in enumerate(top_25[:3]):
        laya_str = f" | Laya: {r['laya_score']}" if r.get('laya_score') is not None else ""
        summary += f"{i + 1}. <b>{r['display_ticker']}</b> (AI: {r['total']:.0f}%{laya_str}): {r['logic']}\n"

    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    sub_title = "<i>⚡ = 1D + 1W Confirmed | Laya Neural + Gemini AI Analysis</i>" if laya_map else "<i>⚡ = Confirmed on both timeframes</i>"
    message_text = f"📊 <b>Double Confirmation Scan (Top 25)</b>\n{sub_title}\n{report_body}{summary}"

    # Final check for length
    if len(message_text) > 4000:
        message_text = message_text[:3950] + "\n... (Message truncated)"

    await bot.send_message(
        chat_id=TELEGRAM_CHANNEL_ID,
        text=message_text,
        parse_mode='HTML'
    )
    print("Report sent to Telegram successfully!")

if __name__ == "__main__":
    asyncio.run(main())
