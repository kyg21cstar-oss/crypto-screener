import streamlit as st
import pandas as pd
import pyupbit
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="비트코인/알트코인 실시간 스크리너")

@st.cache_data(ttl=60)
def get_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

@st.cache_data(ttl=60)
def run_crypto_screener(tickers):
    temp_results = []
    progress_text = "업비트(Upbit) 실시간 데이터 분석 중..."
    my_bar = st.progress(0, text=progress_text)
    
    for i, ticker in enumerate(tickers):
        try:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=30)
            if df is None or len(df) < 20: continue
            
            df['SMA_5'] = df['close'].rolling(window=5).mean()
            df['SMA_20'] = df['close'].rolling(window=20).mean()
            df['Vol_Avg_5'] = df['volume'].rolling(window=5).mean()
            df['Volume_Ratio'] = df['volume'] / df['Vol_Avg_5']
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            expected_sma5 = df['close'].tail(4).mean()
            
            is_volume = latest['Volume_Ratio'] > 1.5
            is_trend = latest['SMA_5'] > latest['SMA_20']
            is_cross = (prev['SMA_5'] <= prev['SMA_20']) and (latest['SMA_5'] > latest['SMA_20'])
            
            if is_trend and is_volume:
                matched = ["🌟 5일선 골든크로스" if is_cross else "이평선 정배열", "거래량 급증"]
                total_score = min(latest['Volume_Ratio'] * 20, 100) + (20 if is_cross else 0)
                
                temp_results.append({"코인명": ticker, "만족조건": ", ".join(matched), "현재가": latest['close'], "눌림목타점": expected_sma5, "볼륨비율": round(latest['Volume_Ratio'], 2), "종합점수": round(total_score, 1)})
        except: pass
        time.sleep(0.04)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by="종합점수", ascending=False).head(20).reset_index(drop=True)

def draw_crypto_chart(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=90)
    df['SMA_5'], df['SMA_20'] = df['close'].rolling(window=5).mean(), df['close'].rolling(window=20).mean()
    expected_sma5 = df['close'].tail(4).mean()
    
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='orange', width=2), name='5일선'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='green', width=2), name='20일선'))
    fig.add_trace(go.Scatter(x=[df.index[-1], df.index[-1] + timedelta(days=1)], y=[expected_sma5, expected_sma5], line=dict(color='purple', width=2, dash='dot'), name='예상 5일선 타점'))
    fig.update_layout(title=f"📈 {ticker} 실시간 차트", yaxis_title="가격 (KRW)", xaxis_rangeslider_visible=False, height=450, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    return fig

st.title("🪙 알트코인 폭등 포착 스크리너")
if st.button("실시간 분석 시작", type="primary"):
    st.session_state['run_crypto'] = True

if st.session_state.get('run_crypto', False):
    tickers = get_krw_tickers()
    if tickers:
        result_df = run_crypto_screener(tickers)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,.1f}", "눌림목타점": "{:,.1f}"}), use_container_width=True)
            selected_stock = st.selectbox("차트를 확인할 코인을 선택하세요:", result_df['코인명'].tolist())
            target_expected = result_df[result_df['코인명'] == selected_stock]['눌림목타점'].values[0]
            current_price = result_df[result_df['코인명'] == selected_stock]['현재가'].values[0]
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_crypto_chart(selected_stock), use_container_width=True)
            with col2: st.info(f"**현재가:** {current_price:,.1f} 원"); st.success(f"**매수 타점 (5일선):** {target_expected:,.1f} 원")
        else: st.warning("조건을 만족하는 코인이 없습니다.")