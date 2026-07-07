from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..cli import collect_queries, detect_price_reduction, mock_listings
from ..donors import load_donors
from ..ebay import EbayApiError, EbayClient, deduplicate
from ..matching import find_terms
from ..models import Listing, ScoreResult
from ..notify import send_telegram_notifications
from ..reports import ScoredListing
from ..scoring import score_listing
from .importers import export_donors_csv
from .models import DonorRecord, ListingRecord, PriceHistoryRecord, ScanErrorRecord, ScanRunRecord
from .settings import get_setting, get_settings


LOG = logging.getLogger(__name__)
scan_lock = threading.Lock()
current_scan_id: int | None = None
current_scan_thread: threading.Thread | None = None


def split_text(value: str) -> list[str]:
    return [part.strip() for part in value.replace("|", ";").split(";") if part.strip()]


def donor_records_as_csv_file(db: Session) -> str:
    return export_donors_csv(db)


def donor_records_as_scoring_donors(db: Session):
    from ..models import DonorEquipment

    donors = []
    for row in db.query(DonorRecord).all():
        donors.append(
            DonorEquipment(
                manufacturer=row.manufacturer,
                model=row.model,
                aliases=tuple(split_text(row.aliases)),
                category=row.category,
                valuable_components=tuple(split_text(row.likely_valuable_components)),
                component_type=tuple(split_text(row.component_type)),
                confidence_level=row.confidence_level,
                desirability_score=row.desirability_score,
                maximum_total_price_gbp=row.maximum_worthwhile_delivered_price_gbp,
                ideal_fault_types=tuple(split_text(row.ideal_fault_types)),
                risky_fault_types=tuple(split_text(row.risky_fault_types)),
                salvage_difficulty=row.salvage_difficulty,
                package_or_removal_notes=row.package_or_removal_notes,
                source_or_verification_note=row.source_or_verification_note,
                general_comments=row.general_comments,
                notes=row.general_comments,
            )
        )
    return donors or load_donors("donor_database.csv")


def upsert_listing_record(
    db: Session,
    listing: Listing,
    score: ScoreResult,
    is_new: bool,
    price_reduction: float | None,
    raw_json: str | None = None,
) -> ListingRecord:
    now = datetime.now(timezone.utc)
    record = db.query(ListingRecord).filter_by(item_id=listing.item_id).one_or_none()
    if record is None:
        record = ListingRecord(item_id=listing.item_id, first_seen_at=now)
        db.add(record)
    record.title = listing.title
    record.item_url = listing.item_url
    record.image_url = listing.image_url
    record.price = listing.price
    record.postage = listing.postage
    record.total_price = listing.total_price
    record.currency = listing.currency or "GBP"
    record.condition = listing.condition
    record.seller = listing.seller
    record.location = listing.location
    record.start_time = listing.start_time
    record.end_time = listing.end_time
    record.buying_options = "; ".join(listing.buying_options)
    record.price_basis = listing.price_basis
    record.postage_unknown = listing.postage_unknown
    record.collection_only = bool(find_terms(" ".join([listing.title, listing.condition, listing.location]), ["collection only", "local pickup", "local pick up"]))
    record.score = score.score
    record.raw_score = score.raw_score
    record.matched_donor = score.matched_donor or ""
    record.matched_manufacturer = ""
    record.matched_category = ""
    if score.matched_donor:
        for donor_row in db.query(DonorRecord).all():
            if f"{donor_row.manufacturer} {donor_row.model}".strip() == score.matched_donor:
                record.matched_manufacturer = donor_row.manufacturer
                record.matched_category = donor_row.category
                break
    record.matched_name = score.matched_name or ""
    record.matched_confidence = score.matched_confidence or ""
    record.matched_component_types = "; ".join(score.matched_component_types)
    record.possible_components = "; ".join(score.possible_components)
    record.score_reasons = "\n".join(score.reasons)
    record.positive_indicators = "; ".join(score.positive_indicators)
    record.risk_indicators = "; ".join(score.risk_indicators)
    record.last_seen_at = now
    record.last_price_reduction = price_reduction
    record.raw_json = raw_json if raw_json is not None else json.dumps(listing.raw, default=str)
    if listing.end_time:
        record.active = True
    db.flush()
    db.add(PriceHistoryRecord(listing_id=record.id, price=listing.price, postage=listing.postage, total_price=listing.total_price))
    return record


