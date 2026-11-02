import streamlit as st
import pandas as pd
import pyupbit
import requests
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="알트코인 스윙 & 매집 통합 스크리너 (와이드망)")

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
    progress_text = "유연한 와이드망(조건 완화)으로 시장 스캔 중..."
    my_bar = st.progress(0, text=progress_text)
    binance_vols = get_binance_volumes()
    
    for i, ticker in enumerate(tickers):
        try:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=60)
            if df is None or len(df) < 30: continue
            
            recent_30 = df.tail(30)
            latest = df.iloc[-1]
            
            peak_value = recent_30['value'].max() 
            
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
            
            peak_high = recent_30['high'].max()
            peak_vol = recent_30['volume'].max()
            
            drop_rate = (latest['close'] - peak_high) / peak_high if peak_high > 0 else 0
            vol_dry_rate = latest['volume'] / peak_vol if peak_vol > 0 else 1
            
            is_swing_dip = (-0.50 <= drop_rate <= -0.08) and (vol_dry_rate < 0.40) and (latest['close'] > latest['SMA_20'] * 0.85)
            
            score = 0
            matched = []
            
            if is_swing_dip: matched.append("⭐거래량급감(스윙)"); score += 30
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
            
            has_technical_pattern = is_swing_dip or is_bb_squeeze or is_obv_accum
            if score >= 20 and has_technical_pattern:
                temp_results.append({
                    "코인명": ticker,
                    "만족조건": ", ".join(matched),
                    "현재가": latest['close'],
                    "최대대금(30일)": f"{int(peak_value / 100000000)}억",
                    "고점대비하락": f"{round(drop_rate*100, 1)}%",
                    "종합점수": score
                })
        except: pass
        
        # [핵심 수정] 업비트 API 차단을 막기 위해 0.04초 -> 0.15초로 딜레이 증가
        time.sleep(0.15)
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
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], line=dict(color='gray', width=1, dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2), name='20일선'), row=1, col=1)
    
    colors = ['red' if df['close'].iloc[i] > df['open'].iloc[i] else 'blue' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['volume'], marker_color=colors, name='거래량'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker} 정밀 타점 차트", yaxis_title="가격 (KRW)", yaxis2_title="거래량", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("🎯 코인 스윙 타점 & 매집 통합 스크리너 (와이드망)")
st.markdown("코인 시장의 높은 변동성을 감안하여 필터링 조건을 완화했습니다. **최소 1개 이상의 기술적 패턴이 포착된 유망 코인**들을 넓게 스캔하여 보여줍니다.")

if st.button("스윙 & 매집 코인 탐지 시작", type="primary"):
    st.session_state['run_crypto'] = True

if st.session_state.get('run_crypto', False):
    tickers = get_krw_tickers()
    if tickers:
        result_df = run_swing_screener(tickers)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,.1f}"}), use_container_width=True)
            
            selected_stock = st.selectbox("정밀 차트 분석 (거래량 확인):", result_df['코인명'].tolist())
            current_price = result_df[result_df['코인명'] == selected_stock]['현재가'].values[0]
            drop = result_df[result_df['코인명'] == selected_stock]['고점대비하락'].values[0]
            peak = result_df[result_df['코인명'] == selected_stock]['최대대금(30일)'].values[0]
            matched_conds = result_df[result_df['코인명'] == selected_stock]['만족조건'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_chart(selected_stock), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,.1f} 원")
                st.success(f"**달성조건:** {matched_conds}")
                st.error(f"**최근 고점 대비:** {drop}")
                st.warning(f"**최대 펌핑 대금:** {peak}")
        else: st.warning("완화된 기준(20점)으로도 현재 기술적 스윙 타점에 들어온 코인이 없습니다. (전체 하락장 유력)")
