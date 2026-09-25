#!/usr/bin/env python3
"""
Laya Middle-Man Decision Engine for Stock Pre-Screening (Enriched Institutional Edition).
Sits between the multi-timeframe market scan (1D & 1W technicals + fundamentals) and Gemini (System 2 deep reasoning).
Evaluates candidate stocks across 4 structured dimensions:
  1. Trend Structure (Multi-timeframe EMAs, VWMA, Parabolic SAR)
  2. Momentum & Institutional Order Flow (MACD histograms, ADX, +DI/-DI Buyer Dominance, Bull-Bear Power)
  3. Valuation & Capital Efficiency (PE, Forward PE, PEG, PB, Debt-to-Equity, Net & Operating Margins, ROE)
  4. Growth & Institutional Ownership (Revenue & EPS Growth YoY, FII/DII Institutional Ownership, Promoter Stake)

Filters out high-risk / deteriorating setups, ranks the highest conviction trades,
and outputs a dense shortlist for Gemini deep reasoning.
"""

import os
import sys
import json
import argparse
import time
from typing import List, Dict, Any

# Ensure laya is importable
try:
    from laya import Agent
except ImportError:
    print("Error: 'laya' package is not installed in current Python environment.")
    print("Install via: pip install laya")
    sys.exit(1)

# Structured Institutional Decision Rubric for Laya
LAYA_QUESTIONS = {
    "setup_rating": {
        "type": "choice",
        "instructions": "How do you classify this stock setup based on trend, momentum, valuation, and growth?",
        "criteria": {
            "top_pick": "High quality institutional swing trade with strong buy ratings, bullish moving average alignment, price above VWMA, expanding MACD histograms, dominant buyer control, negligible debt, and high margins.",
            "neutral_mixed": "Mixed trade setup with conflicting signals, average momentum, or moderate metrics.",
            "avoid": "High risk trade with sell ratings, broken technicals, price below VWMA, expanding bearish histograms, seller dominance, high debt risk, or deteriorating earnings."
        }
    },
    "is_high_conviction": {
        "type": "noul",
        "instructions": "Is this stock a high-conviction institutional swing trade candidate based on confluent technical strength and solid fundamentals?",
        "criteria": {
            "true": "High conviction setup with multi-timeframe alignment, strong institutional buyer control, and solid fundamentals",
            "false": "Low conviction, broken technical structure, negative momentum, or deteriorating fundamentals"
        }
    },
    "conviction_score": {
        "type": "score",
        "instructions": "Rate the swing trade setup quality from low risk-reward to top institutional quality.",
        "criteria": [
            "Low Quality / High Risk",
            "Average Setup",
            "Strong High-Conviction Setup",
            "Top Tier Institutional Quality"
        ]
    }
}


