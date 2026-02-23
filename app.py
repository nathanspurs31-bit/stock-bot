import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz

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

mode = st.selectbox("Mode", ["Swing (daily)", "Day Trade (ORB)"])

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

    # ---------- DAY TRADE ORB MODE ----------
    else:
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
