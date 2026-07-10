from typing import Optional

import pandas as pd

from .indicators import adx, atr, bollinger_bands, macd, pct_change, rsi, volume_ratio
from .models import TechSnapshot


def tech_summary(hist: pd.DataFrame) -> TechSnapshot:
    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    chg = last - prev
    chg_pct = chg / prev * 100

    sma5_series = close.rolling(5).mean()
    sma10_series = close.rolling(10).mean()
    sma20_series = close.rolling(20).mean()
    sma50_series = close.rolling(50).mean()
    sma200_series = close.rolling(200).mean()
    rsi_series = rsi(close)
    macd_line, signal_line, hist_line = macd(close)
    bb_sma, bb_upper, bb_lower = bollinger_bands(close)
    atr14_series = atr(high, low, close)
    plus_di, minus_di, adx_series = adx(high, low, close)
    vol_ratio_series = volume_ratio(volume)
    vol_ratio_5_series = volume / (volume.rolling(5).mean() + 1e-9)
    daily_range = (high.iloc[-1] - low.iloc[-1]) + 1e-9

    values = {
        "last": last,
        "prev": prev,
        "chg": chg,
        "chg_pct": chg_pct,
        "sma5": float(sma5_series.iloc[-1]),
        "sma10": float(sma10_series.iloc[-1]),
        "sma20": float(sma20_series.iloc[-1]),
        "sma50": float(sma50_series.iloc[-1]),
        "sma200": float(sma200_series.iloc[-1]) if len(close) >= 200 else float("nan"),
        "sma5_prev": float(sma5_series.iloc[-2]),
        "sma10_prev": float(sma10_series.iloc[-2]),
        "sma20_prev": float(sma20_series.iloc[-2]),
        "sma50_prev": float(sma50_series.iloc[-2]),
        "rsi14": float(rsi_series.iloc[-1]),
        "rsi14_prev": float(rsi_series.iloc[-2]),
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "macd_hist": float(hist_line.iloc[-1]),
        "macd_hist_prev": float(hist_line.iloc[-2]),
        "high_20": float(close.rolling(20).max().iloc[-1]),
        "low_20": float(close.rolling(20).min().iloc[-1]),
        "high_55": float(close.rolling(55).max().iloc[-1]),
        "low_55": float(close.rolling(55).min().iloc[-1]),
        "bb_upper": float(bb_upper.iloc[-1]),
        "bb_lower": float(bb_lower.iloc[-1]),
        "bb_sma": float(bb_sma.iloc[-1]),
        "bb_width": float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / (bb_sma.iloc[-1] + 1e-9)),
        "atr14": float(atr14_series.iloc[-1]),
        "atr_pct": float(atr14_series.iloc[-1] / (last + 1e-9) * 100),
        "plus_di": float(plus_di.iloc[-1]),
        "minus_di": float(minus_di.iloc[-1]),
        "adx14": float(adx_series.iloc[-1]),
        "vol_ratio": float(vol_ratio_series.iloc[-1]),
        "vol_ratio_5": float(vol_ratio_5_series.iloc[-1]),
        "perf20": pct_change(close, 20),
        "perf55": pct_change(close, 55),
        "close_position": float((last - low.iloc[-1]) / daily_range),
        "dist_ma5_pct": float((last - sma5_series.iloc[-1]) / (sma5_series.iloc[-1] + 1e-9) * 100),
        "dist_ma10_pct": float((last - sma10_series.iloc[-1]) / (sma10_series.iloc[-1] + 1e-9) * 100),
    }
    return TechSnapshot(values)


def intraday_snapshot(intraday: Optional[pd.DataFrame]) -> Optional[dict[str, float]]:
    if intraday is None or intraday.empty:
        return None
    close = intraday["Close"]
    volume = intraday["Volume"]
    latest = intraday.iloc[-1]
    prev = intraday.iloc[-2] if len(intraday) >= 2 else latest
    rolling_high = close.rolling(min(13, len(close))).max().iloc[-1]
    rolling_low = close.rolling(min(13, len(close))).min().iloc[-1]
    intraday_vol_ratio = volume.iloc[-1] / (volume.tail(min(20, len(volume))).mean() + 1e-9)
    return {
        "price": float(latest["Close"]),
        "open": float(latest["Open"]),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "prev_close": float(prev["Close"]),
        "chg_pct": float((latest["Close"] - prev["Close"]) / (prev["Close"] + 1e-9) * 100),
        "high_13": float(rolling_high),
        "low_13": float(rolling_low),
        "vol_ratio": float(intraday_vol_ratio),
    }
