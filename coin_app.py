import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="국내주식 스윙 타점(기준봉 중심선) 스크리너")

@st.cache_data(ttl=300)
def get_market_universe():
    try:
        df = fdr.StockListing('KRX')
        return df.sort_values(by="Marcap", ascending=False).head(300)
    except:
        return pd.DataFrame()

def get_naver_supply(ticker):
    url = f"https://finance.naver.com/item/frgn.naver?code={ticker}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=2)
        soup = BeautifulSoup(res.text, 'html.parser')
        trs = soup.find('table', {'class': 'type2'}).find_all('tr')
        for tr in trs:
            tds = tr.find_all('td')
            if len(tds) >= 9:
                f_val = int(tds[6].text.strip().replace(',', '')) if tds[6].text.strip().replace(',', '').lstrip('-').isdigit() else 0
                i_val = int(tds[7].text.strip().replace(',', '')) if tds[7].text.strip().replace(',', '').lstrip('-').isdigit() else 0
                return f_val, i_val
    except: pass
    return 0, 0

@st.cache_data(ttl=300)
def run_stock_swing_screener(universe_df):
    temp_results = []
    progress_text = "기준봉 중심선(절반) 눌림목 및 수급 스캔 중..."
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    tickers, names, markets = universe_df['Code'].tolist(), universe_df['Name'].tolist(), universe_df['Market'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 20: continue
            
            # [핵심 로직 수정] 최근 2주(14일) 내 10% 이상 장대양봉 중심선 지지
            recent_14 = df.tail(14)
            latest = df.iloc[-1]
            
            peak_vol_idx = recent_14['Volume'].idxmax()
            peak_candle = df.loc[peak_vol_idx]
            
            # 1. 10% 이상 장대양봉 조건
            is_valid_peak = peak_candle['Close'] >= (peak_candle['Open'] * 1.10)
            
            # 2. 중심선(절반) 가격 계산
            peak_open = peak_candle['Open']
            peak_close = peak_candle['Close']
            mid_price = (peak_open + peak_close) / 2
            
            # 3. 현재가가 시초가와 중심선(절반) 부근 사이에서 지지받고 있는지
            is_price_retraced = (peak_open * 0.95 <= latest['Close'] <= mid_price * 1.05)
            
            # 4. 거래량 극감: 장대양봉 당일 거래량 대비 30% 이하
            vol_dry_rate = latest['Volume'] / peak_candle['Volume'] if peak_candle['Volume'] > 0 else 1
            is_vol_dried = vol_dry_rate < 0.30
            
            is_swing_dip = is_valid_peak and is_price_retraced and is_vol_dried
            
            # 보조 지표
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['STD_20'] = df['Close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            delta = df['Close'].diff()
            df['OBV'] = (df['Volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
            
            recent_10 = df.tail(10)
            price_trend = (recent_10['Close'].iloc[-1] - recent_10['Close'].iloc[0]) / recent_10['Close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            
            is_bb_squeeze = latest['Band_Width'] < 0.18
            is_obv_accum = price_trend <= 0.05 and obv_trend
            
            score = 0
            matched = []
            
            if is_swing_dip: matched.append("⭐장대양봉 중심선"); score += 40
            if is_bb_squeeze: matched.append("BB밀집"); score += 20
            if is_obv_accum: matched.append("OBV매집"); score += 20
            
            if score >= 20:
                f_net, i_net = get_naver_supply(ticker)
                if f_net > 0: matched.append("외인(매수)"); score += 15
                if i_net > 0: matched.append("기관(매수)"); score += 15
            
            # 기술적 타점(중심선, BB, OBV) 중 1개 이상 획득 시 표출
            has_technical = is_swing_dip or is_bb_squeeze or is_obv_accum
            if score >= 30 and has_technical:
                temp_results.append({
                    "종목코드": ticker,
                    "종목명": names[i],
                    "시장": markets[i],
                    "만족조건": ", ".join(matched),
                    "현재가": int(latest['Close']),
                    "중심선가격": int(mid_price),
                    "종합점수": score
                })
        except: pass
        time.sleep(0.1)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수"], ascending=[False]).head(15).reset_index(drop=True)

def draw_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)
    
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='주가', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    
    # 최근 14일 내 최대 거래량 기준봉 탐색 및 중심선 표시
    recent_14 = df.tail(14)
    peak_vol_idx = recent_14['Volume'].idxmax()
    peak_open = df.loc[peak_vol_idx, 'Open']
    peak_close = df.loc[peak_vol_idx, 'Close']
    mid_price = (peak_open + peak_close) / 2
    
    # 가로선(중심선) 추가
    fig.add_hline(y=mid_price, line_dash="dot", line_color="green", annotation_text="기준봉 1/2 중심선 (세력 방어선)", annotation_position="bottom right")
    
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2), name='20일선'), row=1, col=1)
    colors = ['red' if df['Close'].iloc[i] > df['Open'].iloc[i] else 'blue' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='거래량'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker_name} ({ticker}) 기준봉 중심선 눌림목 차트", yaxis_title="가격 (원)", yaxis2_title="거래량", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("🎯 주식 스윙 타점(기준봉 중심선) 스크리너")
st.markdown("시가총액 300대 우량주 중, **최근 2주 내 10% 이상 급등한 장대양봉의 '절반(중심선)' 부근까지 거래량 없이 조정을 받은 종목**을 추적합니다.")

if st.button("스윙 & 매집 주식 탐지 시작", type="primary"):
    st.session_state['run_screener'] = True

if st.session_state.get('run_screener', False):
    universe_df = get_market_universe()
    if not universe_df.empty:
        result_df = run_stock_swing_screener(universe_df)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,}", "중심선가격": "{:,}"}), use_container_width=True)
            
            stock_options = [f"{row['종목명']} ({row['종목코드']})" for i, row in result_df.iterrows()]
            selected_stock = st.selectbox("정밀 차트 분석 (초록색 방어선 확인):", stock_options)
            
            sel_name = selected_stock.split(" (")[0]
            sel_code = selected_stock.split(" (")[1].replace(")", "")
            
            current_price = result_df[result_df['종목코드'] == sel_code]['현재가'].values[0]
            mid_price = result_df[result_df['종목코드'] == sel_code]['중심선가격'].values[0]
            matched_conds = result_df[result_df['종목코드'] == sel_code]['만족조건'].values[0]
            market_type = result_df[result_df['종목코드'] == sel_code]['시장'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_chart(sel_code, sel_name), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,} 원")
                st.warning(f"**중심선 가격:** {mid_price:,} 원")
                st.success(f"**달성조건:** {matched_conds}")
                st.error(f"**소속시장:** {market_type}")
                st.markdown("""
                **💡 중심선 매매 팁**
                * 차트의 **초록색 점선**이 세력이 돈을 쓴 장대양봉의 1/2 지점(중심선)입니다.
                * 주가가 이 선 부근에서 하락을 멈추고 거래량이 급감했다면 세력이 이탈하지 않고 물량을 소화 중이라는 뜻입니다.
                """)
        else:
            st.warning("현재 최소 기준 점수(30점)를 만족하는 주식이 없습니다.")
