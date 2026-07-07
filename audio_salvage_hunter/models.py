from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DonorEquipment:
    manufacturer: str
    model: str
    aliases: tuple[str, ...]
    category: str
    valuable_components: tuple[str, ...]
    component_type: tuple[str, ...]
    confidence_level: str
    desirability_score: int
    maximum_total_price_gbp: float
    ideal_fault_types: tuple[str, ...]
    risky_fault_types: tuple[str, ...]
    salvage_difficulty: str
    package_or_removal_notes: str
    source_or_verification_note: str
    general_comments: str
    notes: str

    @property
    def all_names(self) -> tuple[str, ...]:
        names = (f"{self.manufacturer} {self.model}".strip(), self.model, *self.aliases)
        return tuple(dict.fromkeys(name for name in names if name))


@dataclass
class Listing:
    item_id: str
    title: str
    item_url: str
    price: float | None
    postage: float | None
    total_price: float | None
    currency: str
    condition: str
    seller: str
    location: str
    image_url: str
    start_time: str
    end_time: str
    buying_options: tuple[str, ...] = ()
    price_basis: str = "item price"
    postage_unknown: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreResult:
    score: int
    reasons: list[str]
    matched_donor: str | None = None
    matched_name: str | None = None
    matched_confidence: str | None = None
    matched_component_types: list[str] = field(default_factory=list)
    possible_components: list[str] = field(default_factory=list)
    positive_indicators: list[str] = field(default_factory=list)
    risk_indicators: list[str] = field(default_factory=list)
    raw_score: int = 0


@dataclass
class SeenListing:
    item_id: str
    first_seen_at: str
    last_seen_at: str
    best_total_price: float | None
    last_total_price: float | None
    last_score: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