def translate_trend_structure(stock: Dict[str, Any]) -> str:
    """Translates trend and moving average indicators into clear semantic descriptions."""
    sigs = stock.get("signals", {})
    rec_1d = sigs.get("1D", "NEUTRAL")
    rec_1w = sigs.get("1W", "NEUTRAL")
    is_confirmed = stock.get("is_double_confirmed", False)
    t1d = stock.get("tech_1d", {}) or {}
    t1w = stock.get("tech_1w", {}) or {}
    price = stock.get("price", 0.0)
    
    parts = []
    # 1. Recommendation Signals
    if "BUY" in rec_1d and "BUY" in rec_1w:
        if is_confirmed:
            parts.append("Dual-timeframe strong institutional BUY recommendation confirmed across daily and weekly horizons.")
        else:
            parts.append("Bullish buy recommendations active across daily and weekly charts.")
    elif "SELL" in rec_1d and "SELL" in rec_1w:
        parts.append("Severe multi-timeframe SELL rating and active breakdown warning across daily and weekly horizons.")
    elif "SELL" in rec_1d:
        parts.append("Bearish daily sell rating indicating active short-term distribution.")
    elif "BUY" in rec_1d:
        parts.append("Daily buy rating with supportive technical expansion.")
    else:
        parts.append("Neutral or mixed signal structure across timeframes.")

    # 2. Moving Average Alignment
    stack_1d = t1d.get("bullish_ema_stack", False)
    stack_1w = t1w.get("bullish_ema_stack", False)
    ema50_1d = t1d.get("EMA50") or 0.0
    ema200_1d = t1d.get("EMA200") or 0.0
    golden_cross = (ema50_1d > ema200_1d) if (ema50_1d and ema200_1d) else False

    if stack_1d and stack_1w:
        parts.append("Flawless bullish moving average alignment with price leading above all daily and weekly exponential averages.")
    elif stack_1d:
        parts.append("Constructive daily bullish moving average alignment with price positioned comfortably above EMA 20, 50, and 200.")
    elif price > 0 and ema200_1d > 0 and price < ema200_1d:
        parts.append("Broken technical structure with price trapped below the critical 200-day long-term moving average.")
    else:
        parts.append("Mixed moving average alignment undergoing trend consolidation.")

    if golden_cross:
        parts.append("Long-term Golden Cross active.")

    # 3. Institutional VWMA Positioning
    vwma_dist = t1d.get("vwma_dist_pct")
    if vwma_dist is not None:
        if vwma_dist > 15.0:
            parts.append(f"Price is highly extended ({vwma_dist:+.1f}%) above institutional volume-weighted average price (VWMA), carrying elevated mean-reversion risk.")
        elif vwma_dist > 2.0:
            parts.append(f"Strong institutional accumulation trading {vwma_dist:+.1f}% above volume-weighted benchmark (VWMA).")
        elif vwma_dist >= 0.0:
            parts.append(f"Holding firm support directly above the institutional volume-weighted average price ({vwma_dist:+.1f}%).")
        elif vwma_dist > -5.0:
            parts.append(f"Slight weakness slipping {vwma_dist:+.1f}% below volume-weighted average price.")
        else:
            parts.append(f"Severe institutional distribution with price deeply depressed {vwma_dist:+.1f}% below volume-weighted average price.")

    # 4. Parabolic SAR Trail
    psar = t1d.get("P.SAR")
    if psar and price > 0:
        if price > psar:
            parts.append("Bullish trailing stop support intact.")
        else:
            parts.append("Bearish trailing stop overhead resisting advances.")

    return " ".join(parts)


def translate_momentum_and_flow(stock: Dict[str, Any]) -> str:
    """Translates momentum and directional flow into clear semantic descriptions."""
    t1d = stock.get("tech_1d", {}) or {}
    t1w = stock.get("tech_1w", {}) or {}
    parts = []

    # 1. MACD Histograms
    m1d = t1d.get("macd_hist") or 0.0
    m1w = t1w.get("macd_hist") or 0.0
    if m1d > 0 and m1w > 0:
        parts.append("Powerful upward momentum with dual-timeframe expanding MACD histograms on both daily and weekly charts.")
    elif m1d > 0 and m1w <= 0:
        parts.append("Daily momentum positive and expanding while weekly histogram remains lagging.")
    elif m1d <= 0 and m1w > 0:
        parts.append("Weekly momentum remains constructive but daily histogram shows short-term consolidation.")
    else:
        parts.append("Severe negative momentum with dual-timeframe expanding bearish MACD histograms.")

    # 2. Buyer vs Seller Dominance (+DI vs -DI)
    buyer_dom = t1d.get("di_buyer_dominance")
    di_plus = t1d.get("ADX+DI")
    di_minus = t1d.get("ADX-DI")
    if buyer_dom:
        if di_plus and di_plus > 30:
            parts.append("Decisive buyer dominance with bulls completely overwhelming sellers in institutional order flow.")
        else:
            parts.append("Buyer dominance maintained with positive directional flow (+DI > -DI).")
    else:
        if di_minus and di_minus > 30:
            parts.append("Aggressive seller dominance with bears in total control of order flow (-DI > +DI).")
        else:
            parts.append("Seller dominance in control of directional flow.")

    # 3. Bull / Bear Power
    bb = t1d.get("BBPower")
    if bb is not None:
        if bb > 50:
            parts.append("Exceptional bull power demonstrating aggressive institutional buying pressure.")
        elif bb > 0:
            parts.append("Positive bull power confirming solid buying interest.")
        elif bb < -50:
            parts.append("Extreme bear power reflecting heavy institutional liquidation.")
        else:
            parts.append("Negative bear power indicating persistent selling pressure.")

    # 4. ADX Trend Strength
    adx1d = t1d.get("ADX") or 0.0
    adx1w = t1w.get("ADX") or 0.0
    if adx1d > 25 and adx1w > 25:
        parts.append("Multi-timeframe ADX confirms a high-conviction, powerful directional trend.")
    elif adx1d > 25:
        parts.append("Strong daily directional trend strength underway.")
    else:
        parts.append("Moderate trend strength with choppy price action.")

    return " ".join(parts)


