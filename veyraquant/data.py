import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import numpy as np
import pandas as pd

from .config import AppConfig
from .models import DataQuality, FundamentalsData, NewsBundle, OptionsData, SymbolData


POSITIVE_WORDS = {
    "beat",
    "beats",
    "bullish",
    "buy",
    "breakout",
    "growth",
    "surge",
    "strong",
    "upgrade",
    "outperform",
    "record",
    "momentum",
    "ai",
    "lead",
    "领先",
    "增长",
    "利好",
    "强劲",
    "看多",
    "突破",
    "超预期",
    "增持",
    "上调",
    "大涨",
}

NEGATIVE_WORDS = {
    "miss",
    "misses",
    "bearish",
    "sell",
    "downgrade",
    "lawsuit",
    "weak",
    "drop",
    "risk",
    "cut",
    "delay",
    "ban",
    "concern",
    "warning",
    "bubble",
    "overvalued",
    "利空",
    "下调",
    "回落",
    "跳水",
    "风险",
    "减持",
    "承压",
    "疲弱",
    "过热",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def headline_sentiment_score(text: str) -> int:
    text_norm = normalize_text(text)
    score = 0
    for word in POSITIVE_WORDS:
        if word in text_norm:
            score += 1
    for word in NEGATIVE_WORDS:
        if word in text_norm:
            score -= 1
    return score


def safe_cache_key(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol)


class DataClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.cache_dir = Path(config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_symbol(self, symbol: str) -> SymbolData:
        warnings: list[str] = []
        quality = DataQuality()
        ticker = self._ticker(symbol, warnings)
        daily, intraday = self.fetch_price_history(symbol, ticker, warnings, quality)
        fundamentals = self.fetch_fundamentals(symbol, ticker, warnings, quality)
        options = self.fetch_options(symbol, ticker, warnings)
        news = self.fetch_news(symbol, warnings)
        quality.options_available = options is not None
        quality.news_available = bool(news.news or news.social)
        self._finalize_data_quality(symbol, quality, warnings)
        return SymbolData(symbol, daily, intraday, fundamentals, options, news, warnings, quality)

    def fetch_market_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        warnings: list[str] = []
        ticker = self._ticker(symbol, warnings)
        return self._fetch_history(symbol, ticker, "daily", "1y", "1d", warnings)

    def fetch_price_history(
        self,
        symbol: str,
        ticker: Any,
        warnings: list[str],
        quality: DataQuality | None = None,
    ) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        daily = self._fetch_history(symbol, ticker, "daily", "1y", "1d", warnings, quality)
        intraday = self._fetch_history(
            symbol, ticker, "intraday", "10d", self.config.intraday_interval, warnings, quality
        )
        return daily, intraday

    def fetch_fundamentals(
        self,
        symbol: str,
        ticker: Any,
        warnings: list[str],
        quality: DataQuality | None = None,
    ) -> FundamentalsData:
        cache_path = self.cache_dir / f"{safe_cache_key(symbol)}_fundamentals.json"
        info: dict[str, Any] = {}
        if ticker is not None:
            try:
                info = ticker.info or {}
                self._write_json(cache_path, info)
                if quality is not None:
                    quality.fundamentals_freshness = "live"
            except Exception as exc:
                warnings.append(f"{symbol} 基本面实时数据不可用，尝试使用缓存: {exc}")
                info = self._read_json(cache_path) or {}
                if quality is not None:
                    quality.fundamentals_freshness = "cache" if info else "missing"
        else:
            info = self._read_json(cache_path) or {}
            if quality is not None:
                quality.fundamentals_freshness = "cache" if info else "missing"

        return FundamentalsData(
            market_cap=info.get("marketCap"),
            trailing_pe=info.get("trailingPE"),
            forward_pe=info.get("forwardPE"),
            ps=info.get("priceToSalesTrailing12Months"),
            profit_margin=info.get("profitMargins"),
            roe=info.get("returnOnEquity"),
            revenue_growth=info.get("revenueGrowth"),
            earnings_growth=info.get("earningsGrowth"),
            fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
            fifty_two_week_low=info.get("fiftyTwoWeekLow"),
            target_mean_price=info.get("targetMeanPrice"),
            recommendation_key=info.get("recommendationKey"),
            current_price=info.get("currentPrice"),
        )

    def fetch_options(self, symbol: str, ticker: Any, warnings: list[str]) -> Optional[OptionsData]:
        if ticker is None:
            return None
        try:
            exps = ticker.options
            if not exps:
                return None
            exp = exps[0]
            chain = ticker.option_chain(exp)
        except Exception as exc:
            warnings.append(f"{symbol} 期权链不可用: {exc}")
            return None

        calls = chain.calls
        puts = chain.puts
        if calls.empty or puts.empty:
            return None

        total_call_oi = calls["openInterest"].fillna(0).sum()
        total_put_oi = puts["openInterest"].fillna(0).sum()
        total_call_vol = calls["volume"].fillna(0).sum()
        total_put_vol = puts["volume"].fillna(0).sum()
        iv_call = calls["impliedVolatility"].dropna().median()
        iv_put = puts["impliedVolatility"].dropna().median()
        iv_mid = np.nanmean([iv_call, iv_put])
        if isinstance(iv_mid, float) and math.isnan(iv_mid):
            iv_mid = None
        return OptionsData(
            expiration=str(exp),
            put_call_oi=total_put_oi / total_call_oi if total_call_oi > 0 else None,
            put_call_vol=total_put_vol / total_call_vol if total_call_vol > 0 else None,
            iv_mid=iv_mid,
        )

    def fetch_news(self, symbol: str, warnings: list[str]) -> NewsBundle:
        news_queries = [f"{symbol} earnings", f"{symbol} stock"]
        if symbol == "NVDA":
            news_queries.append("NVIDIA AI chip")
        social_queries = [
            f"site:reddit.com {symbol} stock",
            f"site:stocktwits.com {symbol}",
            f"site:x.com {symbol} stock",
        ]
        news_urls = [
            "https://nvidianews.nvidia.com/releases.xml",
            "https://feeds.feedburner.com/nvidiablog",
            "https://developer.nvidia.com/blog/feed",
        ] if symbol == "NVDA" else []
        news_urls.extend(
            "https://news.google.com/rss/search?q=" + quote(query) for query in news_queries
        )
        social_urls = [
            "https://news.google.com/rss/search?q=" + quote(query) for query in social_queries
        ]

        news_items: list[dict[str, Any]] = []
        social_items: list[dict[str, Any]] = []
        for url in news_urls:
            news_items.extend(self._fetch_feed_entries(url, 4, warnings))
        for url in social_urls:
            social_items.extend(self._fetch_feed_entries(url, 4, warnings))

        news_items = self._dedupe(news_items, 8)
        social_items = self._dedupe(social_items, 8)
        social_scores = [headline_sentiment_score(item["title"]) for item in social_items]
        avg_raw = float(np.mean(social_scores)) if social_scores else 0.0
        normalized = max(-1.0, min(1.0, avg_raw / 3.0))
        label = "中性"
        if normalized >= 0.2:
            label = "偏多"
        elif normalized <= -0.2:
            label = "偏空"

        return NewsBundle(
            news=news_items,
            social=social_items,
            social_sentiment={
                "score": normalized,
                "label": label,
                "sample_size": len(social_items),
            },
        )

    def _ticker(self, symbol: str, warnings: list[str]) -> Any:
        try:
            import yfinance as yf

            return yf.Ticker(symbol)
        except Exception as exc:
            warnings.append(f"{symbol} yfinance 不可用: {exc}")
            return None

    def _fetch_history(
        self,
        symbol: str,
        ticker: Any,
        name: str,
        period: str,
        interval: str,
        warnings: list[str],
        quality: DataQuality | None = None,
    ) -> Optional[pd.DataFrame]:
        cache_path = self.cache_dir / f"{safe_cache_key(symbol)}_{name}.csv"
        if ticker is not None:
            try:
                data = ticker.history(period=period, interval=interval, auto_adjust=True)
                data = self._clean_price_frame(data)
                if data is not None and not data.empty:
                    data.to_csv(cache_path, encoding="utf-8")
                    self._mark_history_quality(quality, name, "live", None)
                    return data
                warnings.append(f"{symbol} {name} 行情为空，尝试使用缓存")
            except Exception as exc:
                warnings.append(f"{symbol} {name} 行情不可用，尝试使用缓存: {exc}")

        cached = self._read_price_cache(cache_path)
        if cached is None or cached.empty:
            self._mark_history_quality(quality, name, "missing", None)
            warnings.append(f"{symbol} {name} 无可用缓存")
            return None
        cache_age = self._cache_age_hours(cache_path)
        self._mark_history_quality(quality, name, "cache", cache_age)
        if cache_age is not None:
            warnings.append(f"{symbol} {name} using cached data age {cache_age:.1f}h.")
        return cached

    @staticmethod
    def _mark_history_quality(
        quality: DataQuality | None,
        name: str,
        freshness: str,
        cache_age_hours: float | None,
    ) -> None:
        if quality is None:
            return
        if name == "daily":
            quality.price_freshness = freshness
        elif name == "intraday":
            quality.intraday_freshness = freshness
        if cache_age_hours is not None:
            if quality.cache_age_hours is None:
                quality.cache_age_hours = round(cache_age_hours, 2)
            else:
                quality.cache_age_hours = round(max(quality.cache_age_hours, cache_age_hours), 2)

    @staticmethod
    def _cache_age_hours(path: Path) -> float | None:
        try:
            return max(0.0, (time.time() - path.stat().st_mtime) / 3600)
        except Exception:
            return None

    def _finalize_data_quality(
        self, symbol: str, quality: DataQuality, warnings: list[str]
    ) -> None:
        level = "HIGH"
        reasons: list[str] = []
        if quality.price_freshness == "missing":
            level = "LOW"
            quality.actionable_allowed = False
            reasons.append("daily price data is missing")
        elif quality.price_freshness == "cache":
            age = quality.cache_age_hours
            if age is None:
                level = "LOW"
                quality.actionable_allowed = False
                reasons.append("daily price cache age is unknown")
            elif age > self.config.price_cache_invalid_max_age_hours:
                level = "LOW"
                quality.actionable_allowed = False
                reasons.append(
                    f"daily price cache age {age:.1f}h exceeds invalid threshold "
                    f"{self.config.price_cache_invalid_max_age_hours:.1f}h"
                )
            elif age > self.config.price_cache_actionable_max_age_hours:
                level = "LOW"
                quality.actionable_allowed = False
                reasons.append(
                    f"daily price cache age {age:.1f}h exceeds actionable threshold "
                    f"{self.config.price_cache_actionable_max_age_hours:.1f}h"
                )

        if quality.intraday_freshness in {"missing", "unknown"}:
            quality.intraday_alert_allowed = False
            reasons.append("intraday data is missing; entry alerts are disabled")
            if level == "HIGH":
                level = "MEDIUM"
        if quality.fundamentals_freshness in {"missing", "unknown"}:
            reasons.append("fundamentals data is missing or cached")
            if level == "HIGH":
                level = "MEDIUM"
        if not quality.options_available:
            reasons.append("options data is unavailable")
            if level == "HIGH":
                level = "MEDIUM"
        if not quality.news_available:
            reasons.append("news/social data is unavailable")
            if level == "HIGH":
                level = "MEDIUM"

        quality.data_quality_level = level
        quality.reasons = reasons
        if reasons:
            warnings.append(f"{symbol} data_quality={level}: " + "; ".join(reasons[:4]))

    @staticmethod
    def _clean_price_frame(data: Any) -> Optional[pd.DataFrame]:
        if data is None or data.empty:
            return None
        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [col for col in required if col not in data.columns]
        if missing:
            return None
        cleaned = data[required].copy().dropna(how="all")
        return cleaned if len(cleaned) >= 2 else None

    @staticmethod
    def _read_price_cache(path: Path) -> Optional[pd.DataFrame]:
        if not path.exists():
            return None
        try:
            data = pd.read_csv(path, index_col=0, parse_dates=True)
        except Exception:
            return None
        return DataClient._clean_price_frame(data)

    @staticmethod
    def _fetch_feed_entries(url: str, limit: int, warnings: list[str]) -> list[dict[str, Any]]:
        try:
            import feedparser

            feed = feedparser.parse(url)
        except Exception as exc:
            warnings.append(f"RSS 读取失败: {exc}")
            return []
        entries = []
        for entry in feed.entries[:limit]:
            source = entry.get("source", {})
            entries.append(
                {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": source.get("title") if isinstance(source, dict) else None,
                }
            )
        return entries

    @staticmethod
    def _dedupe(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        seen = set()
        unique = []
        for item in items:
            title = item.get("title")
            if not title:
                continue
            key = normalize_text(title)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:limit]

    @staticmethod
    def _read_json(path: Path) -> Optional[dict[str, Any]]:
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
