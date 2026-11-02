import streamlit as st
import pandas as pd
import pyupbit
import requests
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="알트코인 스윙 타점(기준봉 시초가) 스크리너")

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
    progress_text = "기준봉 시초가 눌림목 및 업비트 쏠림 스캔 중..."
    my_bar = st.progress(0, text=progress_text)
    binance_vols = get_binance_volumes()
    
    for i, ticker in enumerate(tickers):
        try:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=60)
            if df is None or len(df) < 30: continue
            
            recent_30 = df.tail(30)
            latest = df.iloc[-1]
            
            peak_value = recent_30['value'].max() 
            
            # [핵심 로직] 기준봉(대량 거래일) 시초가 지지 확인
            peak_vol_idx = recent_30['volume'].idxmax()
            peak_candle = df.loc[peak_vol_idx]
            
            # 기준봉 양봉 여부 확인 (시가 대비 5% 이상 상승)
            is_valid_peak = peak_candle['close'] > (peak_candle['open'] * 1.05)
            
            peak_open = peak_candle['open']
            # 현재가가 기준봉 시초가 부근(-8% ~ +20%)에서 지지 중인지
            is_price_retraced = (peak_open * 0.92 <= latest['close'] <= peak_open * 1.20)
            
            # 거래량 극감: 기준봉 거래량 대비 35% 이하
            vol_dry_rate = latest['volume'] / peak_candle['volume'] if peak_candle['volume'] > 0 else 1
            is_vol_dried = vol_dry_rate < 0.35
            
            is_swing_dip = is_valid_peak and is_price_retraced and is_vol_dried
            
            df['SMA_20'] = df['close'].rolling(window=20).mean()
            df['STD_20'] = df['close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            delta = df['close'].diff()
            df['OBV'] = (df['volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
            
            recent_10 = df.tail(10)
            price_trend = (recent_10['close'].iloc[-1] - recent_10['close'].iloc[0]) / recent_10['close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            
            is_bb_squeeze = latest['Band_Width'] < 0.25 
            is_obv_accum = price_trend <= 0.10 and obv_trend 
            
            score = 0
            matched = []
            
            if is_swing_dip: matched.append("⭐기준봉시초가(눌림)"); score += 40
            if is_bb_squeeze: matched.append("BB밀집"); score += 20
            if is_obv_accum: matched.append("OBV매집"); score += 20
            
            if peak_value >= 30000000000: 
                matched.append("🔥300억(세력개입)"); score += 20
                
            base_ticker = ticker.split('-')[1]
            upbit_krw_vol = latest['value']
            binance_krw_vol = binance_vols.get(base_ticker, 0)
            dominance = upbit_krw_vol / (upbit_krw_vol + binance_krw_vol) if (upbit_krw_vol + binance_krw_vol) > 0 else 1.0
            dom_percent = int(dominance * 100)
            
            if score >= 20 and dom_percent >= 60:
                matched.append(f"업비트쏠림({dom_percent}%)")
                score += 10
            
            # 기술적 패턴(스윙, BB, OBV) 중 최소 1개 이상 만족하면서 30점 이상인 코인 표출
            has_technical_pattern = is_swing_dip or is_bb_squeeze or is_obv_accum
            if score >= 30 and has_technical_pattern:
                temp_results.append({
                    "코인명": ticker,
                    "만족조건": ", ".join(matched),
                    "현재가": latest['close'],
                    "기준봉시초가": int(peak_open),
                    "최대대금(30일)": f"{int(peak_value / 100000000)}억",
                    "종합점수": score
                })
        except: pass
        time.sleep(0.15)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수"], ascending=[False]).head(15).reset_index(drop=True)

def draw_chart(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=90)
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['STD_20'] = df['close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    
    # 기준봉 시초가 방어선(가로선) 추가
    recent_30 = df.tail(30)
    peak_vol_idx = recent_30['volume'].idxmax()
    peak_open = df.loc[peak_vol_idx, 'open']
    fig.add_hline(y=peak_open, line_dash="dot", line_color="green", annotation_text="기준봉 시초가 (세력 방어선)", annotation_position="bottom right")
    
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2), name='20일선'), row=1, col=1)
    
    colors = ['red' if df['close'].iloc[i] > df['open'].iloc[i] else 'blue' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['volume'], marker_color=colors, name='거래량'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker} 기준봉 시초가 눌림목 차트", yaxis_title="가격 (KRW)", yaxis2_title="거래량", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("🎯 코인 스윙 타점(기준봉 시초가) & 매집 스크리너")
st.markdown("**과거 대량 거래량으로 펌핑되었던 장대양봉(기준봉)의 시초가 부근까지, 거래량 없이 조정을 받고 지지 중인 완벽한 눌림목**을 추적합니다.")

if st.button("스윙 & 매집 코인 탐지 시작", type="primary"):
    st.session_state['run_crypto'] = True

if st.session_state.get('run_crypto', False):
    tickers = get_krw_tickers()
    if tickers:
        result_df = run_swing_screener(tickers)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,.1f}", "기준봉시초가": "{:,.1f}"}), use_container_width=True)
            
            selected_stock = st.selectbox("정밀 차트 분석 (초록색 방어선 확인):", result_df['코인명'].tolist())
            current_price = result_df[result_df['코인명'] == selected_stock]['현재가'].values[0]
            peak_open = result_df[result_df['코인명'] == selected_stock]['기준봉시초가'].values[0]
            peak_val = result_df[result_df['코인명'] == selected_stock]['최대대금(30일)'].values[0]
            matched_conds = result_df[result_df['코인명'] == selected_stock]['만족조건'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_chart(selected_stock), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,.1f} 원")
                st.warning(f"**기준봉 시초가:** {peak_open:,.1f} 원")
                st.success(f"**달성조건:** {matched_conds}")
                st.error(f"**최대 펌핑 대금:** {peak_val}")
                st.markdown("""
                **💡 코인 기준봉 타점 팁**
                * 차트의 **초록색 점선**이 세력이 펌핑을 시작했던 시초가(방어선)입니다.
                * 현재 가격이 이 선에 거의 닿았는데 하단의 **거래량 막대가 바닥에 붙어있다면(이탈 없음)** 최고의 반등 타점입니다.
                """)
        else: st.warning("현재 최소 기준 점수(30점)를 만족하는 기술적 스윙 타점 코인이 없습니다.")
