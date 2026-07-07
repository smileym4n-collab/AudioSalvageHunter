from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import load_config
from .models import SettingRecord


DEFAULT_SETTINGS = {
    "minimum_alert_score": "65",
    "marketplace_id": "EBAY_GB",
    "max_results_per_query": "25",
    "scan_interval_minutes": "60",
    "collection_only_penalty": "12",
    "meaningful_price_reduction_gbp": "5.0",
    "telegram_enabled": "false",
    "mock_mode": "false",
    "log_level": "INFO",
    "scheduler_enabled": "true",
    "local_timezone": os.getenv("TZ", "Europe/London"),
}


def default_config_path() -> str:
    mounted = os.getenv("ASH_CONFIG_PATH", "/app/config/config.yaml")
    return mounted if Path(mounted).exists() else "config.yaml"


def seed_settings_from_config(db: Session, config_path: str | None = None) -> None:
    if db.query(SettingRecord).count():
        return
    values = DEFAULT_SETTINGS.copy()
    try:
        config = load_config(config_path or default_config_path())
        for key, default in values.items():
            if key in config.settings:
                values[key] = str(config.settings[key])
    except Exception:
        pass
    for key, value in values.items():
        db.merge(SettingRecord(key=key, value=value))
    db.commit()


def get_setting(db: Session, key: str, default: str | None = None) -> str:
    row = db.get(SettingRecord, key)
    return row.value if row else (DEFAULT_SETTINGS.get(key, "") if default is None else default)


def get_settings(db: Session) -> dict[str, str]:
    values = DEFAULT_SETTINGS.copy()
    for row in db.query(SettingRecord).all():
        values[row.key] = row.value
    return values


def update_settings(db: Session, values: dict[str, object]) -> dict[str, str]:
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        db.merge(SettingRecord(key=key, value=str(value).lower() if isinstance(value, bool) else str(value)))
    db.commit()
    return get_settings(db)


def bool_setting(db: Session, key: str) -> bool:
    return get_setting(db, key).lower() in {"1", "true", "yes", "on"}


def local_zone(db: Session) -> ZoneInfo:
    try:
        return ZoneInfo(get_setting(db, "local_timezone", "Europe/London"))
    except Exception:
        return ZoneInfo("Europe/London")


def format_local_datetime(db: Session, value: datetime | str | None) -> str:
    if value in (None, ""):
        return "Never"
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_zone(db)).strftime("%Y-%m-%d %H:%M:%S %Z")
