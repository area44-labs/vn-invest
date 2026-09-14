import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


def parse_wait_seconds(err_str):
    """Bóc tách số giây cần chờ từ thông báo lỗi Rate Limit của vnstock."""
    match = re.search(r"chờ\s+(\d+)\s+giây", err_str, re.IGNORECASE)
    if match:
        return int(match.group(1)) + 2
    match_sec = re.search(r"wait\s+(\d+)\s+sec", err_str, re.IGNORECASE)
    if match_sec:
        return int(match_sec.group(1)) + 2
    match_sec2 = re.search(r"(\d+)\s+second", err_str, re.IGNORECASE)
    if match_sec2:
        return int(match_sec2.group(1)) + 2
    return 15


try:
    from vnstock import Company, Listing, Trading
    from vnstock.api.quote import Quote as VnQuote

    VNSTOCK_AVAILABLE = True
except ImportError:
    VNSTOCK_AVAILABLE = False

logger = logging.getLogger(__name__)

STOCKS_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "data",
    "stocks.json",
)


AGENT_SIGNALS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "data",
    "agent_signals.json",
)

# Danh sách cổ phiếu chọn lọc (42 mã): Bao gồm 30 mã thuộc VN30 và 12 mã Midcap tiêu biểu
CANDIDATE_STOCKS = [
    # --- NHÓM VN30 (30 MÃ) ---
    {"symbol": "ACB", "companyName": "Ngân hàng TMCP Á Châu", "sector": "Ngân hàng"},
    {
        "symbol": "BCM",
        "companyName": "Tổng Công ty Đầu tư và Phát triển Công nghiệp",
        "sector": "Bất động sản KCN",
    },
    {
        "symbol": "BID",
        "companyName": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam",
        "sector": "Ngân hàng",
    },
    {"symbol": "BVH", "companyName": "Tập đoàn Bảo Việt", "sector": "Bảo hiểm"},
    {
        "symbol": "CTG",
        "companyName": "Ngân hàng TMCP Công Thương Việt Nam",
        "sector": "Ngân hàng",
    },
    {"symbol": "FPT", "companyName": "Công ty Cổ phần FPT", "sector": "Công nghệ"},
    {
        "symbol": "GAS",
        "companyName": "Tổng Công ty Khí Việt Nam - CTCP",
        "sector": "Dầu khí",
    },
    {
        "symbol": "GVR",
        "companyName": "Tập đoàn Công nghiệp Cao su Việt Nam - CTCP",
        "sector": "Cao su & BĐS KCN",
    },
    {
        "symbol": "HDB",
        "companyName": "Ngân hàng TMCP Phát triển TP. Hồ Chí Minh",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "HPG",
        "companyName": "Công ty Cổ phần Tập đoàn Hòa Phát",
        "sector": "Thép",
    },
    {"symbol": "MBB", "companyName": "Ngân hàng TMCP Quân Đội", "sector": "Ngân hàng"},
    {
        "symbol": "MSN",
        "companyName": "Công ty Cổ phần Tập đoàn Masan",
        "sector": "Tiêu dùng",
    },
    {
        "symbol": "MWG",
        "companyName": "Công ty Cổ phần Đầu tư Thế giới Di Động",
        "sector": "Bán lẻ",
    },
    {
        "symbol": "PLX",
        "companyName": "Tập đoàn Xăng dầu Việt Nam",
        "sector": "Năng lượng",
    },
    {
        "symbol": "POW",
        "companyName": "Tổng Công ty Điện lực Dầu khí Việt Nam - CTCP",
        "sector": "Điện lực",
    },
    {
        "symbol": "SAB",
        "companyName": "Tổng Công ty Cổ phần Bia - Rượu - Nước giải khát Sài Gòn",
        "sector": "Đồ uống",
    },
    {
        "symbol": "SSB",
        "companyName": "Ngân hàng TMCP Đông Nam Á",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "SSI",
        "companyName": "Công ty Cổ phần Chứng khoán SSI",
        "sector": "Chứng khoán",
    },
    {
        "symbol": "STB",
        "companyName": "Ngân hàng TMCP Sài Gòn Thương Tín",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "TCB",
        "companyName": "Ngân hàng TMCP Kỹ thương Việt Nam",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "TPB",
        "companyName": "Ngân hàng TMCP Tiên Phong",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "VCB",
        "companyName": "Ngân hàng TMCP Ngoại Thương Việt Nam",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "VHM",
        "companyName": "Công ty Cổ phần Vinhomes",
        "sector": "Bất động sản",
    },
    {
        "symbol": "VIB",
        "companyName": "Ngân hàng TMCP Quốc tế Việt Nam",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "VIC",
        "companyName": "Tập đoàn Vingroup - CTCP",
        "sector": "Bất động sản",
    },
    {
        "symbol": "VJC",
        "companyName": "Công ty Cổ phần Hàng không Vietjet",
        "sector": "Hàng không",
    },
    {
        "symbol": "VNM",
        "companyName": "Công ty Cổ phần Sữa Việt Nam",
        "sector": "Thực phẩm",
    },
    {
        "symbol": "VPB",
        "companyName": "Ngân hàng TMCP Việt Nam Thịnh Vượng",
        "sector": "Ngân hàng",
    },
    {
        "symbol": "VRE",
        "companyName": "Công ty Cổ phần Vincom Retail",
        "sector": "Bất động sản",
    },
    {
        "symbol": "SHB",
        "companyName": "Ngân hàng TMCP Sài Gòn - Hà Nội",
        "sector": "Ngân hàng",
    },
    # --- NHÓM MIDCAP TIỀM NĂNG DẪN DẮT (12 MÃ) ---
    {
        "symbol": "DGC",
        "companyName": "CTCP Tập đoàn Hóa chất Đức Giang",
        "sector": "Hóa chất",
    },
    {"symbol": "FRT", "companyName": "CTCP Bán lẻ Kỹ thuật số FPT", "sector": "Bán lẻ"},
    {
        "symbol": "PVD",
        "companyName": "Tổng CTCP Khoan và Dịch vụ Khoan Dầu khí",
        "sector": "Dầu khí",
    },
    {
        "symbol": "VCI",
        "companyName": "CTCP Chứng khoán Vietcap",
        "sector": "Chứng khoán",
    },
    {
        "symbol": "HCM",
        "companyName": "CTCP Chứng khoán TP.Hồ Chí Minh",
        "sector": "Chứng khoán",
    },
    {
        "symbol": "VND",
        "companyName": "CTCP Chứng khoán VNDIRECT",
        "sector": "Chứng khoán",
    },
    {"symbol": "HSG", "companyName": "CTCP Tập đoàn Hoa Sen", "sector": "Thép"},
    {"symbol": "NKG", "companyName": "CTCP Thép Nam Kim", "sector": "Thép"},
    {
        "symbol": "DXG",
        "companyName": "CTCP Tập đoàn Đất Xanh",
        "sector": "Bất động sản",
    },
    {
        "symbol": "DIG",
        "companyName": "Tổng CTCP Đầu tư Phát triển Xây dựng",
        "sector": "Bất động sản",
    },
    {
        "symbol": "PDR",
        "companyName": "CTCP Phát triển Bất động sản Phát Đạt",
        "sector": "Bất động sản",
    },
    {"symbol": "GMD", "companyName": "CTCP Gemadept", "sector": "Logistics"},
]