def translate_valuation_and_quality(stock: Dict[str, Any]) -> str:
    """Translates balance sheet leverage and profitability margins into clear semantic descriptions."""
    f = stock.get("fundamentals", {}) or {}
    sector = stock.get("sector", "Others")
    industry = stock.get("industry", "N/A")
    parts = [f"Sector: {sector} ({industry})."]

    # 1. Solvency & Debt Leverage
    debt = f.get("debtToEquity")
    if debt is not None:
        if debt < 15:
            parts.append("Pristine, fortress balance sheet with virtually zero financial debt.")
        elif debt < 60:
            parts.append("Healthy and conservative balance sheet with low, manageable debt.")
        elif debt < 120:
            parts.append("Moderate balance sheet leverage within manageable operating thresholds.")
        else:
            parts.append(f"Severely overleveraged balance sheet carrying dangerous financial debt risk (Debt/Equity: {debt:.1f}).")

    # 2. Operating Margins & Profitability
    op_m = f.get("operatingMargins")
    if op_m is not None:
        if op_m > 0.25:
            parts.append(f"Superior corporate pricing power with institutional-grade operating profit margins of {op_m*100:.1f}%.")
        elif op_m > 0.12:
            parts.append(f"Solid double-digit operating profitability of {op_m*100:.1f}%.")
        elif op_m > 0.05:
            parts.append(f"Modest operating margins of {op_m*100:.1f}%.")
        elif op_m > 0:
            parts.append(f"Razor-thin operating profit margins of {op_m*100:.1f}%, leaving low safety cushion.")
        else:
            parts.append(f"Negative operating profit margins ({op_m*100:.1f}%), burning cash at the operational level.")

    # 3. Capital Efficiency (ROE)
    roe = f.get("returnOnEquity")
    if roe is not None:
        if roe > 0.20:
            parts.append(f"Exceptional capital efficiency delivering a high Return on Equity of {roe*100:.1f}%.")
        elif roe > 0.12:
            parts.append(f"Good Return on Equity of {roe*100:.1f}%.")
        elif roe < 0:
            parts.append("Negative Return on Equity reflecting corporate losses.")

    # 4. Valuation Multiples (Forward P/E & PEG)
    fwd_pe = f.get("forwardPE")
    peg = f.get("pegRatio")
    if fwd_pe is not None and fwd_pe > 0:
        if fwd_pe < 15:
            parts.append(f"Very attractive valuation trading at a discounted forward P/E of {fwd_pe:.1f}.")
        elif fwd_pe < 35:
            parts.append(f"Reasonable valuation at a forward P/E of {fwd_pe:.1f}.")
        elif fwd_pe > 75:
            parts.append(f"Rich, premium valuation trading at an elevated forward P/E of {fwd_pe:.1f}.")

    if peg is not None and peg > 0:
        if peg < 1.0:
            parts.append("Exceptional growth at a reasonable price (undervalued PEG under 1.0).")
        elif peg < 1.5:
            parts.append("Fair growth valuation PEG ratio.")
        elif peg > 3.0:
            parts.append("High PEG ratio indicating valuation outpaces earnings growth.")

    return " ".join(parts)


