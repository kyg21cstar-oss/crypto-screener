import streamlit as st
import pandas as pd
import pyupbit
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="알트코인 매집 & 뉴스 크롤링 스크리너")

@st.cache_data(ttl=3600)
def get_ticker_names():
    try:
        res = requests.get("https://api.upbit.com/v1/market/all").json()
        return {item['market']: item['korean_name'] for item in res if item['market'].startswith('KRW-')}
    except: return {}

@st.cache_data(ttl=60)
def get_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

@st.cache_data(ttl=300)
def get_binance_volumes():
    b_vols = {}
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=3)
        for item in res.json():
            if item['symbol'].endswith('USDT'):
                b_vols[item['symbol'][:-4]] = float(item['quoteVolume']) * 1400 
    except: pass
    return b_vols

@st.cache_data(ttl=600)
def get_naver_news(keyword):
    url = f"https://search.naver.com/search.naver?where=news&query={keyword} 코인"
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_list = []
    try:
        res = requests.get(url, headers=headers, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        articles = soup.find_all('a', {'class': 'news_tit'})[:5]
        for a in articles:
            news_list.append({"title": a.text, "link": a['href']})
    except: pass
    return news_list

@st.cache_data(ttl=60)
def run_accumulation_screener(tickers):
    temp_results = []
    progress_text = "업비트 거래량 및 매집 데이터 분석 중..."
    my_bar = st.progress(0, text=progress_text)
    binance_vols = get_binance_volumes()
    
    for i, ticker in enumerate(tickers):
        try:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=60)
            if df is None or len(df) < 30: continue
            
            df['SMA_20'] = df['close'].rolling(window=20).mean()
            df['STD_20'] = df['close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            delta = df['close'].diff()
            df['OBV'] = (df['volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
            
            latest = df.iloc[-1]
            recent_10 = df.tail(10)
            price_trend = (recent_10['close'].iloc[-1] - recent_10['close'].iloc[0]) / recent_10['close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            
            is_bb_squeeze = latest['Band_Width'] < 0.15
            is_obv_accum = price_trend <= 0.05 and obv_trend
            
            score = 0
            matched = []
            
            if is_bb_squeeze: matched.append("BB밀집"); score += 30
            if is_obv_accum: matched.append("OBV매집"); score += 30
            
            base_ticker = ticker.split('-')[1]
            upbit_krw_vol = latest['value']
            binance_krw_vol = binance_vols.get(base_ticker, 0)
            
            dominance = upbit_krw_vol / (upbit_krw_vol + binance_krw_vol) if (upbit_krw_vol + binance_krw_vol) > 0 else 1.0
            dom_percent = int(dominance * 100)
            
            if score >= 30 and dom_percent >= 60:
                matched.append(f"업비트 쏠림({dom_percent}%)")
                score += 40
            
            if score >= 30 and latest['Band_Width'] < 0.20:
                temp_results.append({
                    "코인명": ticker,
                    "만족조건": ", ".join(matched),
                    "현재가": latest['close'],
                    "업비트점유율": f"{dom_percent}%",
                    "밴드폭": round(latest['Band_Width'] * 100, 2),
                    "종합점수": score
                })
        except: pass
        time.sleep(0.04)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수", "밴드폭"], ascending=[False, True]).head(15).reset_index(drop=True)

def draw_accumulation_chart(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=90)
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['STD_20'] = df['close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
    delta = df['close'].diff()
    df['OBV'] = (df['volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], line=dict(color='gray', width=1, dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='purple', width=2), name='OBV'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker} 세력 매집 차트", yaxis_title="가격 (KRW)", yaxis2_title="OBV", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("🐋 알트코인 매집 & 호재 탐지 스크리너")
st.markdown("차트 횡보 및 거래량 쏠림이 포착된 코인을 선별하고, **선택한 코인의 최신 네이버 뉴스 호재**를 실시간으로 교차 검증합니다.")

if st.button("실시간 스크리닝 및 뉴스 탐지 시작", type="primary"):
    st.session_state['run_crypto'] = True

if st.session_state.get('run_crypto', False):
    tickers = get_krw_tickers()
    ticker_names = get_ticker_names()
    
    if tickers:
        result_df = run_accumulation_screener(tickers)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,.1f}", "밴드폭": "{:.1f}%"}), use_container_width=True)
            
            selected_stock = st.selectbox("차트 및 뉴스 분석할 코인을 선택하세요:", result_df['코인명'].tolist())
            current_price = result_df[result_df['코인명'] == selected_stock]['현재가'].values[0]
            dom = result_df[result_df['코인명'] == selected_stock]['업비트점유율'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: 
                st.plotly_chart(draw_accumulation_chart(selected_stock), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,.1f} 원")
                st.error(f"**업비트 점유율:** {dom}")
                
                st.markdown("### 📰 최신 네이버 뉴스")
                kor_name = ticker_names.get(selected_stock, selected_stock.split('-')[1])
                news_data = get_naver_news(kor_name)
                
                if news_data:
                    for idx, n in enumerate(news_data):
                        st.markdown(f"**{idx+1}.** [{n['title']}]({n['link']})")
                else:
                    st.write("관련 최신 뉴스가 없습니다.")
        else: st.warning("현재 완벽한 매집 조건을 충족하는 코인이 없습니다.")
