import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
import os
import requests

# 載入自定義模組
from database import (
    get_latest_date,
    get_etf_summary,
    get_holdings_by_date,
    get_stock_holding_history,
    get_all_dates
)
from downloader import run_downloader

# 設置頁面設定 - 寬版模式、標題與 Icon
st.set_page_config(
    page_title="主動型 ETF 投組追蹤分析儀表板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- 自定義 CSS 樣式 (深色高級感 + 玻璃擬態) -----------------
st.markdown("""
<style>
    /* 全域字體 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', 'Noto Sans TC', sans-serif;
    }
    
    /* 標題樣式 */
    .app-title {
        font-family: 'Outfit', sans-serif;
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(45deg, #FF8a00, #e52e71);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    /* 玻璃擬態卡片容器 */
    .glass-card {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 1.5rem;
        margin-bottom: 1rem;
    }
    
    /* 指標數據字體 */
    .metric-value {
        font-family: 'Outfit', sans-serif;
        font-size: 1.8rem;
        font-weight: 700;
        color: #f8f9fa;
    }
    
    .metric-label {
        font-size: 0.85rem;
        color: #adb5bd;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 靜態對照資料 -----------------
ETF_INFO = {
    "00981A": {
        "code": "00981A",
        "name": "主動統一台股增長 ETF",
        "ticker": "00981A.TW",
        "region": "台股"
    },
    "00988A": {
        "code": "00988A",
        "name": "主動統一全球創新 ETF",
        "ticker": "00988A.TW",
        "region": "全球"
    }
}

# ----------------- 輔助函式 -----------------
def map_stock_code_to_ticker(stock_code):
    """
    將投組中的股票代號轉為 Yahoo Finance 的 Ticker。
    """
    code = str(stock_code).strip()
    if code.endswith(" US"):
        return code.replace(" US", "")
    if code.endswith(" JP"):
        return code.replace(" JP", ".T")
    if code.endswith(" KS"):
        return code.replace(" KS", ".KS")
    if code.endswith(" GY"):
        return code.replace(" GY", ".DE")
    if code.endswith(" CH"):
        raw_code = code.replace(" CH", "")
        if raw_code.startswith("60") or raw_code.startswith("68"):
            return f"{raw_code}.SS"
        else:
            return f"{raw_code}.SZ"
    if code.endswith(" HK"):  # 香港（自動補滿四碼，如 700 HK -> 0700.HK）
        raw_code = code.replace(" HK", "")
        return f"{raw_code.zfill(4)}.HK"
    if code.endswith(" LN"):  # 英國倫敦
        return code.replace(" LN", ".L")
    if code.endswith(" AU"):  # 澳洲
        return code.replace(" AU", ".AX")
    if code.endswith(" CN"):  # 加拿大多倫多
        return code.replace(" CN", ".TO")
    if code.endswith(" SP"):  # 新加坡
        return code.replace(" SP", ".SI")
    if code.endswith(" FP"):  # 法國巴黎
        return code.replace(" FP", ".PA")
    if code.endswith(" NA"):  # 荷蘭阿姆斯特丹
        return code.replace(" NA", ".AS")
    if code.endswith(" SW"):  # 瑞士
        return code.replace(" SW", ".SW")
    if code.isdigit():
        # 1. 先試上市 (.TW)
        try:
            df = yf.download(f"{code}.TW", period="1d", progress=False)
            if not df.empty:
                return f"{code}.TW"
        except Exception:
            pass

        # 2. 再試上櫃 (.TWO)
        try:
            df = yf.download(f"{code}.TWO", period="1d", progress=False)
            if not df.empty:
                return f"{code}.TWO"
        except Exception:
            pass
        # 3. 若都抓不到，預設先補 .TW (或回傳原始 code)
        return f"{code}.TW"

@st.cache_data(ttl=1800)
def fetch_ticker_history(ticker_symbol, period="6mo"):
    """
    獲取 Yahoo Finance 股價歷史 (使用自訂 User-Agent Session 以免雲端被擋)
    """
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        })
        ticker = yf.Ticker(ticker_symbol, session=session)
        df = ticker.history(period=period)
        if df.empty:
            return None
        df.index = df.index.tz_localize(None)
        return df
    except Exception as e:
        st.error(f"獲取 {ticker_symbol} 股價失敗: {e}")
        return None

def add_ma_lines(fig, df, row=1, col=1):
    """
    計算並添加 MA5, MA15, MA25, MA50 均線到 Plotly 圖表中
    """
    if df is not None and not df.empty:
        close_prices = df['Close']
        ma_configs = [
            (5, '#fef08a', 'MA5'),
            (15, '#f97316', 'MA15'),
            (25, '#a855f7', 'MA25'),
            (50, '#3b82f6', 'MA50')
        ]
        for window, color, name in ma_configs:
            # 使用 pandas 的 rolling 來計算移動平均線
            ma = close_prices.rolling(window=window).mean()
            fig.add_trace(go.Scatter(
                x=df.index,
                y=ma,
                name=name,
                line=dict(color=color, width=1.2, shape='spline'),
                opacity=0.8,
                hoverinfo="skip"
            ), row=row, col=col)

# ----------------- 側邊欄與標頭 -----------------
with st.sidebar:
    st.markdown('<div class="app-title">ETF Tracker 📊</div>', unsafe_allow_html=True)
    st.markdown("### 主動型 ETF 追蹤分析平台")
    st.markdown("---")
    
    # 選擇要查看的 ETF
    etf_options = [f"{code} - {info['name']}" for code, info in ETF_INFO.items()]
    selected_etf_str = st.selectbox("選擇 ETF：", etf_options)
    selected_etf_code = selected_etf_str.split(" ")[0]
    etf_info = ETF_INFO[selected_etf_code]
    
    st.markdown("---")
    # 價格歷史時間區間選擇
    period_options = {"3個月": "3mo", "6個月": "6mo", "1年": "1y", "2年": "2y"}
    selected_period_label = st.selectbox("價格時間區間：", list(period_options.keys()), index=1)
    selected_period = period_options[selected_period_label]
    
    st.markdown("---")
    # 手動下載投組按鈕
    st.markdown("#### 資料庫管理")
    if st.button("🔄 手動更新下載最新投組", use_container_width=True):
        with st.spinner("正在下載與解析最新投組 Excel 中..."):
            res = run_downloader()
            success_msg = []
            for code, val in res.items():
                if val["status"] == "success":
                    success_msg.append(f"✅ **{code}** 更新成功 ({val['date']})")
                else:
                    success_msg.append(f"❌ **{code}** 更新失敗：`{val['error']}`")
            
            # 清除快取以加載新資料
            st.cache_data.clear()
            st.success("下載程序執行結束！")
            for msg in success_msg:
                st.markdown(msg)
            
            # 雲端說明提示
            st.info("💡 提示：Streamlit Cloud 為暫時性容器，此按鈕更新的資料在容器重啟後會還原。若要永久保存，請於本機執行下載後 Push 上傳至 GitHub。")
            st.rerun()

# ----------------- 主介面數據載入 -----------------
all_dates = get_all_dates(selected_etf_code)

if not all_dates:
    st.warning(f"目前資料庫中無 {selected_etf_code} 的歷史數據。請點擊側邊欄手動下載更新。")
else:
    latest_date = all_dates[-1]
    prev_date = all_dates[-2] if len(all_dates) >= 2 else None
    
    summary = get_etf_summary(selected_etf_code, latest_date)
    holdings = get_holdings_by_date(selected_etf_code, latest_date)
    
    # 計算加減倉狀態與變動
    holdings_map = {h["stock_code"]: h for h in holdings}
    
    if prev_date:
        holdings_prev = get_holdings_by_date(selected_etf_code, prev_date)
        prev_map = {h["stock_code"]: h for h in holdings_prev}
        
        latest_codes = set()
        for h in holdings:
            code = h["stock_code"]
            latest_codes.add(code)
            if code in prev_map:
                prev_shares = prev_map[code]["shares"]
                curr_shares = h["shares"]
                if curr_shares > prev_shares:
                    h["action"] = "加倉"
                elif curr_shares < prev_shares:
                    h["action"] = "減倉"
                else:
                    h["action"] = "持平"
            else:
                h["action"] = "新開倉"
                
        # 處理清倉 (前一日有但今日沒有)
        for h_prev in holdings_prev:
            code = h_prev["stock_code"]
            if code not in latest_codes:
                holdings.append({
                    "stock_code": code,
                    "stock_name": h_prev["stock_name"],
                    "shares": 0,
                    "weight": 0.0,
                    "action": "清倉"
                })
    else:
        for h in holdings:
            h["action"] = "新開倉"

    # 轉為 DataFrame 供繪圖與顯示使用
    df_holdings = pd.DataFrame(holdings)

    # ----------------- 頂部 ETF 概況卡片 -----------------
    st.markdown(f"## {etf_info['name']} ({selected_etf_code}) 投組追蹤儀表板")
    st.caption(f"資料來源：統一投信官網投組 Excel 每日(18:00)自動更新檔案，最新交易日：`{latest_date}`")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-label">最新淨值 (NAV)</div>
            <div class="metric-value">TWD {summary['nav']:.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-label">基金規模 (Net Assets)</div>
            <div class="metric-value">TWD {summary['net_assets']:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-label">流通單位數 (Outstanding)</div>
            <div class="metric-value">{summary['units_outstanding']:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-label">成分股檔數 (Holdings)</div>
            <div class="metric-value">{len(df_holdings[df_holdings['shares'] > 0])} 檔</div>
        </div>
        """, unsafe_allow_html=True)

    # ----------------- 左右兩欄佈局 -----------------
    left_col, right_col = st.columns([1, 1.1])
    
    with left_col:
        st.markdown("### 📈 ETF 走勢與持股細目")
        
        # 1. 繪製 ETF K線走勢 (加入均線功能)
        etf_history = fetch_ticker_history(etf_info["ticker"], period=selected_period)
        if etf_history is not None:
            fig_etf = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                    vertical_spacing=0.08, row_heights=[0.7, 0.3])
            
            # K線圖
            fig_etf.add_trace(go.Candlestick(
                x=etf_history.index,
                open=etf_history['Open'],
                high=etf_history['High'],
                low=etf_history['Low'],
                close=etf_history['Close'],
                increasing_line_color='#f43f5e',
                increasing_fillcolor='#f43f5e',
                decreasing_line_color='#10b981',
                decreasing_fillcolor='#10b981',
                name="ETF K線"
            ), row=1, col=1)
            
            # 添加 MA 均線 (MA5, MA15, MA25, MA50)
            add_ma_lines(fig_etf, etf_history, row=1, col=1)
            
            # 成交量
            fig_etf.add_trace(go.Bar(
                x=etf_history.index,
                y=etf_history['Volume'],
                name="成交量",
                marker_color='rgba(100, 150, 200, 0.4)'
            ), row=2, col=1)
            
            fig_etf.update_layout(
                title="",
                xaxis_rangeslider_visible=False,
                height=350,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                template="plotly_dark",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            # 強制將所有子圖綁定到同一個 X 軸 (xaxis="x")，以實現垂直貫穿的游標虛線
            fig_etf.update_traces(xaxis="x")
            
            fig_etf.update_xaxes(
                fixedrange=True, 
                gridcolor='rgba(255,255,255,0.1)',
                showspikes=True,
                spikesnap="cursor",
                spikemode="across",
                spikethickness=1,
                spikecolor="rgba(255,255,255,0.5)",
                spikedash="solid"
            )
            fig_etf.update_yaxes(fixedrange=True, gridcolor='rgba(255,255,255,0.1)')
            
            # 使用 Streamlit 渲染標題，避免與 Plotly 內建圖例重疊
            st.markdown(f"##### 📈 {selected_etf_code} {etf_info['name']} 價格走勢 ({selected_period_label})")
            st.plotly_chart(fig_etf, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info(f"💡 無法獲取 {etf_info['ticker']} 的歷史價格資料。這可能是 Yahoo Finance 目前對雲端伺服器有限制，但不影響下方成分股名細。")
            
        # 2. 持股細目表格 (採用原生 Pandas Styler 來繪製，防 HTML 被剝離)
        st.markdown("#### 成分股明細表")
        
        # 篩選要展示的資料
        df_display = df_holdings.sort_values(by="weight", ascending=False).copy()
        df_display = df_display[df_display["shares"] > 0]
        
        df_show = df_display[["stock_code", "stock_name", "weight", "action", "shares"]].copy()
        df_show.columns = ["股票代號", "股票名稱", "持股權重 (%)", "變動狀態", "持有股數 (股)"]
        
        # 定義變動狀態顏色樣式
        def style_action(val):
            if val == "加倉":  #加倉red color: #e65c5c
                return "background-color: rgba(43, 147, 72, 0.2); color: #e65c5c; font-weight: bold; text-align: center;"
            elif val == "新開倉": #新開倉orange color: #ffa500
                return "background-color: rgba(58, 134, 200, 0.2); color: #ffa500; font-weight: bold; text-align: center;"
            elif val == "減倉":   #減倉green color: #5ce65c
                return "background-color: rgba(201, 24, 74, 0.2); color: #5ce65c; font-weight: bold; text-align: center;"
            elif val == "清倉":   #清倉purple color: #FF00DA
                return "background-color: rgba(247, 127, 0, 0.2); color: #FF00DA; font-weight: bold; text-align: center;"
            else:
                return "color: #adb5bd; text-align: center;"

        # 套用樣式與格式化
        styled_df = df_show.style.map(
            style_action, subset=["變動狀態"]
        ).format({
            "持股權重 (%)": "{:.2f}%",
            "持有股數 (股)": "{:,.0f}"
        })
        
        st.dataframe(styled_df, use_container_width=True, height=450)

    # ----------------- 右側欄個股詳細分析 -----------------
    with right_col:
        st.markdown("### 🔍 個股詳細進出與持股趨勢")
        
        # 下拉選單供使用者點選想要查看的個股
        stock_list = df_holdings[df_holdings["shares"] > 0].sort_values(by="weight", ascending=False)
        stock_options = [f"{row['stock_code']} - {row['stock_name']} (權重: {row['weight']:.2f}%)" for _, row in stock_list.iterrows()]
        
        selected_stock_str = st.selectbox("選擇要分析的成分股：", stock_options)
        parts = selected_stock_str.split(" - ")
        selected_stock_code = parts[0].strip()
        selected_stock_name = parts[1].split(" (")[0].strip()
        
        # 轉換成 yfinance 格式的股票代號
        yf_stock_ticker = map_stock_code_to_ticker(selected_stock_code)
        
        # 1. 抓取個股價格數據與 SQLite 歷史持股紀錄
        stock_history = fetch_ticker_history(yf_stock_ticker, period=selected_period)
        holding_history = get_stock_holding_history(selected_etf_code, selected_stock_code)
        
        if holding_history:
            df_hist = pd.DataFrame(holding_history)
            df_hist['date'] = pd.to_datetime(df_hist['date'])
            
            # 使用 plotly 繪製同步對齊的雙軸/雙圖表
            # 第一列: 個股價格 K 線圖 + MA 均線
            # 第二列: ETF 持股量 (Area)
            # 第三列: 每日買賣變動 (Bar)
            fig_detail = make_subplots(
                rows=3, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.06, 
                row_heights=[0.5, 0.25, 0.25]
            )
            
            # 1. K線圖 (Row 1) - 若成功抓取股價則繪製 K 線，否則畫出佔位提示
            if stock_history is not None and not stock_history.empty:
                fig_detail.add_trace(go.Candlestick(
                    x=stock_history.index,
                    open=stock_history['Open'],
                    high=stock_history['High'],
                    low=stock_history['Low'],
                    close=stock_history['Close'],
                    increasing_line_color='#f43f5e',
                    increasing_fillcolor='#f43f5e',
                    decreasing_line_color='#10b981',
                    decreasing_fillcolor='#10b981',
                    name="個股價格 (K線)"
                ), row=1, col=1)
                
                # 添加個股 MA 均線 (MA5, MA15, MA25, MA50)
                add_ma_lines(fig_detail, stock_history, row=1, col=1)
            else:
                # 若 Yahoo Finance 被擋，於 K 線圖區繪製文字提示
                fig_detail.add_annotation(
                    text=f"無法獲取 {yf_stock_ticker} 的 Yahoo 歷史股價<br>（可能由於雲端 IP 存取受限，下方持股趨勢正常顯示）",
                    xref="x", yref="y",
                    x=df_hist['date'].iloc[len(df_hist)//2] if not df_hist.empty else datetime.date.today(),
                    y=1, showarrow=False,
                    font=dict(size=14, color="yellow"),
                    row=1, col=1
                )
            
            # 2. 歷史持股量 (Row 2) - 使用面積圖展現持股堆疊感
            fig_detail.add_trace(go.Scatter(
                x=df_hist['date'],
                y=df_hist['shares'],
                mode='lines',
                fill='tozeroy',
                fillcolor='rgba(43, 147, 72, 0.2)',
                line=dict(color='#c9184a', width=2),
                name="ETF 持股股數"
            ), row=2, col=1)
            
            # 3. 每日加減倉柱狀圖 (Row 3)
            # 依變動大小設置紅綠顏色 (加倉紅色，減倉綠色)
            colors = ['#c9184a' if val > 0 else '#2b9348' for val in df_hist['change']]
            fig_detail.add_trace(go.Bar(
                x=df_hist['date'],
                y=df_hist['change'],
                marker_color=colors,
                name="每日加減倉股數"
            ), row=3, col=1)
            
            fig_detail.update_layout(
                title="",
                xaxis_rangeslider_visible=False,
                height=650,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                template="plotly_dark",
                hovermode="x",
                legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1)
            )
            
            # 強制將所有子圖綁定到同一個 X 軸 (xaxis="x")，以實現垂直貫穿的游標虛線
            fig_detail.update_traces(xaxis="x")
            
            # 設定固定範圍，禁止縮放
            fig_detail.update_xaxes(
                fixedrange=True, 
                gridcolor='rgba(255,255,255,0.08)',
                showspikes=True,
                spikesnap="cursor",
                spikemode="across",
                spikethickness=1,
                spikecolor="rgba(255,255,255,0.5)",
                spikedash="solid"
            )
            fig_detail.update_yaxes(fixedrange=True, gridcolor='rgba(255,255,255,0.08)')
            
            # 使用 Streamlit 渲染標題，避免與 Plotly 內建圖例重疊
            st.markdown(f"##### 🔍 {selected_stock_code} {selected_stock_name} 進出與持股趨勢對齊 ({selected_period_label})")
            st.plotly_chart(fig_detail, use_container_width=True, config={'displayModeBar': False})
            
            # 2. 個股近期變化數值明細
            st.markdown("#### 近期交易變化紀錄 (倒序)")
            df_hist_display = df_hist.copy()
            df_hist_display['date'] = df_hist_display['date'].dt.strftime('%Y-%m-%d')
            df_hist_display = df_hist_display.sort_values(by="date", ascending=False)
            
            # 格式化數值展示
            df_hist_display['shares'] = df_hist_display['shares'].map('{:,.0f}'.format)
            df_hist_display['change'] = df_hist_display['change'].map(lambda x: f"+{x:,.0f}" if x > 0 else f"{x:,.0f}" if x < 0 else "0")
            df_hist_display['weight'] = df_hist_display['weight'].map('{:.2f}%'.format)
            
            # 重命名欄位
            df_hist_display.columns = ["日期", "持有股數 (股)", "持股比例 (%)", "當日進出變化 (股)"]
            
            st.dataframe(df_hist_display.set_index("日期"), use_container_width=True)
            
        else:
            st.info(f"無法載入 {selected_stock_code} {selected_stock_name} 的歷史持股資料。")