def translate_growth_and_ownership(stock: Dict[str, Any]) -> str:
    """Translates YoY revenue/EPS growth and institutional backing into clear semantic descriptions."""
    f = stock.get("fundamentals", {}) or {}
    parts = []

    mcap = f.get("marketCap")
    if mcap:
        mcap_cr = f"₹{mcap/1e7:,.0f} Cr"
        parts.append(f"Market Capitalization: {mcap_cr}.")

    eps_g = f.get("earningsGrowth")
    rev_g = f.get("revenueGrowth")
    if eps_g is not None and rev_g is not None:
        if eps_g > 0.25 and rev_g > 0.15:
            parts.append(f"Robust hyper-growth with rapid YoY revenue expansion (+{rev_g*100:.1f}%) and earnings growth (+{eps_g*100:.1f}%).")
        elif eps_g > 0 and rev_g > 0:
            parts.append(f"Steady positive revenue (+{rev_g*100:.1f}%) and earnings (+{eps_g*100:.1f}%) growth.")
        elif eps_g < -0.20 and rev_g < -0.10:
            parts.append(f"Severe fundamental contraction with dropping revenue ({rev_g*100:.1f}%) and collapsing net income ({eps_g*100:.1f}%).")
        elif eps_g < 0:
            parts.append(f"Earnings contraction with declining year-over-year net income ({eps_g*100:.1f}%).")
    elif eps_g is not None:
        if eps_g > 0.20:
            parts.append(f"Strong earnings growth expansion (+{eps_g*100:.1f}% YoY).")
        elif eps_g < -0.20:
            parts.append(f"Deteriorating earnings with a {eps_g*100:.1f}% contraction.")

    inst_own = f.get("heldPercentInstitutions")
    prom_own = f.get("heldPercentInsiders")
    if inst_own is not None:
        if inst_own > 0.40:
            parts.append(f"Strong institutional ownership with {inst_own*100:.1f}% held by institutions (FIIs/DIIs).")
        elif inst_own > 0.15:
            parts.append(f"Solid institutional sponsorship ({inst_own*100:.1f}%).")
        else:
            parts.append(f"Low institutional coverage ({inst_own*100:.1f}%).")

    if prom_own is not None and prom_own > 0.50:
        parts.append(f"High promoter commitment with {prom_own*100:.1f}% insider stake.")

    return " ".join(parts)


