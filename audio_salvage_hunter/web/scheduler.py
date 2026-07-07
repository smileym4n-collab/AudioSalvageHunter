from __future__ import annotations

import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .database import SessionLocal
from .models import ScanRunRecord
from .services import create_scan, run_scan_by_id, scan_status
from .settings import bool_setting, get_setting


scheduler = BackgroundScheduler(timezone="UTC")


def ebay_credentials_configured() -> bool:
    return bool(os.getenv("EBAY_CLIENT_ID") and os.getenv("EBAY_CLIENT_SECRET"))


def scheduled_scan_mode(mock_mode: bool) -> str:
    if mock_mode or not ebay_credentials_configured():
        return "mock"
    return "live"


def scheduled_scan(app=None) -> None:
    if scan_status()["running"]:
        return
    with SessionLocal() as db:
        mode = scheduled_scan_mode(get_setting(db, "mock_mode") == "true")
        scan = create_scan(db, mode=mode, notifications_enabled=bool_setting(db, "telegram_enabled"))
        scan.mode = f"scheduled-{mode}"
        db.commit()
        run_scan_by_id(app, scan.id)


def configure_scheduler(app=None) -> None:
    with SessionLocal() as db:
        enabled = bool_setting(db, "scheduler_enabled")
        interval = int(get_setting(db, "scan_interval_minutes", "60"))
    if not scheduler.running:
        scheduler.start(paused=not enabled)
    elif enabled:
        scheduler.resume()
    else:
        scheduler.pause()
    scheduler.remove_all_jobs()
    if enabled:
        scheduler.add_job(scheduled_scan, "interval", minutes=interval, id="scan", args=[app], replace_existing=True)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def pause_scheduler() -> None:
    if scheduler.running:
        scheduler.pause()


def resume_scheduler() -> None:
    if scheduler.running:
        scheduler.resume()


def next_run_time() -> datetime | None:
    job = scheduler.get_job("scan")
    return job.next_run_time if job else None


def scheduler_status(mock_mode: bool = False) -> dict[str, object]:
    return {
        "enabled": scheduler.get_job("scan") is not None,
        "running": scheduler.running,
        "mode": scheduled_scan_mode(mock_mode),
        "credentials_configured": ebay_credentials_configured(),
        "next_run_time": next_run_time(),
    }