def round_tick_size(price, exchange="HOSE"):
    """Làm tròn giá theo đúng bước giá quy định của từng sàn giao dịch (HOSE, HNX, UPCoM)."""
    if exchange == "HOSE":
        if price < 10.0:
            step = 0.01
        elif price <= 50.0:
            step = 0.05
        else:
            step = 0.1
    else:
        step = 0.1
    return round(round(price / step) * step, 2)


def clamp_price_limits(price, ref_price, exchange="HOSE"):
    """Đảm bảo mức giá tính toán nằm trong biên độ Trần / Sàn cho phép của phiên kế tiếp."""
    pct = 0.07 if exchange == "HOSE" else (0.10 if exchange == "HNX" else 0.15)
    floor_p = round_tick_size(ref_price * (1 - pct), exchange)
    ceiling_p = round_tick_size(ref_price * (1 + pct), exchange)
    return round_tick_size(max(floor_p, min(ceiling_p, price)), exchange)


def calculate_atr(df, period=14):
    """Tính chỉ báo ATR (Average True Range) để đo lường mức độ biến động giá."""
    high, low, close = df["high"], df["low"], df["close"]
    close_prev = close.shift(1)
    tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(
        axis=1
    )
    return tr.rolling(window=period, min_periods=1).mean()


def calculate_single_tf_indicators(df):
    """Tính toán các chỉ báo kỹ thuật cơ bản (MA20, MA50, RSI, MACD, ATR) trên DataFrame OHLCV."""
    df_calc = df.copy()
    df_calc["ma20"] = df_calc["close"].rolling(window=20, min_periods=1).mean()
    df_calc["ma50"] = df_calc["close"].rolling(window=50, min_periods=1).mean()
    df_calc["vol_ma20"] = df_calc["volume"].rolling(window=20, min_periods=1).mean()

    delta = df_calc["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14, min_periods=1).mean()
    avg_loss = loss.rolling(window=14, min_periods=1).mean().replace(0, 0.00001)
    df_calc["rsi"] = (100 - (100 / (1 + (avg_gain / avg_loss)))).fillna(50)

    df_calc["ema12"] = df_calc["close"].ewm(span=12, adjust=False, min_periods=1).mean()
    df_calc["ema26"] = df_calc["close"].ewm(span=26, adjust=False, min_periods=1).mean()
    df_calc["macd"] = df_calc["ema12"] - df_calc["ema26"]
    df_calc["signal"] = df_calc["macd"].ewm(span=9, adjust=False, min_periods=1).mean()
    df_calc["hist"] = df_calc["macd"] - df_calc["signal"]
    df_calc["atr"] = calculate_atr(df_calc, 14)
    df_calc["daily_return"] = df_calc["close"].pct_change()
    return df_calc


def detect_divergence(df, lookback=40):
    """
    Nhận diện tín hiệu Phân kỳ Dương (Bullish Divergence) và Phân kỳ Âm (Bearish Divergence)
    cho chỉ báo RSI và MACD Histogram.
    - Phân kỳ Dương: Giá tạo đáy mới thấp hơn/bằng đáy cũ nhưng RSI/MACD tạo đáy mới cao hơn.
    - Phân kỳ Âm: Giá tạo đỉnh mới cao hơn/bằng đỉnh cũ nhưng RSI/MACD tạo đỉnh mới thấp hơn.
    """
    if len(df) < 15:
        return {
            "rsi_bullish": False,
            "rsi_bearish": False,
            "macd_bullish": False,
            "macd_bearish": False,
        }

    df_sub = df.tail(lookback).reset_index(drop=True)
    n = len(df_sub)

    # Tìm các điểm đáy local (tại i với window 2)
    troughs = []
    peaks = []

    for i in range(2, n - 2):
        # Đáy giá
        if (
            df_sub["low"].iloc[i] <= df_sub["low"].iloc[i - 1]
            and df_sub["low"].iloc[i] <= df_sub["low"].iloc[i - 2]
            and df_sub["low"].iloc[i] <= df_sub["low"].iloc[i + 1]
            and df_sub["low"].iloc[i] <= df_sub["low"].iloc[i + 2]
        ):
            troughs.append(i)
        # Đỉnh giá
        if (
            df_sub["high"].iloc[i] >= df_sub["high"].iloc[i - 1]
            and df_sub["high"].iloc[i] >= df_sub["high"].iloc[i - 2]
            and df_sub["high"].iloc[i] >= df_sub["high"].iloc[i + 1]
            and df_sub["high"].iloc[i] >= df_sub["high"].iloc[i + 2]
        ):
            peaks.append(i)

    rsi_bullish = False
    macd_bullish = False
    rsi_bearish = False
    macd_bearish = False

    # Phân kỳ Dương (Bullish Divergence): So sánh 2 đáy gần nhất
    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        p1, p2 = df_sub["low"].iloc[t1], df_sub["low"].iloc[t2]
        rsi1, rsi2 = df_sub["rsi"].iloc[t1], df_sub["rsi"].iloc[t2]
        macd1, macd2 = df_sub["hist"].iloc[t1], df_sub["hist"].iloc[t2]

        # Đáy giá mới thấp hơn/bằng đáy cũ nhưng RSI/MACD cao hơn
        if p2 <= p1 * 1.01 and rsi2 > rsi1 + 1.5:
            rsi_bullish = True
        if p2 <= p1 * 1.01 and macd2 > macd1 + 0.05:
            macd_bullish = True

    # Phân kỳ Âm (Bearish Divergence): So sánh 2 đỉnh gần nhất
    if len(peaks) >= 2:
        pk1, pk2 = peaks[-2], peaks[-1]
        p1, p2 = df_sub["high"].iloc[pk1], df_sub["high"].iloc[pk2]
        rsi1, rsi2 = df_sub["rsi"].iloc[pk1], df_sub["rsi"].iloc[pk2]
        macd1, macd2 = df_sub["hist"].iloc[pk1], df_sub["hist"].iloc[pk2]

        # Đỉnh giá mới cao hơn/bằng đỉnh cũ nhưng RSI/MACD thấp hơn
        if p2 >= p1 * 0.99 and rsi2 < rsi1 - 1.5:
            rsi_bearish = True
        if p2 >= p1 * 0.99 and macd2 < macd1 - 0.05:
            macd_bearish = True

    # Bổ sung kiểm tra phụ: Nếu 5 phiên gần nhất RSI tăng từ vùng oversold (<35) trong khi giá tạo đáy mới
    last_5 = df_sub.tail(5)
    if (
        not rsi_bullish
        and (last_5["low"].iloc[-1] <= last_5["low"].min())
        and (last_5["rsi"].iloc[-1] > last_5["rsi"].iloc[0] + 3.0)
        and (last_5["rsi"].min() < 40)
    ):
        rsi_bullish = True

    return {
        "rsi_bullish": rsi_bullish,
        "rsi_bearish": rsi_bearish,
        "macd_bullish": macd_bullish,
        "macd_bearish": macd_bearish,
    }


def calculate_multi_timeframe_analysis(df_daily):
    """
    Phân tích xu hướng & động lượng trên đa khung thời gian: 1H, 1D, 1W, 1M.
    Chuyển đổi dữ liệu ngày thành dữ liệu Tuần & Tháng, đồng thời tính chỉ báo và tín hiệu phân kỳ.
    Khung 1H được ước lượng từ biến động 3 phiên gần nhất.
    """
    df_d = calculate_single_tf_indicators(df_daily)
    div_d = detect_divergence(df_d)

    # Chuẩn bị DatetimeIndex cho việc Resample Weekly/Monthly
    df_resample = df_d.copy()
    if not isinstance(df_resample.index, pd.DatetimeIndex):
        if "time" in df_resample.columns:
            df_resample["date_dt"] = pd.to_datetime(df_resample["time"])
            df_resample = df_resample.set_index("date_dt")
        elif "date" in df_resample.columns:
            df_resample["date_dt"] = pd.to_datetime(df_resample["date"])
            df_resample = df_resample.set_index("date_dt")

    if not isinstance(df_resample.index, pd.DatetimeIndex):
        df_weekly = df_d
        df_monthly = df_d
    else:
        df_weekly = (
            df_resample.resample("W")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
    df_w = calculate_single_tf_indicators(df_weekly)
    div_w = detect_divergence(df_w, lookback=30)

    # Resample Monthly
    if isinstance(df_resample.index, pd.DatetimeIndex):
        df_monthly = (
            df_resample.resample("ME")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
    df_m = calculate_single_tf_indicators(df_monthly)
    div_m = detect_divergence(df_m, lookback=24)

    # Khung 1H (Ước tính từ động lượng ngắn hạn 3 phiên gần nhất)
    # Tín hiệu phân kỳ 1H: nếu trong 3 phiên gần nhất giá điều chỉnh nhẹ/đi ngang nhưng RSI & MACD ngắn hạn ngóc lên
    tail3 = df_d.tail(3)
    rsi_1h_bullish = False
    rsi_1h_bearish = False
    macd_1h_bullish = False
    macd_1h_bearish = False

    if len(tail3) >= 3:
        if (
            tail3["close"].iloc[-1] <= tail3["close"].iloc[0] * 1.005
            and tail3["rsi"].iloc[-1] > tail3["rsi"].iloc[0] + 2.0
        ):
            rsi_1h_bullish = True
        elif (
            tail3["close"].iloc[-1] >= tail3["close"].iloc[0] * 0.995
            and tail3["rsi"].iloc[-1] < tail3["rsi"].iloc[0] - 2.0
        ):
            rsi_1h_bearish = True

        if (
            tail3["hist"].iloc[-1] > tail3["hist"].iloc[0] + 0.02
            and tail3["close"].iloc[-1] <= tail3["close"].iloc[0]
        ):
            macd_1h_bullish = True
        elif (
            tail3["hist"].iloc[-1] < tail3["hist"].iloc[0] - 0.02
            and tail3["close"].iloc[-1] >= tail3["close"].iloc[0]
        ):
            macd_1h_bearish = True

    div_1h = {
        "rsi_bullish": rsi_1h_bullish,
        "rsi_bearish": rsi_1h_bearish,
        "macd_bullish": macd_1h_bullish,
        "macd_bearish": macd_1h_bearish,
    }

    tf_summary = {
        "1h": {
            "rsi": round(float(df_d["rsi"].iloc[-1]), 1),
            "macd_hist": round(float(df_d["hist"].iloc[-1]), 3),
            "divergence": div_1h,
        },
        "1d": {
            "rsi": round(float(df_d["rsi"].iloc[-1]), 1),
            "macd_hist": round(float(df_d["hist"].iloc[-1]), 3),
            "divergence": div_d,
        },
        "1w": {
            "rsi": round(float(df_w["rsi"].iloc[-1]) if not df_w.empty else 50.0, 1),
            "macd_hist": round(float(df_w["hist"].iloc[-1]) if not df_w.empty else 0.0, 3),
            "divergence": div_w,
        },
        "1m": {
            "rsi": round(float(df_m["rsi"].iloc[-1]) if not df_m.empty else 50.0, 1),
            "macd_hist": round(float(df_m["hist"].iloc[-1]) if not df_m.empty else 0.0, 3),
            "divergence": div_m,
        },
    }

    return df_d, tf_summary


def calculate_technical_indicators(df):
    df_d, _ = calculate_multi_timeframe_analysis(df)
    return df_d


def calculate_advanced_vn_risk_metrics(
    df, exchange="HOSE", is_margin_eligible=True, df_vnindex=None
):
    """
    Mô hình Đánh giá Rủi ro Định lượng Chuẩn hóa dành riêng cho thị trường Việt Nam:
    1. Giá tham chiếu: Sử dụng VWAP đối với sàn UPCoM, Giá đóng cửa đối với HOSE/HNX.
    2. Lợi nhuận cuộn 3 phiên (Chu kỳ thanh toán T+2.5) & Giá trị rủi ro VaR 95%.
    3. Tần suất chạm giá sàn trong 60 phiên gần nhất (Floor Hit Risk).
    4. Hệ số phạt đối với cổ phiếu không được cấp Margin.
    5. Biến động giá niên hóa (Annualized Volatility 60 phiên).
    6. Mức sụt giảm tối đa (Max Drawdown - MDD).
    """
    if df is None or len(df) < 20:
        return {
            "status": "REJECTED",
            "reason": "Dữ liệu không đủ 20 phiên",
            "annual_vol": 0.25,
            "historical_var_t25": -0.07,
            "mdd": -0.15,
            "floor_hits_60d": 0,
            "floor_risk_flag": False,
            "margin_penalty": 1.0 if is_margin_eligible else 1.5,
            "avg_value_20d_bn": 0.0,
        }

    # 1. Chọn giá theo đặc thù từng sàn
    price_col = (
        "vwap"
        if (exchange.upper() == "UPCOM" and "vwap" in df.columns)
        else (
            "avg_price" if (exchange.upper() == "UPCOM" and "avg_price" in df.columns) else "close"
        )
    )

    # 2. Tính Lợi nhuận 1D và T+2.5 (Explicit Settlement Horizon Helper)
    from scripts.lib.risk import calculate_t25_returns

    df["returns_1d"] = df[price_col].pct_change()
    df["returns_t25"] = calculate_t25_returns(df[price_col])

    # 3. Lọc Thanh khoản tối thiểu (20 phiên gần nhất)
    df["trading_value"] = df[price_col] * df["volume"]
    avg_value_20d = float(df["trading_value"].tail(20).mean())

    # 4. Historical VaR 95% thực tế cho chu kỳ T+2.5
    returns_t25_clean = df["returns_t25"].dropna()
    var_95_t25 = (
        float(np.percentile(returns_t25_clean, 5)) if len(returns_t25_clean) >= 5 else -0.07
    )

    # 5. Tần suất chạm sàn trong 60 phiên (Floor Hit Risk)
    floor_limit = (
        -0.068 if exchange.upper() == "HOSE" else (-0.098 if exchange.upper() == "HNX" else -0.148)
    )
    tail_returns_1d = df["returns_1d"].tail(60)
    floor_hits = int((tail_returns_1d <= floor_limit).sum())
    floor_risk_flag = floor_hits >= 2

    # 6. Penalty Margin
    margin_penalty = 1.0 if is_margin_eligible else 1.5

    # 7. Volatility Niên hóa 60 phiên
    tail_std = float(df["returns_1d"].tail(60).std())
    annual_vol = tail_std * np.sqrt(252) if not np.isnan(tail_std) else 0.25

    # 8. Max Drawdown
    rolling_max = df[price_col].cummax()
    mdd_series = (df[price_col] - rolling_max) / rolling_max
    mdd = float(mdd_series.min()) if not mdd_series.empty else -0.15

    return {
        "status": "PASSED" if avg_value_20d >= 1_000_000_000 else "LOW_LIQUIDITY",
        "avg_value_20d_bn": round(avg_value_20d / 1e9, 2),
        "annual_vol": round(annual_vol, 4),
        "historical_var_t25": round(var_95_t25, 4),
        "mdd": round(mdd, 4),
        "floor_hits_60d": floor_hits,
        "floor_risk_flag": floor_risk_flag,
        "margin_penalty": margin_penalty,
    }


def normalize_universe_risk(scanned_results, market_risk_level="LOW"):
    """
    Chuẩn hóa Điểm Rủi ro (Z-Score Normalization) trên toàn bộ danh mục cổ phiếu theo dõi.
    Phân loại cổ phiếu thành các mức rủi ro THẤP (LOW), TRUNG BÌNH (MEDIUM), CAO (HIGH).
    """
    if not scanned_results:
        return scanned_results

    valid_items = [r for r in scanned_results if "risk_metrics" in r]
    if len(valid_items) < 3:
        for r in scanned_results:
            r["riskLevel"] = r.get("riskLevel", "MEDIUM")
        return scanned_results

    # Trích xuất chỉ số để tính Z-Score
    vols = np.array([r["risk_metrics"]["annual_vol"] for r in valid_items])
    vars_t25 = np.array([abs(r["risk_metrics"]["historical_var_t25"]) for r in valid_items])
    mdds = np.array([abs(r["risk_metrics"]["mdd"]) for r in valid_items])
    penalties = np.array([r["risk_metrics"]["margin_penalty"] for r in valid_items])
    floor_flags = np.array(
        [1.5 if r["risk_metrics"]["floor_risk_flag"] else 1.0 for r in valid_items]
    )

    vol_std = vols.std() if vols.std() > 0 else 1.0
    var_std = vars_t25.std() if vars_t25.std() > 0 else 1.0
    mdd_std = mdds.std() if mdds.std() > 0 else 1.0

    vol_z = (vols - vols.mean()) / vol_std
    var_z = (vars_t25 - vars_t25.mean()) / var_std
    mdd_z = (mdds - mdds.mean()) / mdd_std

    raw_final_scores = (vol_z * 0.4 + var_z * 0.4 + mdd_z * 0.2) * penalties * floor_flags

    if market_risk_level == "HIGH":
        raw_final_scores += 0.5

    # Phân loại dựa trên Bách phân vị (Percentiles)
    p33 = np.percentile(raw_final_scores, 33)
    p66 = np.percentile(raw_final_scores, 66)

    for idx, r in enumerate(valid_items):
        score = raw_final_scores[idx]
        r["composite_risk_score"] = round(float(score), 3)
        if score >= p66 or r["risk_metrics"]["floor_risk_flag"]:
            r["riskLevel"] = "HIGH"
        elif score <= p33 and not r["risk_metrics"]["floor_risk_flag"]:
            r["riskLevel"] = "LOW"
        else:
            r["riskLevel"] = "MEDIUM"

    return scanned_results


def fetch_batch_smart_money(symbols):
    """Lấy dữ liệu giao dịch khớp lệnh, dòng tiền Khối ngoại & Tự doanh cho danh sách mã cổ phiếu."""
    smart_money_map = {sym: {"foreign_net_val": 0.0, "prop_net_val": 0.0} for sym in symbols}
    live_price_map = {sym: 0.0 for sym in symbols}
    if not VNSTOCK_AVAILABLE:
        return smart_money_map, live_price_map
    for attempt in range(3):
        try:
            price_board = Trading().price_board(symbols)
            if price_board is not None and not price_board.empty:
                for _, row in price_board.iterrows():
                    sym = row.get("symbol")
                    close = float(row.get("close_price", 0) or row.get("reference_price", 0) or 0)
                    if sym in smart_money_map:
                        f_buy = float(row.get("foreign_buy_volume", 0) or 0)
                        f_sell = float(row.get("foreign_sell_volume", 0) or 0)
                        smart_money_map[sym]["foreign_net_val"] = (f_buy - f_sell) * close
                        smart_money_map[sym]["prop_net_val"] = float(
                            row.get("prop_net_value", 0) or 0
                        )
                    if sym in live_price_map and close > 0:
                        live_price_map[sym] = close / 1000.0 if close > 1000.0 else close
                break
        except (Exception, SystemExit, BaseException) as e:  # noqa: BLE001
            err_str = str(e).lower()
            logger.warning("Failed to fetch batch price board (attempt %d): %s", attempt + 1, e)
            if (
                "rate limit" in err_str
                or "giới hạn api" in err_str
                or "wait" in err_str
                or "systemexit" in err_str
                or "quota" in err_str
                or "429" in err_str
                or "yêu cầu api" in err_str
            ):
                wait_sec = parse_wait_seconds(str(e))
                time.sleep(wait_sec)
            else:
                time.sleep(2)
    return smart_money_map, live_price_map


def check_corporate_events(symbol):
    """Kiểm tra lịch sự kiện doanh nghiệp (giao dịch không hưởng quyền) để cảnh báo hoặc tạm dừng khuyến nghị."""
    if not VNSTOCK_AVAILABLE:
        return False, "Bình thường"
    try:
        company = Company(symbol=symbol, source="VCI")
        df_events = company.events()
        if df_events is not None and not df_events.empty:
            df_events["event_date"] = pd.to_datetime(df_events["public_date"], errors="coerce")
            now = pd.Timestamp.now()
            recent_events = df_events[
                (df_events["event_date"] >= now - pd.Timedelta(days=2))
                & (df_events["event_date"] <= now + pd.Timedelta(days=3))
            ]
            if not recent_events.empty:
                event_name = recent_events.iloc[0].get("event_name", "Sự kiện quyền")
                return True, f"Cảnh báo: [{event_name}] gần ngày GDKHQ"
    except (Exception, SystemExit, BaseException) as e:  # noqa: BLE001
        logger.debug("Error checking corporate events for %s: %s", symbol, e)
    return False, "Bình thường"


def get_exchange_mapping():
    """Lấy thông tin sàn giao dịch (HOSE, HNX, UPCoM) và tên doanh nghiệp cho từng mã cổ phiếu."""
    mapping = {}
    if not VNSTOCK_AVAILABLE:
        return mapping
    for attempt in range(2):
        try:
            df = Listing().symbols_by_exchange("HOSE")
            if df is not None and not df.empty:
                stocks_df = df[df["type"] == "stock"]
                for _, row in stocks_df.iterrows():
                    ex = row.get("exchange") or "HOSE"
                    mapping[row["symbol"]] = {
                        "exchange": ex,
                        "organ_name": row.get("organ_name", ""),
                    }
                break
        except (Exception, SystemExit, BaseException) as e:  # noqa: BLE001
            err_str = str(e).lower()
            logger.warning("Failed to retrieve symbols by exchange: %s", e)
            if (
                "rate limit" in err_str
                or "giới hạn api" in err_str
                or "wait" in err_str
                or "systemexit" in err_str
                or "quota" in err_str
                or "429" in err_str
                or "yêu cầu api" in err_str
            ):
                wait_sec = parse_wait_seconds(str(e))
                time.sleep(wait_sec)
            else:
                time.sleep(2)
    return mapping


def get_historical_data_api(symbol, start_date, end_date, max_retries=1):
    if not VNSTOCK_AVAILABLE:
        return None, None
    sources = ["kbs", "msn"]
    for attempt in range(max_retries):
        for source in sources:
            try:
                q = VnQuote(symbol=symbol, source=source)
                df = q.history(start=start_date, end=end_date)
                if df is not None and not df.empty and "close" in df.columns:
                    df.columns = [c.lower() for c in df.columns]
                    for col in ["open", "high", "low", "close", "volume"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    # Verify price scale
                    if df["close"].iloc[-1] < 1.0:
                        continue
                    return df, source
            except (Exception, SystemExit, BaseException) as e:  # noqa: BLE001
                err_str = str(e).lower()
                logger.debug("Error fetching quote for %s from %s: %s", symbol, source, err_str)
                if any(
                    x in err_str
                    for x in [
                        "rate limit",
                        "giới hạn api",
                        "wait",
                        "systemexit",
                        "quota",
                        "429",
                        "yêu cầu api",
                    ]
                ):
                    wait_sec = parse_wait_seconds(str(e))
                    logger.info(
                        "Rate limit hit for %s (%s). Sleeping %d seconds...",
                        symbol,
                        source,
                        wait_sec,
                    )
                    time.sleep(wait_sec)
                else:
                    time.sleep(0.1)
        if attempt < max_retries - 1:
            time.sleep(0.2)
    return None, None


def main():
    import sys

    from scripts.generate_report import main as generate_report_main

    print("=====================================================================")
    print("DELEGATING TO UNIFIED QUANTITATIVE REPORT GENERATOR (generate_report.py)")
    print("=====================================================================")
    sys.argv = [sys.argv[0], "--update"]
    generate_report_main()


def legacy_main_deprecated():
    print("=====================================================================")
    print("BẮT ĐẦU QUÉT HỆ THỐNG VN INVEST (42 MÃ VN30 & MIDCAP HÀNG ĐẦU)")
    print("=====================================================================")

    # Load backup/original data if existing
    backup_data = {}
    try:
        if os.path.exists(STOCKS_JSON_PATH):
            with open(STOCKS_JSON_PATH, "r", encoding="utf-8") as f:
                backup_data = json.load(f)
            print("Successfully loaded original stocks.json as backup.")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load stocks.json: %s", e)

    end_date_dt = datetime.now(timezone.utc)
    start_date_dt = end_date_dt - timedelta(days=365)
    start_date, end_date = (
        start_date_dt.strftime("%Y-%m-%d"),
        end_date_dt.strftime("%Y-%m-%d"),
    )

    # Step 1: Xác định Xu hướng VN-Index
    print("\n[Step 1] Fetching VN-Index for Market Regime Filter...")
    vnindex_status, market_risk_level = "UPTREND", "LOW"
    vnindex_val = 1740.0
    vnindex_change = 0.0
    vnindex_pct = 0.0
    df_vn = None

    try:
        df_vn, _ = get_historical_data_api("VNINDEX", start_date, end_date)
        if df_vn is not None and len(df_vn) >= 20:
            for col in ["open", "high", "low", "close"]:
                if col in df_vn.columns and df_vn[col].iloc[-1] > 10000:
                    df_vn[col] = df_vn[col] / 1000.0
            df_vn = calculate_technical_indicators(df_vn)
            vnindex_val = float(df_vn["close"].iloc[-1])
            prev_vnindex = float(df_vn["close"].iloc[-2]) if len(df_vn) >= 2 else vnindex_val
            vnindex_change = vnindex_val - prev_vnindex
            vnindex_pct = (vnindex_change / prev_vnindex) * 100

            ma20_vn = float(df_vn["ma20"].iloc[-1])
            if vnindex_val < ma20_vn:
                vnindex_status, market_risk_level = "DOWNTREND", "HIGH"
            print(
                f"  -> [VN-Index]: {vnindex_val:.2f} ({vnindex_pct:+.2f}%) | Trạng thái: {vnindex_status} | Rủi ro: {market_risk_level}"
            )
        else:
            print("  -> WARNING: Failed to fetch VNINDEX. Falling back to backup context.")
    except Exception as e:  # noqa: BLE001
        logger.warning("Lỗi lấy dữ liệu VN-Index: %s", e)

    exchange_map = get_exchange_mapping()

    # Pre-fetch Batch Smart Money Signals and Live Exchange Price Map for all 42 stocks in 1 request
    all_symbols = [item["symbol"] for item in CANDIDATE_STOCKS]
    smart_money_batch, live_price_map = fetch_batch_smart_money(all_symbols)

    # Step 2: Quét toàn bộ danh sách 42 Mã chọn lọc
    scanned_results = []
    exit_scanner_alerts = []
    print(f"\n[Step 2] Bắt đầu quét {len(CANDIDATE_STOCKS)} mã cổ phiếu...")

    for idx, item in enumerate(CANDIDATE_STOCKS):
        symbol = item["symbol"]
        meta = exchange_map.get(symbol, {"exchange": "HOSE", "organ_name": item["companyName"]})
        ex = meta["exchange"]
        comp_name = item["companyName"] or meta["organ_name"]

        print(f"[{idx + 1}/{len(CANDIDATE_STOCKS)}] Đang phân tích: {symbol}...", end=" ")

        # 1. Bỏ qua nếu dính ngày GDKHQ
        has_event, event_msg = check_corporate_events(symbol)
        if has_event:
            print(f"-> [LOẠI]: {event_msg}")
            continue

        live_price = live_price_map.get(symbol, 0.0)

        # 2. Lấy giá lịch sử
        df, _ = get_historical_data_api(symbol, start_date, end_date)

        if df is not None and len(df) >= 20:
            try:
                for col in ["open", "high", "low", "close"]:
                    if df[col].iloc[-1] > 1000:
                        df[col] = df[col] / 1000.0

                # Synchronize/rescale historical prices to match real-time live price board
                if live_price > 0 and df["close"].iloc[-1] > 0:
                    scale_factor = live_price / df["close"].iloc[-1]
                    for col in ["open", "high", "low", "close"]:
                        df[col] = df[col] * scale_factor

                df, tf_summary = calculate_multi_timeframe_analysis(df)
                close = float(df["close"].iloc[-1])
                rsi = float(df["rsi"].iloc[-1])
                prev_rsi = float(df["rsi"].iloc[-2]) if len(df) >= 2 else rsi
                macd_hist = float(df["hist"].iloc[-1])
                prev_macd_hist = float(df["hist"].iloc[-2]) if len(df) >= 2 else 0.0
                ma20, ma50 = float(df["ma20"].iloc[-1]), float(df["ma50"].iloc[-1])
                atr = float(df["atr"].iloc[-1])
                vol_ratio = (
                    float(df["volume"].iloc[-1]) / float(df["vol_ma20"].iloc[-1])
                    if df["vol_ma20"].iloc[-1] > 0
                    else 1.0
                )

                # 3. Dòng tiền Khối ngoại & Tự doanh
                smart_money = smart_money_batch.get(
                    symbol, {"foreign_net_val": 0.0, "prop_net_val": 0.0}
                )
                f_val = smart_money["foreign_net_val"] / 1_000_000_000
                p_val = smart_money["prop_net_val"] / 1_000_000_000

                # 4. Tính Điểm tự tin (Quant Score 0-100) tích hợp Đa Khung Thời Gian
                score = 50
                if close > ma20:
                    score += 10
                if close > ma50:
                    score += 10
                if macd_hist > 0 and macd_hist > prev_macd_hist:
                    score += 10
                if vol_ratio > 1.2:
                    score += 10
                # Cải tiến 2: Vùng an toàn RSI & Phạt rủi ro Quá mua (Overbought)
                if 45 <= rsi <= 68:
                    score += 10
                elif rsi > 78:
                    score -= 15
                elif rsi > 70:
                    score -= 10

                if f_val > 5.0:
                    score += 10
                elif f_val < -5.0:
                    score -= 10
                if p_val > 2.0:
                    score += 5
                elif p_val < -2.0:
                    score -= 5
                if market_risk_level == "LOW":
                    score += 5
                else:
                    score -= 5

                # Cải tiến bổ sung: Sức mạnh tương quan RS (Relative Strength vs VN-Index 20 phiên)
                if df_vn is not None and len(df_vn) >= 20 and len(df) >= 20:
                    stock_ret_20 = (df["close"].iloc[-1] - df["close"].iloc[-20]) / df[
                        "close"
                    ].iloc[-20]
                    vn_ret_20 = (df_vn["close"].iloc[-1] - df_vn["close"].iloc[-20]) / df_vn[
                        "close"
                    ].iloc[-20]
                    rs_diff = stock_ret_20 - vn_ret_20
                    if rs_diff > 0.05:  # Vượt trội so với thị trường > 5%
                        score += 5
                    elif rs_diff < -0.05:  # Yếu hơn thị trường > 5%
                        score -= 5

                # Cải tiến 1: Thưởng/Phạt điểm & Khống chế Phân Kỳ Đa Khung Thời Gian
                has_major_bearish_divergence = False
                for tf in ["1h", "1d", "1w", "1m"]:
                    div = tf_summary[tf]["divergence"]
                    if tf == "1w":
                        weight_bull, weight_bear = 12, 15
                    elif tf == "1d":
                        weight_bull, weight_bear = 8, 12
                    elif tf == "1m":
                        weight_bull, weight_bear = 10, 10
                    else:  # 1h
                        weight_bull, weight_bear = 3, 5

                    if div["rsi_bullish"] or div["macd_bullish"]:
                        score += weight_bull
                    if div["rsi_bearish"] or div["macd_bearish"]:
                        score -= weight_bear
                        if tf in ["1d", "1w"]:
                            has_major_bearish_divergence = True

                # Quy tắc khống chế (Hard Cap): Nếu dính Phân kỳ âm 1D hoặc 1W, khống chế score < 65
                if has_major_bearish_divergence:
                    score = min(score, 60)

                score = max(0, min(100, score))

                # 5. Đánh giá Mức độ Rủi ro (Production-Ready Vietnam Quantitative Risk Model)
                risk_metrics = calculate_advanced_vn_risk_metrics(
                    df, exchange=ex, is_margin_eligible=True, df_vnindex=df_vn
                )
                dynamic_risk_level = "MEDIUM"  # Default before universe normalization

                # 6. Xác định điểm Quản trị vị thế (Thanh khoản T+2.5 & Biên độ sàn)
                buy_min = round_tick_size(close, ex)
                buy_max = clamp_price_limits(close * 1.02, close, ex)
                # Cải tiến 3: Tối ưu hoá điểm Dừng lỗ Cắt lỗ Đa yếu tố (T+2.5 Dynamic Stop Loss)
                # Dùng max(...) để chọn hỗ trợ kỹ thuật sát nhất, khống chế lỗ tối đa <= 7% (close * 0.93)
                lowest_low_5d = float(df["low"].tail(5).min())
                sl_atr = close - 1.8 * atr
                sl_ma20 = ma20 * 0.98
                sl_raw = max(sl_atr, lowest_low_5d, sl_ma20, close * 0.93)
                stop_loss = clamp_price_limits(sl_raw, close, ex)
                risk = max(close - stop_loss, close * 0.05)
                target1 = clamp_price_limits(close + 2.0 * risk, close, ex)
                target2 = clamp_price_limits(close + 3.0 * risk, close, ex)

                # Cải tiến: Bộ lọc Trạng thái Thị trường Thích ứng (Market Regime Adaptive Filter)
                # Khi thị trường ở xu hướng giảm (DOWNTREND) hoặc Rủi ro CAO (HIGH), siết chặt điều kiện MUA (score >= 75)
                min_buy_score = (
                    75 if market_risk_level == "HIGH" or vnindex_status == "DOWNTREND" else 65
                )

                is_buy = close > ma20 and score >= min_buy_score
                is_sell = (
                    close < ma20 or score <= 45 or macd_hist < 0 or rsi < 45 or close <= stop_loss
                )

                if is_buy:
                    action = "BUY"
                elif is_sell:
                    action = "SELL"
                else:
                    action = "HOLD/WATCH"

                if score >= 80:
                    grade = "Grade A"
                elif score >= 60:
                    grade = "Grade B"
                else:
                    grade = "Grade C"

                rr_ratio = f"1:{(target1 - close) / risk:.1f}" if action == "BUY" else "1:1.0"
                exec_notes = (
                    f"Bỏ qua lệnh nếu mở phiên T+1 hở Gap UP vượt mức {buy_max * 1000:,.0f}đ. Tuân thủ chu kỳ T+2.5, không fomo khi giá vượt quá Vùng mua."
                    if action == "BUY"
                    else "Khuyến nghị hạ tỷ trọng/bán chốt lời hoặc cắt lỗ quản trị rủi ro ngay khi vi phạm mốc MA20 hoặc xuất hiện cảnh báo phân kỳ âm."
                )

                # Diễn giải tín hiệu Phân Kỳ Đa Khung Thời Gian (1H, 1D, 1W, 1M)
                tf_names = {
                    "1h": "khung giờ (1H)",
                    "1d": "khung ngày (1D)",
                    "1w": "khung tuần (1W)",
                    "1m": "khung tháng (1M)",
                }
                div_bull_details = []
                div_bear_details = []

                for tf_k, tf_lbl in tf_names.items():
                    d_info = tf_summary[tf_k]["divergence"]
                    sigs_bull = []
                    sigs_bear = []
                    if d_info["rsi_bullish"]:
                        sigs_bull.append("RSI")
                    if d_info["macd_bullish"]:
                        sigs_bull.append("MACD")
                    if sigs_bull:
                        div_bull_details.append(f"{'/'.join(sigs_bull)} phân kỳ dương {tf_lbl}")

                    if d_info["rsi_bearish"]:
                        sigs_bear.append("RSI")
                    if d_info["macd_bearish"]:
                        sigs_bear.append("MACD")
                    if sigs_bear:
                        div_bear_details.append(f"{'/'.join(sigs_bear)} phân kỳ âm {tf_lbl}")

                if div_bull_details:
                    divergence_rationale = f"Tín hiệu xác nhận: Xuất hiện {', '.join(div_bull_details)}, báo hiệu lực cầu đảo chiều tăng điểm rất mạnh."
                elif div_bear_details:
                    divergence_rationale = f"Cảnh báo kỹ thuật: Đã xuất hiện {', '.join(div_bear_details)}, áp lực chốt lời/suy yếu gia tăng."
                else:
                    divergence_rationale = f"Động lượng đa khung: Chỉ báo RSI ({rsi:.1f}) và MACD ({macd_hist:.3f}) duy trì xu hướng đồng thuận trên khung ngày và tuần."

                rationale_points = [
                    f"Giá đóng cửa {close * 1000:,.0f}đ vượt đường trung bình động MA20 ({ma20 * 1000:,.0f}đ), củng cố xu hướng tăng."
                    if close > ma20
                    else f"Giá đóng cửa {close * 1000:,.0f}đ gãy đường xu hướng ngắn hạn MA20 ({ma20 * 1000:,.0f}đ), suy yếu xu hướng.",
                    f"Thanh khoản bùng nổ đạt {vol_ratio:.1f}x so với trung bình 20 phiên, dòng tiền mua chủ động."
                    if vol_ratio > 1.2
                    else "Thanh khoản duy trì ở mức bình ổn.",
                    divergence_rationale,
                    f"RSI khung ngày đạt {rsi:.1f} điểm, MACD Histogram ({macd_hist:.3f}) hỗ trợ đà bứt phá."
                    if macd_hist > 0
                    else f"RSI khung ngày đạt {rsi:.1f} điểm, MACD Histogram ({macd_hist:.3f}) thể hiện áp lực điều chỉnh.",
                ]
                full_rationale = " ".join(rationale_points) + (
                    " Khuyến nghị Mua gia tăng vị thế theo xu hướng."
                    if action == "BUY"
                    else " Khuyến nghị Bán/Hạ tỷ trọng để quản trị rủi ro danh mục."
                )

                # Format divergence status for H (1H), D (1D), W (1W), T (1M/Tháng)
                divergence_by_tf = {}
                tf_mapping = [("1h", "H"), ("1d", "D"), ("1w", "W"), ("1m", "T")]
                for tf_k, tf_code in tf_mapping:
                    div = tf_summary[tf_k]["divergence"]
                    if div["rsi_bullish"] or div["macd_bullish"]:
                        divergence_by_tf[tf_code] = "BULLISH"
                    elif div["rsi_bearish"] or div["macd_bearish"]:
                        divergence_by_tf[tf_code] = "BEARISH"
                    else:
                        divergence_by_tf[tf_code] = "NONE"

                scanned_results.append(
                    {
                        "symbol": symbol,
                        "companyName": comp_name,
                        "sector": item["sector"],
                        "exchange": ex,
                        "action": action,
                        "score": score,
                        "grade": grade,
                        "closePrice": round(close * 1000, 0),
                        "currentPrice": round(close, 2),
                        "foreignNetBuyBillion": round(f_val, 2),
                        "propNetBuyBillion": round(p_val, 2),
                        "buy_zone": {
                            "min": int(buy_min * 1000),
                            "max": int(buy_max * 1000),
                        },
                        "stop_loss": int(stop_loss * 1000),
                        "target_1": int(target1 * 1000),
                        "target_2": int(target2 * 1000),
                        "risk_reward_ratio": rr_ratio,
                        "rationale": full_rationale,
                        "rationale_points": rationale_points,
                        "exec_notes": exec_notes,
                        "risk_metrics": risk_metrics,
                        "riskLevel": dynamic_risk_level,
                        "divergenceByTf": divergence_by_tf,
                    }
                )
                print(f"-> [THÀNH CÔNG] Điểm: {score}/100 | Khuyến nghị: {action}")

                # Check Exit Alerts
                exit_reasons = []
                if close < ma20:
                    exit_reasons.append("Giá đóng cửa gãy đường xu hướng MA20")
                if close <= stop_loss:
                    exit_reasons.append("Giá đóng cửa vi phạm ngưỡng dừng lỗ Stop Loss")
                if prev_rsi > 70 and rsi < prev_rsi:
                    exit_reasons.append(
                        f"RSI quá mua quay đầu giảm (từ {prev_rsi:.1f} về {rsi:.1f})"
                    )
                if exit_reasons:
                    exit_scanner_alerts.append(
                        {"symbol": symbol, "close": close, "reasons": exit_reasons}
                    )

            except Exception as e:  # noqa: BLE001
                logger.error("Lỗi tính toán cho ticker %s: %s", symbol, e)
        else:
            print("-> [KHÔNG DỮ LIỆU/DỰ PHÒNG] Khôi phục từ dữ liệu backup...")
            old_rec = None
            for r in backup_data.get("recommendations", []):
                if r["symbol"] == symbol:
                    old_rec = r
                    break

            curr_p = (
                live_price if live_price > 0 else (old_rec["currentPrice"] if old_rec else 25.0)
            )

            if old_rec:
                scanned_results.append(
                    {
                        "symbol": symbol,
                        "companyName": item["companyName"],
                        "sector": item["sector"],
                        "exchange": ex,
                        "action": old_rec["type"],
                        "score": 65,
                        "grade": "Grade B",
                        "closePrice": round(curr_p * 1000, 0),
                        "currentPrice": round(curr_p, 2),
                        "foreignNetBuyBillion": 0.0,
                        "propNetBuyBillion": 0.0,
                        "buy_zone": {
                            "min": int(curr_p * 1000),
                            "max": int(curr_p * 1.02 * 1000),
                        },
                        "stop_loss": int(curr_p * 0.93 * 1000),
                        "target_1": int(curr_p * 1.1 * 1000),
                        "target_2": int(curr_p * 1.2 * 1000),
                        "risk_reward_ratio": "1:2.0",
                        "rationale": old_rec["rationale"],
                        "rationale_points": [old_rec["rationale"]],
                        "exec_notes": "Retained from previous record.",
                        "riskLevel": old_rec.get("riskLevel", "MEDIUM"),
                    }
                )
            else:
                # Default baseline fallback record
                scanned_results.append(
                    {
                        "symbol": symbol,
                        "companyName": item["companyName"],
                        "sector": item["sector"],
                        "exchange": ex,
                        "action": "HOLD/WATCH",
                        "score": 50,
                        "grade": "Grade C",
                        "closePrice": round(curr_p * 1000, 0),
                        "currentPrice": round(curr_p, 2),
                        "foreignNetBuyBillion": 0.0,
                        "propNetBuyBillion": 0.0,
                        "buy_zone": {
                            "min": int(curr_p * 1000),
                            "max": int(curr_p * 1.02 * 1000),
                        },
                        "stop_loss": int(curr_p * 0.93 * 1000),
                        "target_1": int(curr_p * 1.1 * 1000),
                        "target_2": int(curr_p * 1.2 * 1000),
                        "risk_reward_ratio": "1:2.0",
                        "rationale": "Cổ phiếu trong danh sách theo dõi xu hướng.",
                        "rationale_points": ["Cổ phiếu trong danh sách theo dõi xu hướng."],
                        "exec_notes": "Theo dõi sát tín hiệu dòng tiền.",
                        "riskLevel": "MEDIUM",
                    }
                )

        # Pacing execution delay (~1.0s) to comply with API rate limits (Guest tier: 20 req/min)
        time.sleep(1.0)

    # Step 2.5: Chuẩn hóa điểm rủi ro Z-Score toàn danh mục cổ phiếu (Universe Risk Normalization)
    scanned_results = normalize_universe_risk(scanned_results, market_risk_level=market_risk_level)

    # Step 3: Chọn lọc danh sách khuyến nghị & xuất file JSON
    print("\n[Step 3] Xuất dữ liệu cho AI Agent và Giao diện UI...")
    all_buys = [s for s in scanned_results if s["action"] == "BUY"]
    all_sells = [s for s in scanned_results if s["action"] == "SELL"]
    all_watch = [s for s in scanned_results if s["action"] == "HOLD/WATCH"]

    all_buys.sort(key=lambda x: x["score"], reverse=True)
    all_sells.sort(key=lambda x: x["score"])  # Lowest score / clearest sell signals first
    all_watch.sort(key=lambda x: x["score"], reverse=True)

    # Select top recommendations (8 buys + 4 sells)
    selected_buys = all_buys[:8]
    selected_sells = all_sells[:4]

    # Fill if not enough sells or buys
    if len(selected_sells) < 4:
        # Fill from watch list marked as SELL
        additional_sells = all_watch[: (4 - len(selected_sells))]
        for item in additional_sells:
            item["action"] = "SELL"
        selected_sells += additional_sells

    final_selections = selected_buys + selected_sells
    if len(final_selections) < 12:
        remaining = [s for s in scanned_results if s not in final_selections]
        remaining.sort(key=lambda x: x["score"], reverse=True)
        final_selections += remaining[: (12 - len(final_selections))]

    # Generate Agent Readiness JSON format
    agent_signals = {
        "scan_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "market_context": {
            "vnindex_status": vnindex_status,
            "market_risk_level": market_risk_level,
            "vnindex_value": round(vnindex_val, 2),
            "vnindex_change_percent": round(vnindex_pct, 2),
        },
        "signals": [],
    }

    for item in final_selections:
        agent_signals["signals"].append(
            {
                "ticker": item["symbol"],
                "exchange": item["exchange"],
                "action": "BUY" if item["action"] == "BUY" else "SELL",
                "confidence_score": item["score"],
                "grade": item["grade"],
                "price_data": {
                    "buy_zone": item["buy_zone"],
                    "stop_loss": item["stop_loss"],
                    "target_1": item["target_1"],
                    "target_2": item["target_2"],
                    "risk_reward_ratio": item["risk_reward_ratio"],
                },
                "technical_rationale": item["rationale_points"],
                "execution_notes": item["exec_notes"],
            }
        )

    os.makedirs(os.path.dirname(AGENT_SIGNALS_PATH), exist_ok=True)
    with open(AGENT_SIGNALS_PATH, "w", encoding="utf-8") as f:
        json.dump(agent_signals, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  -> Agent Signals JSON written to: {AGENT_SIGNALS_PATH}")

    # Generate UI-compatible stocks.json format
    ui_recommendations = []
    for item in final_selections:
        rec_type = "BUY" if item["action"] == "BUY" else "SELL"
        buy_range_str = (
            f"{item['buy_zone']['min'] / 1000:.1f} - {item['buy_zone']['max'] / 1000:.1f}"
            if rec_type == "BUY"
            else "Không khuyến nghị"
        )
        ui_recommendations.append(
            {
                "symbol": item["symbol"],
                "companyName": item["companyName"],
                "sector": item["sector"],
                "type": rec_type,
                "currentPrice": round(item["currentPrice"], 2),
                "targetBuyPrice": buy_range_str,
                "targetSellPrice": round(item["target_1"] / 1000, 2),
                "stopLossPrice": round(item["stop_loss"] / 1000, 2),
                "riskLevel": item["riskLevel"],
                "rationale": item["rationale"],
                "riskRewardRatio": item["risk_reward_ratio"],
                "divergenceByTf": item.get(
                    "divergenceByTf",
                    {"H": "NONE", "D": "NONE", "W": "NONE", "T": "NONE"},
                ),
            }
        )

    # Step 4: Update Market Summary Indices at the end
    print("\n[Step 4] Fetching fresh stock market summaries...")
    index_symbol_mapping = {
        "vnIndex": "VNINDEX",
        "hoseIndex": "VN30",
        "hnxIndex": "HNXINDEX",
        "upcomIndex": "UPCOMINDEX",
    }

    market_summary = backup_data.get(
        "marketSummary",
        {
            "vnIndex": {
                "name": "VN-Index",
                "value": 1788.61,
                "change": 15.2,
                "changePercent": 0.86,
                "volume": "18.500 tỷ VNĐ",
            },
            "hoseIndex": {
                "name": "HOSE",
                "value": 1934.83,
                "change": 12.3,
                "changePercent": 0.64,
                "volume": "15.200 tỷ VNĐ",
            },
            "hnxIndex": {
                "name": "HNX-Index",
                "value": 287.99,
                "change": -2.92,
                "changePercent": -1.0,
                "volume": "1.800 tỷ VNĐ",
            },
            "upcomIndex": {
                "name": "Upcom-Index",
                "value": 127.88,
                "change": 0.7,
                "changePercent": 0.55,
                "volume": "1.500 tỷ VNĐ",
            },
        },
    )

    for index_key, ssi_symbol in index_symbol_mapping.items():
        try:
            if index_key == "vnIndex" and df_vn is not None and len(df_vn) >= 2:
                df_idx = df_vn
            else:
                df_idx, _ = get_historical_data_api(ssi_symbol, start_date, end_date)

            if df_idx is not None and len(df_idx) >= 2:
                for col in ["open", "high", "low", "close"]:
                    if col in df_idx.columns and df_idx[col].iloc[-1] > 10000:
                        df_idx[col] = df_idx[col] / 1000.0

                latest_val = float(df_idx["close"].iloc[-1])
                prev_val = float(df_idx["close"].iloc[-2])
                change = latest_val - prev_val
                change_percent = (change / prev_val) * 100

                vol_str = market_summary[index_key].get("volume", "15.000 tỷ VNĐ")

                market_summary[index_key]["value"] = round(latest_val, 2)
                market_summary[index_key]["change"] = round(change, 2)
                market_summary[index_key]["changePercent"] = round(change_percent, 2)
                market_summary[index_key]["volume"] = vol_str
                print(f"  -> [{index_key}]: {latest_val:.2f} ({change_percent:+.2f}%)")
        except Exception as e:  # noqa: BLE001
            logger.warning("Error updating index %s: %s", ssi_symbol, e)

    local_now = datetime.now(timezone.utc)
    formatted_date = local_now.strftime("%d/%m/%Y")

    output_json = {
        "lastUpdated": formatted_date,
        "marketSummary": market_summary,
        "recommendations": ui_recommendations,
    }

    os.makedirs(os.path.dirname(STOCKS_JSON_PATH), exist_ok=True)
    with open(STOCKS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  -> UI Stocks JSON written to: {STOCKS_JSON_PATH}")

    # Output active DataFrame to terminal
    df_res = pd.DataFrame(scanned_results)
    print("\n=====================================================================")
    print("KẾT QUẢ QUÉT TÍCH CỰC (TOP CỔ PHIẾU ĐIỂM CAO NHẤT):")
    print("=====================================================================")
    if not df_res.empty:
        df_sorted = df_res.sort_values(by="score", ascending=False)
        cols_to_print = [
            c
            for c in [
                "symbol",
                "sector",
                "closePrice",
                "score",
                "foreignNetBuyBillion",
                "action",
                "buy_zone",
                "stop_loss",
            ]
            if c in df_sorted.columns
        ]
        print(df_sorted[cols_to_print].to_string(index=False))

    print("\n=====================================================================")
    print("HOÀN THÀNH CẬP NHẬT DỮ LIỆU VN INVEST!")
    print("=====================================================================")


if __name__ == "__main__":
    main()
