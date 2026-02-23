import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

st.set_page_config(page_title="Stock Signal Bot", page_icon="📈", layout="centered")

def rsi(series, period=14):
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
run = st.button("Analyze")

if run:
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

        # Safe chart display (prevents Streamlit crash if columns missing)
df_plot = result["df"].copy()

# Only use columns that exist
cols = []
for c in ["Close", "MA50", "MA200"]:
    if c in df_plot.columns:
        cols.append(c)

if len(cols) == 0:
    st.warning("No chart data available.")
else:
    st.line_chart(df_plot[cols].dropna())
