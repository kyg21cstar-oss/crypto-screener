import streamlit as st
import pandas as pd
import pyupbit
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

st.set_page_config(layout="wide", page_title="알트코인 세력 매집 포착 스크리너")

@st.cache_data(ttl=60)
def get_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

@st.cache_data(ttl=60)
def run_accumulation_screener(tickers):
    temp_results = []
    progress_text = "업비트 실시간 매집 데이터 및 지표 분석 중..."
    my_bar = st.progress(0, text=progress_text)
    
    for i, ticker in enumerate(tickers):
        try:
            # 볼린저 밴드와 OBV 계산을 위해 60일치 데이터 확보
            df = pyupbit.get_ohlcv(ticker, interval="day", count=60)
            if df is None or len(df) < 30: continue
            
            # 지표 1: 볼린저 밴드 (20일선 기준)
            df['SMA_20'] = df['close'].rolling(window=20).mean()
            df['STD_20'] = df['close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            # 지표 2: OBV (On-Balance Volume) - 누적 거래량
            delta = df['close'].diff()
            direction = delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
            df['OBV'] = (df['volume'] * direction).cumsum()
            
            # 지표 3: RSI (14일)
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=13, adjust=False).mean()
            ema_down = down.ewm(com=13, adjust=False).mean()
            rs = ema_up / ema_down
            df['RSI'] = 100 - (100 / (1 + rs))

            latest = df.iloc[-1]
            
            # 최근 10일 기준 지표 분석
            recent_10 = df.tail(10)
            price_trend = (recent_10['close'].iloc[-1] - recent_10['close'].iloc[0]) / recent_10['close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            
            # 조건 판단 로직
            is_bb_squeeze = latest['Band_Width'] < 0.12 # 밴드폭이 12% 이내로 극도로 좁아진 응축 상태
            is_obv_accum = price_trend <= 0.05 and obv_trend # 가격은 제자리/하락인데 OBV는 상승 (세력 매집)
            is_rsi_turn = 30 < latest['RSI'] < 55 # 바닥을 다지고 고개를 드는 상태
            
            matched = []
            score = 0
            
            if is_bb_squeeze: 
                matched.append("볼린저 밴드 밀집(응축)")
                score += 40
            if is_obv_accum: 
                matched.append("OBV 매집 다이버전스")
                score += 40
            if is_rsi_turn: 
                matched.append("RSI 바닥 반등")
                score += 20
            
            # 강한 윗꼬리 캔들 (매물대 소화 테스트) 
            upper_wick = (latest['high'] - max(latest['open'], latest['close'])) / (latest['high'] - latest['low'] + 0.0001)
            if upper_wick > 0.6 and latest['volume'] > df['volume'].rolling(5).mean().iloc[-1] * 2:
                matched.append("윗꼬리 매물대 테스트")
                score += 30

            # 매집 조건이 최소 1개 이상이고 밴드폭이 좁은 종목만 선별
            if score >= 40 and latest['Band_Width'] < 0.18:
                temp_results.append({
                    "코인명": ticker,
                    "만족조건": ", ".join(matched),
                    "현재가": latest['close'],
                    "밴드폭": round(latest['Band_Width'] * 100, 2),
                    "RSI": round(latest['RSI'], 1),
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
    
    # 1층: 캔들 차트 및 볼린저 밴드
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='gray', width=1, dash='dot'), name='BB 상단'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], line=dict(color='gray', width=1, dash='dot'), name='BB 하단', fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2), name='20일선'), row=1, col=1)
    
    # 2층: OBV (세력 매집 지표)
    fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='purple', width=2), name='OBV (누적 거래량)'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker} 매집 포착 정밀 차트 (볼린저밴드 & OBV)", yaxis_title="가격 (KRW)", yaxis2_title="OBV", xaxis_rangeslider_visible=False, height=600, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    return fig

st.title("🕵️‍♂️ 알트코인 폭풍전야 매집 포착 스크리너")
st.markdown("가격이 급등하기 전, **볼린저 밴드가 좁아진 상태에서 누군가 조용히 물량을 모으고 있는(OBV 상승)** 코인을 찾아냅니다.")

if st.button("매집 코인 실시간 탐지 시작", type="primary"):
    st.session_state['run_crypto'] = True

if st.session_state.get('run_crypto', False):
    tickers = get_krw_tickers()
    if tickers:
        result_df = run_accumulation_screener(tickers)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,.1f}", "밴드폭": "{:.1f}%"}), use_container_width=True)
            
            selected_stock = st.selectbox("정밀 차트 분석할 코인을 선택하세요:", result_df['코인명'].tolist())
            current_price = result_df[result_df['코인명'] == selected_stock]['현재가'].values[0]
            bb_width = result_df[result_df['코인명'] == selected_stock]['밴드폭'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_accumulation_chart(selected_stock), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,.1f} 원")
                st.warning(f"**현재 밴드폭:** {bb_width}%")
                st.markdown("""
                **💡 매집주 공략 시나리오**
                1. 밴드 하단선에서 분할 매수 진입
                2. 거래량이 터지며 밴드 상단을 강하게 돌파할 때 1차 익절
                3. 20일선 이탈 시 손절
                """)
        else: st.warning("현재 완벽한 매집 조건을 충족하는 코인이 없습니다. (시장 변동성이 클 때 주로 발생)")