def scan_status() -> dict[str, object]:
    return {"running": scan_lock.locked(), "scan_id": current_scan_id}


def start_scan_background(app, scan_id: int) -> None:
    global current_scan_thread
    thread = threading.Thread(target=run_scan_by_id, args=(app, scan_id), daemon=False, name=f"scan-{scan_id}")
    current_scan_thread = thread
    thread.start()


def run_scan_by_id(app, scan_id: int) -> None:
    from .database import SessionLocal

    global current_scan_id, current_scan_thread
    if not scan_lock.acquire(blocking=False):
        mark_scan_finished(scan_id, "blocked", "Another scan is already running.")
        return
    current_scan_id = scan_id
    try:
        with SessionLocal() as db:
            run_scan(db, scan_id)
    except Exception as exc:
        LOG.exception("Background scan %s crashed", scan_id)
        mark_scan_finished(scan_id, "failed", f"Background scan crashed: {exc}")
    finally:
        current_scan_id = None
        current_scan_thread = None
        scan_lock.release()


def mark_scan_finished(scan_id: int, status: str, message: str) -> None:
    from .database import SessionLocal

    with SessionLocal() as db:
        scan = db.get(ScanRunRecord, scan_id)
        if scan:
            scan.status = status
            scan.message = message
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()


def mark_stale_running_scans(db: Session) -> int:
    count = 0
    for scan in db.query(ScanRunRecord).filter(ScanRunRecord.status.in_(["queued", "running"])).all():
        scan.status = "interrupted"
        scan.message = "Marked interrupted during application startup."
        scan.finished_at = datetime.now(timezone.utc)
        count += 1
    db.commit()
    return count


def wait_for_scan_shutdown(timeout_seconds: float = 10.0) -> bool:
    thread = current_scan_thread
    if not thread or not thread.is_alive():
        return True
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        LOG.warning("Scan thread did not stop within %.1f seconds during shutdown.", timeout_seconds)
        if current_scan_id is not None:
            mark_scan_finished(current_scan_id, "interrupted", "Application stopped while scan was still running.")
        return False
    return True


def remove_mock_data(db: Session) -> dict[str, int]:
    mock_listings = db.query(ListingRecord).filter(ListingRecord.item_id.like("MOCK-%")).all()
    listing_ids = [listing.id for listing in mock_listings]
    price_history_count = 0
    if listing_ids:
        price_history_count = db.query(PriceHistoryRecord).filter(PriceHistoryRecord.listing_id.in_(listing_ids)).count()
    for listing in mock_listings:
        db.delete(listing)

    mock_scans = db.query(ScanRunRecord).filter(ScanRunRecord.mode.in_(["mock", "scheduled-mock"])).all()
    scan_count = len(mock_scans)
    for scan in mock_scans:
        db.delete(scan)

    commit_with_retry(db)
    return {"listings": len(mock_listings), "price_history": price_history_count, "scan_runs": scan_count}


def create_scan(db: Session, mode: str, query_group: str = "", custom_query: str = "", notifications_enabled: bool = False) -> ScanRunRecord:
    scan = ScanRunRecord(mode=mode, query_group=query_group, custom_query=custom_query, notifications_enabled=notifications_enabled, status="queued")
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def collect_live_listings(db: Session, scan: ScanRunRecord) -> list[Listing]:
    settings = get_settings(db)
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise EbayApiError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET are not configured.")
    client = EbayClient(
        client_id=client_id,
        client_secret=client_secret,
        marketplace_id=settings["marketplace_id"],
        timeout_seconds=20,
        rate_limit_delay_seconds=0.4,
    )
    terms_query = db.query(__import__("audio_salvage_hunter.web.models", fromlist=["SearchTermRecord"]).SearchTermRecord).filter_by(enabled=True)
    if scan.query_group:
        terms_query = terms_query.filter_by(group_name=scan.query_group)
    queries = [(term.group_name, term.term) for term in terms_query.all()]
    if scan.custom_query:
        queries = [("custom", scan.custom_query)]
    found: list[Listing] = []
    for group, query in queries:
        try:
            found.extend(client.search(query, limit=int(settings["max_results_per_query"])))
        except EbayApiError as exc:
            db.add(ScanErrorRecord(scan_id=scan.id, query=query, message=str(exc)))
    return deduplicate(found)


