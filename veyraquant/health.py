"""Run manifest and system-health export.

Every full nightly run writes docs/data/health.json: what ran, how long
it took, which symbols came back live vs cache vs missing, whether the
email went out and whether the export succeeded. The intraday trigger
job stamps a lightweight heartbeat into the same file. The dashboard's
System Health card reads nothing else.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional


logger = logging.getLogger(__name__)

HEALTH_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_manifest(
    results: list[Any],
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    data_fetch_seconds: float | None = None,
    email_sent: bool = False,
    alerts_sent: int = 0,
    export_ok: Optional[bool] = None,
    run_kind: str = "daily",
) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    live = cache = failed = 0
    for result in results:
        quality = getattr(result, "data_quality", None)
        freshness = getattr(quality, "price_freshness", "unknown") if quality else "unknown"
        if freshness == "live":
            live += 1
        elif freshness == "cache":
            cache += 1
        elif freshness == "missing":
            failed += 1
        symbols.append(
            {
                "symbol": getattr(result, "symbol", "?"),
                "price_freshness": freshness,
                "intraday_freshness": getattr(quality, "intraday_freshness", "unknown")
                if quality else "unknown",
                "data_quality_level": getattr(quality, "data_quality_level", "unknown")
                if quality else "unknown",
                "warnings": len(getattr(result, "warnings", []) or []),
            }
        )
    processed = len(symbols)
    return {
        "health_schema_version": HEALTH_SCHEMA_VERSION,
        "run_kind": run_kind,
        "run_id": started_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 2),
        "data_fetch_seconds": None if data_fetch_seconds is None else round(data_fetch_seconds, 2),
        "symbols_processed": processed,
        "symbols_live": live,
        "symbols_cache": cache,
        "symbols_failed": failed,
        "cache_hit_rate_pct": round(cache / processed * 100, 1) if processed else None,
        "email_sent": bool(email_sent),
        "alerts_sent": int(alerts_sent),
        "export_ok": export_ok,
        "symbols": symbols,
    }


def write_health(export_dir: str, manifest: dict[str, Any]) -> bool:
    """Merge the manifest into health.json (daily runs own the top level;
    the intraday heartbeat lives under its own key). Best-effort."""
    if not export_dir:
        return False
    path = os.path.join(export_dir, "health.json")
    try:
        existing: dict[str, Any] = {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                existing = loaded
        except FileNotFoundError:
            pass
        except Exception:
            # Corrupt health file: overwrite with fresh state rather than
            # losing observability to a broken artifact.
            logger.warning("Unreadable health.json; rewriting.", exc_info=True)
        if manifest.get("run_kind") == "intraday":
            existing["intraday_heartbeat"] = manifest
        else:
            heartbeat = existing.get("intraday_heartbeat")
            existing = manifest
            if heartbeat is not None:
                existing["intraday_heartbeat"] = heartbeat
        os.makedirs(export_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, ensure_ascii=False, indent=1, sort_keys=True)
        return True
    except Exception:
        logger.warning("health.json write failed.", exc_info=True)
        return False


def intraday_heartbeat(
    checked_plans: int, transitions: int, started_at: str, duration_seconds: float
) -> dict[str, Any]:
    return {
        "health_schema_version": HEALTH_SCHEMA_VERSION,
        "run_kind": "intraday",
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "duration_seconds": round(duration_seconds, 2),
        "checked_plans": checked_plans,
        "transitions": transitions,
    }
