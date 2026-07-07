from __future__ import annotations

import csv
import json
import sqlite3
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import load_config
from ..donors import load_donors
from .models import DonorRecord, ImportStateRecord, SearchTermRecord


DONOR_FIELDS = [
    "manufacturer",
    "model",
    "aliases",
    "category",
    "likely_valuable_components",
    "component_type",
    "confidence_level",
    "desirability_score",
    "maximum_worthwhile_delivered_price_gbp",
    "ideal_fault_types",
    "risky_fault_types",
    "salvage_difficulty",
    "package_or_removal_notes",
    "source_or_verification_note",
    "general_comments",
]


def join_multi(values: tuple[str, ...] | list[str]) -> str:
    return "; ".join(values)


def seed_donors_from_csv(db: Session, path: str = "donor_database.csv") -> int:
    if db.query(DonorRecord).count():
        return 0
    count = 0
    for donor in load_donors(path):
        db.add(
            DonorRecord(
                manufacturer=donor.manufacturer,
                model=donor.model,
                aliases=join_multi(donor.aliases),
                category=donor.category,
                likely_valuable_components=join_multi(donor.valuable_components),
                component_type=join_multi(donor.component_type),
                confidence_level=donor.confidence_level,
                desirability_score=donor.desirability_score,
                maximum_worthwhile_delivered_price_gbp=donor.maximum_total_price_gbp,
                ideal_fault_types=join_multi(donor.ideal_fault_types),
                risky_fault_types=join_multi(donor.risky_fault_types),
                salvage_difficulty=donor.salvage_difficulty,
                package_or_removal_notes=donor.package_or_removal_notes,
                source_or_verification_note=donor.source_or_verification_note,
                general_comments=donor.general_comments,
            )
        )
        count += 1
    db.add(ImportStateRecord(key="donors_csv_imported", value="true"))
    db.commit()
    return count


def export_donors_csv(db: Session) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=DONOR_FIELDS)
    writer.writeheader()
    for donor in db.query(DonorRecord).order_by(DonorRecord.manufacturer, DonorRecord.model):
        writer.writerow({field: getattr(donor, field) for field in DONOR_FIELDS})
    return output.getvalue()


def import_donors_csv_text(db: Session, text: str) -> int:
    reader = csv.DictReader(StringIO(text))
    count = 0
    for row in reader:
        manufacturer = (row.get("manufacturer") or "").strip()
        model = (row.get("model") or "").strip()
        if not manufacturer or not model:
            continue
        existing = db.query(DonorRecord).filter_by(manufacturer=manufacturer, model=model).one_or_none()
        donor = existing or DonorRecord(manufacturer=manufacturer, model=model)
        for field in DONOR_FIELDS:
            if field in {"manufacturer", "model"}:
                continue
            if field in row:
                setattr(donor, field, row[field] or "")
        if not existing:
            db.add(donor)
        count += 1
    db.commit()
    return count


def seed_search_terms_from_config(db: Session, config_path: str | None = None) -> int:
    if db.query(SearchTermRecord).count():
        return 0
    from .settings import default_config_path

    config = load_config(config_path or default_config_path())
    count = 0
    for group, terms in config.search_groups.items():
        for term in terms:
            db.add(SearchTermRecord(term=term, group_name=group, enabled=True))
            count += 1
    db.commit()
    return count


def import_legacy_seen_sqlite(db: Session, legacy_path: str) -> int:
    from .services import upsert_listing_record
    from ..models import Listing, ScoreResult

    path = Path(legacy_path)
    if not path.exists():
        return 0
    marker = db.get(ImportStateRecord, f"legacy_seen:{path}")
    if marker:
        return 0
    source = sqlite3.connect(path)
    source.row_factory = sqlite3.Row
    count = 0
    try:
        for row in source.execute("SELECT * FROM seen_listings"):
            listing = Listing(
                item_id=row["item_id"],
                title=row["title"],
                item_url=row["item_url"],
                price=None,
                postage=None,
                total_price=row["last_total_price"],
                currency="GBP",
                condition="",
                seller="",
                location="",
                image_url="",
                start_time="",
                end_time="",
            )
            score = ScoreResult(score=row["last_score"], reasons=["Imported from legacy seen-listing database."])
            upsert_listing_record(db, listing, score, is_new=False, price_reduction=None, raw_json=json.dumps({"legacy_import": True}))
            count += 1
    finally:
        source.close()
    db.add(ImportStateRecord(key=f"legacy_seen:{path}", value="true"))
    db.commit()
    return count
