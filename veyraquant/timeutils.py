from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


SYDNEY_TZ = ZoneInfo("Australia/Sydney")
US_EASTERN_TZ = ZoneInfo("America/New_York")


def now_sydney() -> datetime:
    return datetime.now(tz=SYDNEY_TZ)


def now_us_eastern() -> datetime:
    return datetime.now(tz=US_EASTERN_TZ)


def daily_report_due(now_dt: datetime, hour: int, minute: int, window_minutes: int) -> bool:
    target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    earliest = target - timedelta(minutes=window_minutes)
    return now_dt >= earliest


def is_us_market_weekday(now_dt_et: datetime) -> bool:
    return now_dt_et.weekday() < 5