def build_laya_state(stock: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms enriched technical and fundamental data into high-signal semantic statements
    tailored specifically for Laya's neural language model.
    """
    ticker = stock.get("ticker", "UNKNOWN")
    price = stock.get("price", 0.0)
    sigs = stock.get("signals", {})
    t1d = stock.get("tech_1d", {}) or {}
    t1w = stock.get("tech_1w", {}) or {}
    f = stock.get("fundamentals", {}) or {}

    trend_summary = translate_trend_structure(stock)
    momentum_summary = translate_momentum_and_flow(stock)
    valuation_summary = translate_valuation_and_quality(stock)
    growth_summary = translate_growth_and_ownership(stock)

    return {
        "ticker": ticker,
        "signals": f"1D: {sigs.get('1D', 'NEUTRAL')}, 1W: {sigs.get('1W', 'NEUTRAL')}",
        "double_confirmed": "YES" if stock.get("is_double_confirmed") else "NO",
        "trend_structure": trend_summary,
        "momentum_and_flow": momentum_summary,
        "valuation_and_quality": valuation_summary,
        "growth_and_ownership": growth_summary,
        "metrics": {
            "price": price,
            "change_pct": round(t1d.get("change") or 0.0, 2),
            "bullish_stack_1d": t1d.get("bullish_ema_stack", False),
            "bullish_stack_1w": t1w.get("bullish_ema_stack", False),
            "vwma_dist_pct": t1d.get("vwma_dist_pct"),
            "macd_hist_1d": t1d.get("macd_hist") or 0.0,
            "macd_hist_1w": t1w.get("macd_hist") or 0.0,
            "buyer_dominance": t1d.get("di_buyer_dominance"),
            "bb_power": t1d.get("BBPower"),
            "adx_1d": round(t1d.get("ADX") or 0.0, 1),
            "adx_1w": round(t1w.get("ADX") or 0.0, 1),
            "pe": f.get("trailingPE"),
            "fwd_pe": f.get("forwardPE"),
            "peg": f.get("pegRatio"),
            "debt": f.get("debtToEquity"),
            "roe": f.get("returnOnEquity"),
            "net_margin": f.get("profitMargins"),
            "op_margin": f.get("operatingMargins"),
            "rev_growth": f.get("revenueGrowth"),
            "eps_growth": f.get("earningsGrowth"),
            "inst_own": f.get("heldPercentInstitutions")
        }
    }


def calculate_laya_composite_score(stock: Dict[str, Any], answers: Dict[str, Any]) -> float:
    """
    Computes an institutional composite conviction score (0 - 100) based on Laya's neural predictions
    combined with high-signal technical and fundamental confluence bonuses.
    """
    choice_info = answers.get("setup_rating", {})
    choice = choice_info.get("choice", "neutral_mixed")
    probs = choice_info.get("probabilities", {})
    top_prob = probs.get("top_pick", 0.0)
    avoid_prob = probs.get("avoid", 0.0)

    noul_info = answers.get("is_high_conviction", {})
    conviction_noul = noul_info.get("noul", 0.5)

    score_info = answers.get("conviction_score", {})
    quality_score = score_info.get("score", 1.5)  # 0 to 3

    # Base neural weighting (60 pts):
    # - Conviction probability (noul): up to 25 pts
    # - Top-pick probability (penalized heavily by avoid probability): up to 25 pts
    # - Quality score (0-3): up to 10 pts
    neural_pts = (conviction_noul * 25.0)
    neural_pts += max(0.0, (top_prob - (avoid_prob * 1.2))) * 25.0
    neural_pts += (quality_score / 3.0) * 10.0

    # Strong neural penalty if Laya explicitly flags 'avoid' or 'neutral_mixed'
    if choice == "avoid":
        neural_pts *= 0.35
    elif choice == "neutral_mixed":
        neural_pts *= 0.80

    comp = neural_pts

    # Multi-timeframe Confluence & Fundamental Health Bonuses (up to 40 pts):
    t1d = stock.get("tech_1d", {}) or {}
    t1w = stock.get("tech_1w", {}) or {}
    f = stock.get("fundamentals", {}) or {}
    sigs = stock.get("signals", {})
    sig_1d = sigs.get("1D", "")
    sig_1w = sigs.get("1W", "")

    # Double confirmation bonus (+10 if BUY on both, -20 if SELL)
    if stock.get("is_double_confirmed"):
        if "BUY" in sig_1d:
            comp += 10.0
        elif "SELL" in sig_1d:
            comp -= 20.0

    # 1D Strong Buy bonus (+6)
    if "STRONG_BUY" in sig_1d:
        comp += 6.0
    elif "BUY" in sig_1d:
        comp += 3.0
    elif "SELL" in sig_1d:
        comp -= 15.0

    # Bullish multi-timeframe EMA alignment (+8)
    if t1d.get("bullish_ema_stack") and t1w.get("bullish_ema_stack"):
        comp += 8.0
    elif t1d.get("bullish_ema_stack"):
        comp += 4.0

    # Institutional buyer flow (+6): Price > VWMA & Buyer Dominance (+DI > -DI)
    vwma_dist = t1d.get("vwma_dist_pct") or 0.0
    if vwma_dist > 0 and t1d.get("di_buyer_dominance"):
        comp += 6.0
    elif vwma_dist < -5.0:
        comp -= 8.0

    # MACD momentum expansion bonus (+5)
    if (t1d.get("macd_hist") or 0) > 0 and (t1w.get("macd_hist") or 0) > 0:
        comp += 5.0
    elif (t1d.get("macd_hist") or 0) < 0 and (t1w.get("macd_hist") or 0) < 0:
        comp -= 6.0

    # Fundamental health bonus (+5): High ROE (>15%), Low Debt (<60), and High Margins
    roe = f.get("returnOnEquity")
    debt = f.get("debtToEquity")
    rev_growth = f.get("revenueGrowth")
    op_margin = f.get("operatingMargins")
    fund_bonus = 0.0
    if roe is not None and roe > 0.15:
        fund_bonus += 2.0
    if debt is not None and debt < 60:
        fund_bonus += 1.5
    elif debt is not None and debt > 150:
        comp -= 5.0
    if op_margin is not None and op_margin > 0.15:
        fund_bonus += 1.5
    elif op_margin is not None and op_margin < 0:
        comp -= 8.0
    comp += min(5.0, fund_bonus)

    return round(min(100.0, max(0.0, comp)), 1)


def prioritize_candidate_pool(stocks: List[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
    """Prioritizes candidates so Laya evaluates bullish double-confirmed and strong momentum stocks first."""
    if len(stocks) <= limit:
        return stocks

    def priority_score(s):
        score = 0
        sigs = s.get("signals", {})
        sig_1d = sigs.get("1D", "")
        sig_1w = sigs.get("1W", "")
        is_bullish_confirmed = s.get("is_double_confirmed") and "BUY" in sig_1d

        if is_bullish_confirmed:
            score += 100
        if "BUY" in sig_1d:
            score += 40
        if "STRONG_BUY" in sig_1d:
            score += 20
        if "BUY" in sig_1w:
            score += 30
        if "STRONG_BUY" in sig_1w:
            score += 15

        t1d = s.get("tech_1d", {}) or {}
        if t1d.get("bullish_ema_stack"):
            score += 25
        if t1d.get("di_buyer_dominance"):
            score += 15
        if (t1d.get("vwma_dist_pct") or 0) > 0:
            score += 15

        # Penalize sell signals for long swing candidate selection
        if "SELL" in sig_1d:
            score -= 100
        if "SELL" in sig_1w:
            score -= 50
        return score

    sorted_stocks = sorted(stocks, key=priority_score, reverse=True)
    return sorted_stocks[:limit]


def run_laya_screening(input_file: str, output_file: str, top_n: int = 25, candidate_limit: int = 50, batch_size: int = 16, device: str = "cpu") -> List[Dict[str, Any]]:
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)

    with open(input_file, "r") as f:
        all_stocks = json.load(f)

    if not all_stocks:
        print("Warning: Input stocks list is empty. Nothing to screen.")
        return []

    # Select prioritized candidate pool for Laya evaluation
    stocks = prioritize_candidate_pool(all_stocks, limit=candidate_limit)
    print(f"Selected top {len(stocks)} high-priority candidate stocks (from {len(all_stocks)} total scanned) for Laya neural evaluation.")

    print(f"--- Initializing Laya Decision Agent (System 1 Middle-Man on {device.upper()}) ---")
    t0 = time.time()
    agent = Agent(device=device)
    print(f"Laya Agent initialized in {round(time.time() - t0, 2)}s.")

    print(f"Formatting {len(stocks)} candidate stocks with 4-dimensional technical & fundamental state...")
    states = [build_laya_state(s) for s in stocks]

    print(f"Running Laya neural batch evaluation (batch_size={batch_size})...")
    t_eval = time.time()
    batch_results = agent.predict_batch(states, LAYA_QUESTIONS, batch_size=batch_size)
    print(f"Laya evaluated {len(stocks)} stocks in {round(time.time() - t_eval, 2)}s.")

    evaluated_stocks = []
    for stock, res in zip(stocks, batch_results):
        answers = res.get("answers", {})
        comp_score = calculate_laya_composite_score(stock, answers)

        choice = answers.get("setup_rating", {}).get("choice", "neutral_mixed")
        top_prob = answers.get("setup_rating", {}).get("probabilities", {}).get("top_pick", 0.0)
        noul_conv = answers.get("is_high_conviction", {}).get("noul", 0.5)
        quality_score = answers.get("conviction_score", {}).get("score", 1.5)

        stock_copy = dict(stock)
        stock_copy["laya_analysis"] = {
            "choice": choice,
            "top_pick_prob": round(top_prob, 3),
            "conviction": round(noul_conv, 3),
            "quality_score": round(quality_score, 2),
            "composite_score": comp_score
        }
        evaluated_stocks.append(stock_copy)

    # Sort candidates by Laya's composite score (highest first)
    evaluated_stocks.sort(key=lambda s: s["laya_analysis"]["composite_score"], reverse=True)

    # Assign ranks
    for rank, s in enumerate(evaluated_stocks, 1):
        s["laya_analysis"]["rank"] = rank

    # Shortlist top N
    shortlisted = evaluated_stocks[:top_n]

    # Save to output file
    with open(output_file, "w") as f:
        json.dump(shortlisted, f, indent=2)

    # Print summary table
    print("\n" + "=" * 95)
    print(f"LAYA MIDDLE-MAN PRE-SCREENING RESULTS (Top {len(shortlisted)} of {len(stocks)} Candidates)")
    print("=" * 95)
    header = f"{'#':<3} | {'TICKER':<10} | {'PRICE':<8} | {'1D':<11} | {'1W':<11} | {'CONF':<4} | {'VWMA':<6} | {'BUYER':<6} | {'LAYA DECISION':<14} | {'SCORE'}"
    print(header)
    print("-" * 95)
    for s in shortlisted:
        ticker = s["ticker"]
        price = s.get("price", 0)
        sig1d = s.get("signals", {}).get("1D", "N/A")
        sig1w = s.get("signals", {}).get("1W", "N/A")
        conf = "⚡" if s.get("is_double_confirmed") else " "
        t1d = s.get("tech_1d", {}) or {}
        vwma_flag = "✓" if (t1d.get("vwma_dist_pct") or 0) > 0 else "✗"
        buyer_flag = "✓" if t1d.get("di_buyer_dominance") else "✗"
        la = s["laya_analysis"]
        choice_str = la["choice"]
        score_val = la["composite_score"]
        print(f"{la['rank']:<3} | {ticker:<10} | {price:<8.2f} | {sig1d:<11} | {sig1w:<11} | {conf:<4} | {vwma_flag:<6} | {buyer_flag:<6} | {choice_str:<14} | {score_val:<5.1f}")

    print("=" * 95)
    print(f"Shortlist saved to '{output_file}'. Ready for Gemini deep reasoning.\n")
    return shortlisted


def main():
    parser = argparse.ArgumentParser(description="Laya Decision Engine Middle-Man for Stock Pre-Screening")
    parser.add_argument("--input", default="stock_data_for_ai.json", help="Path to input stock data JSON")
    parser.add_argument("--output", default="laya_screened_stocks.json", help="Path to save Laya shortlisted JSON")
    parser.add_argument("--candidates", type=int, default=50, help="Candidate pool size for Laya evaluation (default: 50)")
    parser.add_argument("--top", type=int, default=25, help="Number of top candidates to pass to Gemini (default: 25)")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size for Laya neural inference (default: 16)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "mps", "cuda"], help="Inference device (default: cpu)")

    args = parser.parse_args()
    run_laya_screening(
        input_file=args.input,
        output_file=args.output,
        top_n=args.top,
        candidate_limit=args.candidates,
        batch_size=args.batch_size,
        device=args.device
    )


if __name__ == "__main__":
    main()
