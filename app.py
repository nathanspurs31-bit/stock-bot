import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz
import time as pytime

st.set_page_config(page_title="Stock Signal Bot", page_icon="📈", layout="centered")

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def vwap(df):
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()

def get_intraday(ticker: str, interval="1m", period="5d"):
    df = yf.download(ticker, interval=interval, period=period, auto_adjust=True, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df

def orb_signal(ticker: str, orb_minutes=5):
    df = get_intraday(ticker, interval="1m", period="5d")
    if df.empty or len(df) < 30:
        return {"error": "Not enough intraday data."}

    eastern = pytz.timezone("US/Eastern")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(eastern)
    else:
        df.index = df.index.tz_convert(eastern)

    today = df.index[-1].date()
    session = df[df.index.date == today]
    session = session.between_time("09:30", "16:00")

    if session.empty:
        return {"error": "No market session data yet."}

    start = time(9, 30)
    end = time(9, 35)
    opening = session.between_time(start.strftime("%H:%M"), end.strftime("%H:%M"))

    or_high = float(opening["High"].max())
    or_low = float(opening["Low"].min())

    last_price = float(session["Close"].iloc[-1])

    signal = "WAIT"
    if last_price > or_high:
        signal = "LONG ORB"
    elif last_price < or_low:
        signal = "SHORT ORB"

    return {
        "ticker": ticker.upper(),
        "last_price": round(last_price, 2),
        "or_high": round(or_high, 2),
        "or_low": round(or_low, 2),
        "signal": signal,
        "chart": session[["Close"]]
    }
def hybrid_scalper_signal(df: pd.DataFrame):
    """
    df: intraday dataframe (1m or 5m) with columns: Open, High, Low, Close, Volume
    Returns: decision + scores for scalping/intraday
    """
    if df is None or df.empty or len(df) < 30:
        return {"decision": "AVOID", "reason": "Not enough intraday data.", "momentum": 0, "vol": 0, "vwap_ok": False}

    d = df.copy()

    # VWAP
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    d["VWAP"] = (tp * d["Volume"]).cumsum() / d["Volume"].cumsum()

    # Momentum score (simple + beginner-safe)
    # We look at last 3 candles: higher closes = bullish momentum
    last = d["Close"].iloc[-1]
    c1 = d["Close"].iloc[-2]
    c2 = d["Close"].iloc[-3]
    momentum = 0
    if last > c1: momentum += 1
    if c1 > c2: momentum += 1

    # Volume spike: last candle volume vs rolling average
    vol_ma = d["Volume"].rolling(20).mean().iloc[-1]
    last_vol = d["Volume"].iloc[-1]
    vol_spike = 0
    if pd.notna(vol_ma) and vol_ma > 0:
        vol_spike = 1 if last_vol > vol_ma * 1.5 else 0

    # VWAP condition
    vwap_ok = last >= d["VWAP"].iloc[-1]

    # “Late/chasing” filter: if price is extended above recent range, avoid
    recent_high = d["High"].rolling(20).max().iloc[-1]
    recent_low = d["Low"].rolling(20).min().iloc[-1]
    rng = (recent_high - recent_low) if pd.notna(recent_high) and pd.notna(recent_low) else 0
    extended = False
    if rng and rng > 0:
        extended = (last - recent_low) / rng > 0.90  # top 10% of recent range

    # Decision logic (Hybrid)
    # ENTER = momentum + volume spike + above VWAP + not extended
    if momentum == 2 and vol_spike == 1 and vwap_ok and not extended:
        return {
            "decision": "ENTER",
            "reason": "Momentum up + volume spike + above VWAP (not extended).",
            "momentum": momentum,
            "vol": vol_spike,
            "vwap_ok": vwap_ok
        }

    # WATCH = some pieces are forming
    if (momentum >= 1 and vwap_ok) or (vol_spike == 1 and vwap_ok):
        return {
            "decision": "WATCH",
            "reason": "Setup forming (needs confirmation).",
            "momentum": momentum,
            "vol": vol_spike,
            "vwap_ok": vwap_ok
        }

    return {
        "decision": "AVOID",
        "reason": "No clean momentum setup right now.",
        "momentum": momentum,
        "vol": vol_spike,
        "vwap_ok": vwap_ok
    }


@st.cache_data(ttl=60)
def fetch_intraday_5m(ticker: str):
    # 5m candles, last ~5 days
    df = yf.download(ticker, interval="5m", period="5d", auto_adjust=True, progress=False)

    if df.empty:
        return df

    # Flatten MultiIndex if it appears
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    return df


def scan_universe(tickers, top_n=25):
    rows = []
    for t in tickers:
        t = t.strip().upper()
        if not t:
            continue

        try:
            df = fetch_intraday_5m(t)
            if df is None or df.empty:
                continue

            # % move today (rough): last close vs first close of today in the 5m data
            # If today isn't present yet, it still works but will be less meaningful.
            last_close = float(df["Close"].iloc[-1])

            # Try to isolate today's rows by date
            dates = pd.to_datetime(df.index).date
            today = dates[-1]
            df_today = df[dates == today]
            if len(df_today) >= 2:
                first_close = float(df_today["Close"].iloc[0])
            else:
                first_close = float(df["Close"].iloc[max(0, len(df)-50)])  # fallback

            pct_move = ((last_close - first_close) / first_close) * 100 if first_close else 0

            sig = hybrid_scalper_signal(df)

            rows.append({
                "Ticker": t,
                "% Move": round(pct_move, 2),
                "Decision": sig["decision"],
                "Momentum(0-2)": sig["momentum"],
                "VolSpike(0/1)": sig["vol"],
                "AboveVWAP": "YES" if sig["vwap_ok"] else "NO",
                "Why": sig["reason"],
                "Last": round(last_close, 2)
            })

            # tiny pause to reduce rate-limit risk
            pytime.sleep(0.05)

        except Exception:
            continue

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # Sort by biggest movers first, then better decisions
    decision_rank = {"ENTER": 0, "WATCH": 1, "AVOID": 2}
    out["Rank"] = out["Decision"].map(decision_rank).fillna(9)
    out = out.sort_values(by=["Rank", "% Move"], ascending=[True, False])
    out = out.drop(columns=["Rank"])
    return out.head(top_n)
    
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze_stock(ticker: str, period="2y"):
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    
def analyze_stock(ticker: str, period="2y"):
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    if df.empty or len(df) < 250:
        return {"ticker": ticker, "error": "Not enough data to analyze."}

    close = df["Close"]
    df["MA50"] = close.rolling(50).mean()
    df["MA200"] = close.rolling(200).mean()
    df["RSI14"] = rsi(close, 14)

    latest = df.iloc[-1]
    price = float(latest["Close"])
    ma50 = float(latest["MA50"])
    ma200 = float(latest["MA200"])
    rsi14 = float(latest["RSI14"])

    score = 50
    reasons = []

    if price > ma200:
        score += 15
        reasons.append("Above 200-day trend")
    else:
        score -= 15
        reasons.append("Below 200-day trend")

    if ma50 > ma200:
        score += 10
        reasons.append("Bullish MA structure")
    else:
        score -= 10
        reasons.append("Bearish MA structure")

    if rsi14 < 35:
        score += 10
        reasons.append("Oversold RSI")
    elif rsi14 > 70:
        score -= 10
        reasons.append("Overbought RSI")

    score = int(np.clip(score, 0, 100))

    if score >= 65:
        decision = "GOOD BUY"
        badge = "✅"
    elif score <= 35:
        decision = "BAD BUY"
        badge = "⛔"
    else:
        decision = "WAIT"
        badge = "🟡"

    return {
        "ticker": ticker.upper(),
        "price": round(price, 2),
        "score": score,
        "decision": decision,
        "badge": badge,
        "reasons": reasons,
        "df": df
    }

st.title("📈 Stock Signal Bot")

ticker = st.text_input("Enter ticker", "AAPL")

mode = st.selectbox("Mode", ["Swing (daily)", "Day Trade (ORB)", "Scanner (Top 25) — Hybrid Scalper (5m)"])
@st.cache_data(ttl=60)
def fetch_intraday_5m(ticker: str):
    df = yf.download(ticker, interval="5m", period="5d", auto_adjust=True, progress=False)

    if df is None or df.empty:
        return df

    # flatten MultiIndex if Yahoo returns it
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    return df


def hybrid_scalper_signal(df: pd.DataFrame):
    """
    df: intraday dataframe (5m) with columns Open/High/Low/Close/Volume
    returns: dict with ENTER/WATCH/AVOID + why
    """
    if df is None or df.empty or len(df) < 30:
        return {"decision": "AVOID", "why": "Not enough intraday data.", "mom": 0, "vol": 0, "vwap": False}

    d = df.copy()

    # VWAP
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    d["VWAP"] = (tp * d["Volume"]).cumsum() / d["Volume"].cumsum()

    last = float(d["Close"].iloc[-1])
    prev1 = float(d["Close"].iloc[-2])
    prev2 = float(d["Close"].iloc[-3])

    # Momentum (0-2)
    mom = 0
    if last > prev1: mom += 1
    if prev1 > prev2: mom += 1

    # Volume spike (0/1)
    vol_ma = d["Volume"].rolling(20).mean().iloc[-1]
    last_vol = d["Volume"].iloc[-1]
    vol_spike = 0
    if pd.notna(vol_ma) and vol_ma > 0:
        vol_spike = 1 if last_vol > vol_ma * 1.5 else 0

    # Above VWAP
    vwap_ok = last >= float(d["VWAP"].iloc[-1])

    # Late / chasing filter (extended)
    recent_high = d["High"].rolling(20).max().iloc[-1]
    recent_low = d["Low"].rolling(20).min().iloc[-1]
    rng = float(recent_high - recent_low) if pd.notna(recent_high) and pd.notna(recent_low) else 0.0
    extended = False
    if rng > 0:
        extended = ((last - float(recent_low)) / rng) > 0.90

    # Decision
        if mom == 2 and vol_spike == 1 and vwap_ok and not extended:
            return {
            "decision": "BUY NOW",
            "why": "Momentum + volume spike + above VWAP breakout.",
            "mom": mom,
            "vol": vol_spike,
            "vwap": vwap_ok
    }
    if (mom >= 1 and vwap_ok) or (vol_spike == 1 and vwap_ok):
        return {"decision": "WATCH", "why": "Setup forming (needs confirmation).", "mom": mom, "vol": vol_spike, "vwap": vwap_ok}

    return {"decision": "AVOID", "why": "No clean setup right now.", "mom": mom, "vol": vol_spike, "vwap": vwap_ok}


def scan_universe(tickers, top_n=25):
    rows = []

    for t in tickers:
        t = t.strip().upper()
        if not t:
            continue

        try:
            df = fetch_intraday_5m(t)
            if df is None or df.empty:
                continue

            last_close = float(df["Close"].iloc[-1])

            # % move "today" in the 5m feed
            idx_dates = pd.to_datetime(df.index).date
            today = idx_dates[-1]
            df_today = df[idx_dates == today]

            if len(df_today) >= 2:
                first_close = float(df_today["Close"].iloc[0])
            else:
                first_close = float(df["Close"].iloc[max(0, len(df) - 50)])

            pct_move = ((last_close - first_close) / first_close) * 100 if first_close else 0.0

            sig = hybrid_scalper_signal(df)

            rows.append({
                "Ticker": t,
                "% Move": round(pct_move, 2),
                "Decision": sig["decision"],
                "Momentum(0-2)": sig["mom"],
                "VolSpike(0/1)": sig["vol"],
                "AboveVWAP": "YES" if sig["vwap"] else "NO",
                "Last": round(last_close, 2),
                "Why": sig["why"],
            })

            pytime.sleep(0.05)  # helps avoid rate-limits

        except Exception:
            continue

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # Sort ENTER first, then WATCH, then AVOID. Within each, biggest movers first.
    rank = {"BUY NOW": 0, "WATCH": 1, "AVOID": 2}
    out["__rank"] = out["Decision"].map(rank).fillna(9)
    out = out.sort_values(["__rank", "% Move"], ascending=[True, False]).drop(columns="__rank")

    return out.head(top_n)
universe_text = ""
if mode == "Scanner (Top 25) — Hybrid Scalper (5m)":
    universe_text = st.text_area(
        "Paste tickers to scan (one per line). Example: TSLA, NVDA, AMD, AAPL...",
        height=200
    )
run = st.button("Analyze")

if run:

    # ---------- SWING MODE ----------
    if mode == "Swing (daily)":
        result = analyze_stock(ticker)

        if "error" in result:
            st.error(result["error"])
        else:
            st.subheader(f"{result['badge']} {result['ticker']} — {result['decision']}")
            st.metric("Score", result["score"])
            st.metric("Price", f"${result['price']}")

            st.write("Why:")
            for r in result["reasons"]:
                st.write(f"- {r}")

            df_plot = result["df"].copy()

            cols = []
            for c in ["Close", "MA50", "MA200"]:
                if c in df_plot.columns:
                    cols.append(c)

            if len(cols) == 0:
                st.warning("No chart data available.")
            else:
                st.line_chart(df_plot[cols].dropna())
    elif mode == "Day Trade (ORB)":
        orb = orb_signal(ticker)

        if "error" in orb:
            st.error(orb["error"])
        else:
            st.subheader(f"{orb['ticker']} — {orb['signal']}")
            st.metric("Last Price", f"${orb['last_price']}")
            c1, c2 = st.columns(2)
            c1.metric("OR High", f"${orb['or_high']}")
            c2.metric("OR Low", f"${orb['or_low']}")
            st.line_chart(orb["chart"])

    elif mode == "Scanner (Top 25) — Hybrid Scalper (5m)":
        tickers = [x.strip() for x in universe_text.replace(",", "\n").splitlines() if x.strip()]

        if len(tickers) < 5:
            st.warning("Paste at least 5 tickers to scan.")
        else:
            with st.spinner(f"Scanning {len(tickers)} tickers..."):
                table = scan_universe(tickers, top_n=25)

            if table.empty:
                st.error("No data returned. Try different tickers or try again during market hours.")
            else:
                st.subheader("Top 25 — Hybrid Scalper Signals (5m)")
                st.dataframe(table, use_container_width=True)