def run_scan(db: Session, scan_id: int) -> ScanRunRecord:
    scan = db.get(ScanRunRecord, scan_id)
    if scan is None:
        raise ValueError(f"Unknown scan {scan_id}")
    scan.status = "running"
    scan.started_at = datetime.now(timezone.utc)
    db.commit()
    settings = get_settings(db)
    try:
        listings = deduplicate(mock_listings()) if scan.mode == "mock" else collect_live_listings(db, scan)
        donors = donor_records_as_scoring_donors(db)
        new_count = 0
        drop_count = 0
        notify_rows: list[ScoredListing] = []
        for listing in listings:
            existing = db.query(ListingRecord).filter_by(item_id=listing.item_id).one_or_none()
            is_new = existing is None
            price_reduction = None
            if existing:
                price_reduction = detect_price_reduction(existing.total_price, listing.total_price, float(settings["meaningful_price_reduction_gbp"]))
            score = score_listing(
                listing=listing,
                donors=donors,
                scoring_terms=__import__("audio_salvage_hunter.config", fromlist=["load_config"]).load_config(__import__("audio_salvage_hunter.web.settings", fromlist=["default_config_path"]).default_config_path()).scoring_terms,
                collection_only_penalty=int(settings["collection_only_penalty"]),
                default_max_total_price_gbp=80.0,
            )
            upsert_listing_record(db, listing, score, is_new=is_new, price_reduction=price_reduction)
            if is_new:
                new_count += 1
            if price_reduction is not None:
                drop_count += 1
            if scan.notifications_enabled and score.score >= int(settings["minimum_alert_score"]) and (is_new or price_reduction is not None):
                notify_rows.append(ScoredListing(listing, score, is_new, price_reduction))
        if notify_rows and settings.get("telegram_enabled", "false") == "true":
            send_telegram_notifications(notify_rows)
        scan.status = "success"
        scan.listings_found = len(listings)
        scan.new_listings = new_count
        scan.price_drops = drop_count
        scan.message = "Scan completed."
    except Exception as exc:
        scan.status = "failed"
        scan.message = str(exc)
        db.add(ScanErrorRecord(scan_id=scan.id, query=scan.custom_query or scan.query_group, message=str(exc)))
    finally:
        scan.finished_at = datetime.now(timezone.utc)
        commit_with_retry(db)
    return scan


def commit_with_retry(db: Session, attempts: int = 5) -> None:
    for attempt in range(attempts):
        try:
            db.commit()
            return
        except Exception:
            db.rollback()
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def listing_query(db: Session, params: dict[str, object]):
    query = db.query(ListingRecord)
    search = str(params.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(ListingRecord.title.ilike(like), ListingRecord.matched_donor.ilike(like), ListingRecord.possible_components.ilike(like)))
    if params.get("min_score") not in (None, ""):
        query = query.filter(ListingRecord.score >= int(params["min_score"]))
    if params.get("max_total") not in (None, ""):
        query = query.filter(ListingRecord.total_price <= float(params["max_total"]))
    for attr, key in [
        (ListingRecord.matched_confidence, "confidence"),
        (ListingRecord.condition, "condition"),
        (ListingRecord.matched_donor, "matched_donor"),
    ]:
        if params.get(key):
            query = query.filter(attr == str(params[key]))
    if params.get("component_type"):
        query = query.filter(ListingRecord.matched_component_types.ilike(f"%{params['component_type']}%"))
    if params.get("manufacturer"):
        query = query.filter(ListingRecord.matched_manufacturer == str(params["manufacturer"]))
    if params.get("category"):
        query = query.filter(ListingRecord.matched_category == str(params["category"]))
    if params.get("collection_only") == "true":
        query = query.filter(ListingRecord.collection_only.is_(True))
    if params.get("price_drops") == "true":
        query = query.filter(ListingRecord.last_price_reduction.is_not(None))
    if params.get("active") in {"true", "false"}:
        query = query.filter(ListingRecord.active.is_(params.get("active") == "true"))
    sort = str(params.get("sort") or "score")
    sort_map = {
        "score": ListingRecord.score.desc(),
        "total_price": ListingRecord.total_price.asc(),
        "first_seen": ListingRecord.first_seen_at.desc(),
        "last_seen": ListingRecord.last_seen_at.desc(),
        "price_reduction": ListingRecord.last_price_reduction.desc(),
        "end_time": ListingRecord.end_time.asc(),
    }
    return query.order_by(sort_map.get(sort, ListingRecord.score.desc()))
