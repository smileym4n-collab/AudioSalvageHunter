from __future__ import annotations

import csv
from pathlib import Path

from .models import DonorEquipment

VALID_CONFIDENCE = {"confirmed", "probable", "uncertain"}


def split_multi(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.replace(";", "|").split("|") if part.strip())


def row_value(row: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value.strip()
    return default


def load_donors(path: str | Path) -> list[DonorEquipment]:
    donors: list[DonorEquipment] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            confidence = row_value(row, "confidence_level", default="uncertain").lower()
            if confidence not in VALID_CONFIDENCE:
                confidence = "uncertain"
            valuable_components = split_multi(row_value(row, "likely_valuable_components", "valuable_components"))
            comments = row_value(row, "general_comments", "notes")
            donors.append(
                DonorEquipment(
                    manufacturer=row_value(row, "manufacturer"),
                    model=row_value(row, "model"),
                    aliases=split_multi(row_value(row, "aliases")),
                    category=row_value(row, "category"),
                    valuable_components=valuable_components,
                    component_type=split_multi(row_value(row, "component_type")),
                    confidence_level=confidence,
                    desirability_score=int(float(row_value(row, "desirability_score", default="0") or 0)),
                    maximum_total_price_gbp=float(row_value(row, "maximum_worthwhile_delivered_price_gbp", "maximum_total_price_gbp", default="0") or 0),
                    ideal_fault_types=split_multi(row_value(row, "ideal_fault_types")),
                    risky_fault_types=split_multi(row_value(row, "risky_fault_types")),
                    salvage_difficulty=row_value(row, "salvage_difficulty"),
                    package_or_removal_notes=row_value(row, "package_or_removal_notes"),
                    source_or_verification_note=row_value(row, "source_or_verification_note"),
                    general_comments=comments,
                    notes=comments,
                )
            )
    return donors
