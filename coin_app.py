import streamlit as st
import pandas as pd
import pyupbit
import requests
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="알트코인 스윙 타점(눌림목) 스크리너")

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

@st.cache_data(ttl=60)
def run_swing_screener(tickers):
    temp_results = []
    progress_text = "스윙 눌림목 및 매집 데이터 스캔 중..."
    my_bar = st.progress(0, text=progress_text)
    binance_vols = get_binance_volumes()
    
    for i, ticker in enumerate(tickers):
        try:
            # 60일치 데이터를 불러와 분석 (속도 최적화)
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
            
            # [기존 로직] 매집 조건
            recent_10 = df.tail(10)
            price_trend = (recent_10['close'].iloc[-1] - recent_10['close'].iloc[0]) / recent_10['close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            is_bb_squeeze = latest['Band_Width'] < 0.15
            is_obv_accum = price_trend <= 0.05 and obv_trend
            
            # [신규 로직] 거래량 급감 스윙(눌림목) 조건
            recent_30 = df.tail(30)
            peak_high = recent_30['high'].max()
            peak_vol = recent_30['volume'].max()
            
            drop_rate = (latest['close'] - peak_high) / peak_high
            vol_dry_rate = latest['volume'] / peak_vol
            
            # 가격은 고점 대비 10~45% 하락, 거래량은 고점 대비 25% 이하, 20일선에서 크게 안 벗어난 지지 형태
            is_swing_dip = (-0.45 <= drop_rate <= -0.10) and (vol_dry_rate < 0.25) and (latest['close'] > latest['SMA_20'] * 0.90)
            
            score = 0
            matched = []
            
            if is_swing_dip: matched.append("⭐거래량급감(스윙)"); score += 40
            if is_bb_squeeze: matched.append("BB밀집"); score += 20
            if is_obv_accum: matched.append("OBV매집"); score += 20
            
            # 업비트 김치펌핑 쏠림 현상 확인
            base_ticker = ticker.split('-')[1]
            upbit_krw_vol = latest['value']
            binance_krw_vol = binance_vols.get(base_ticker, 0)
            dominance = upbit_krw_vol / (upbit_krw_vol + binance_krw_vol) if (upbit_krw_vol + binance_krw_vol) > 0 else 1.0
            dom_percent = int(dominance * 100)
            
            if score >= 20 and dom_percent >= 60:
                matched.append(f"업비트쏠림({dom_percent}%)")
                score += 20
            
            # 점수가 40점 이상(최소 스윙 타점이거나 매집 조건 충족)인 코인만 표출
            if score >= 40:
                temp_results.append({
                    "코인명": ticker,
                    "만족조건": ", ".join(matched),
                    "현재가": latest['close'],
                    "고점대비하락": f"{round(drop_rate*100, 1)}%",
                    "밴드폭": round(latest['Band_Width'] * 100, 2),
                    "종합점수": score
                })
        except: pass
        time.sleep(0.04)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수", "고점대비하락"], ascending=[False, True]).head(15).reset_index(drop=True)

def draw_chart(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=90)
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['STD_20'] = df['close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    
    # 상단 캔들 차트
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], line=dict(color='gray', width=1, dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2), name='20일선'), row=1, col=1)
    
    # 하단 거래량 차트 (직관적인 색상 적용)
    colors = ['red' if df['close'].iloc[i] > df['open'].iloc[i] else 'blue' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['volume'], marker_color=colors, name='거래량'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker} 정밀 스윙 타점 차트", yaxis_title="가격 (KRW)", yaxis2_title="거래량", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("🎯 코인 스윙 타점(눌림목) & 매집 스크리너")
st.markdown("급등 후 **가격은 크게 조정을 받았으나 거래량이 씨가 말라버린(세력 이탈 없음)** 완벽한 스윙 타점(눌림목)을 포착합니다.")

if st.button("스윙 & 매집 코인 탐지 시작", type="primary"):
    st.session_state['run_crypto'] = True

if st.session_state.get('run_crypto', False):
    tickers = get_krw_tickers()
    
    if tickers:
        result_df = run_swing_screener(tickers)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,.1f}", "밴드폭": "{:.1f}%"}), use_container_width=True)
            
            selected_stock = st.selectbox("정밀 차트(거래량 확인) 분석:", result_df['코인명'].tolist())
            current_price = result_df[result_df['코인명'] == selected_stock]['현재가'].values[0]
            drop = result_df[result_df['코인명'] == selected_stock]['고점대비하락'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: 
                st.plotly_chart(draw_chart(selected_stock), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,.1f} 원")
                st.error(f"**최근 고점 대비:** {drop}")
                st.markdown("""
                **💡 스윙(눌림목) 공략법**
                * 거래량이 터지며 상승한 뒤, **거래량 없이 하락**하는 것은 전형적인 개미털기 패턴입니다.
                * 하단 차트에서 파란색 거래량 막대가 바닥에 붙어있는지 확인하세요.
                * 20일선(주황색 선) 지지를 확인하고 분할 매수하는 것이 가장 안전합니다.
                """)
        else: st.warning("현재 완벽한 스윙(눌림목) 조건을 충족하는 코인이 없습니다.")
