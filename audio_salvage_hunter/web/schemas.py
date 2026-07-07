from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Confidence = Literal["confirmed", "probable", "uncertain"]


class DonorIn(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    aliases: str = ""
    category: str = Field(min_length=1, max_length=255)
    likely_valuable_components: str = ""
    component_type: str = ""
    confidence_level: Confidence = "uncertain"
    desirability_score: int = Field(ge=0, le=100)
    maximum_worthwhile_delivered_price_gbp: float = Field(ge=0)
    ideal_fault_types: str = ""
    risky_fault_types: str = ""
    salvage_difficulty: str = ""
    package_or_removal_notes: str = ""
    source_or_verification_note: str = ""
    general_comments: str = ""


class DonorOut(DonorIn):
    id: int

    model_config = {"from_attributes": True}


class SearchTermIn(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    group_name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    maximum_price: float | None = Field(default=None, ge=0)
    category: str = ""
    notes: str = ""


class SearchTermOut(SearchTermIn):
    id: int

    model_config = {"from_attributes": True}


class SettingsIn(BaseModel):
    minimum_alert_score: int = Field(ge=0, le=100)
    marketplace_id: str = Field(min_length=3, max_length=32)
    max_results_per_query: int = Field(ge=1, le=1000)
    scan_interval_minutes: int = Field(ge=5, le=10080)
    collection_only_penalty: int = Field(ge=0, le=100)
    meaningful_price_reduction_gbp: float = Field(ge=0)
    telegram_enabled: bool = False
    mock_mode: bool = False
    log_level: str = "INFO"
    scheduler_enabled: bool = True
    local_timezone: str = "Europe/London"


class ScanRequest(BaseModel):
    mode: Literal["live", "mock"] = "live"
    query_group: str = ""
    custom_query: str = ""
    notifications_enabled: bool = False


class ScanOut(BaseModel):
    id: int
    mode: str
    status: str
    listings_found: int
    new_listings: int
    price_drops: int
    message: str

    model_config = {"from_attributes": True}
