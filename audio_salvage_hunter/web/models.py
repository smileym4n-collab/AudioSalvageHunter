from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ListingRecord(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    item_url: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float | None] = mapped_column(Float)
    postage: Mapped[float | None] = mapped_column(Float)
    total_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="GBP")
    condition: Mapped[str] = mapped_column(String(255), default="")
    seller: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    start_time: Mapped[str] = mapped_column(String(64), default="")
    end_time: Mapped[str] = mapped_column(String(64), default="")
    buying_options: Mapped[str] = mapped_column(Text, default="")
    price_basis: Mapped[str] = mapped_column(String(64), default="item price")
    postage_unknown: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    collection_only: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    raw_score: Mapped[int] = mapped_column(Integer, default=0)
    matched_donor: Mapped[str] = mapped_column(String(255), default="", index=True)
    matched_manufacturer: Mapped[str] = mapped_column(String(255), default="", index=True)
    matched_category: Mapped[str] = mapped_column(String(255), default="", index=True)
    matched_name: Mapped[str] = mapped_column(String(255), default="")
    matched_confidence: Mapped[str] = mapped_column(String(32), default="", index=True)
    matched_component_types: Mapped[str] = mapped_column(Text, default="")
    possible_components: Mapped[str] = mapped_column(Text, default="")
    score_reasons: Mapped[str] = mapped_column(Text, default="")
    positive_indicators: Mapped[str] = mapped_column(Text, default="")
    risk_indicators: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    last_price_reduction: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")

    price_history: Mapped[list["PriceHistoryRecord"]] = relationship(back_populates="listing", cascade="all, delete-orphan")


class PriceHistoryRecord(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    price: Mapped[float | None] = mapped_column(Float)
    postage: Mapped[float | None] = mapped_column(Float)
    total_price: Mapped[float | None] = mapped_column(Float)

    listing: Mapped[ListingRecord] = relationship(back_populates="price_history")


class ScanRunRecord(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default="live")
    query_group: Mapped[str] = mapped_column(String(255), default="")
    custom_query: Mapped[str] = mapped_column(String(255), default="")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listings_found: Mapped[int] = mapped_column(Integer, default=0)
    new_listings: Mapped[int] = mapped_column(Integer, default=0)
    price_drops: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")

    errors: Mapped[list["ScanErrorRecord"]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class ScanErrorRecord(Base):
    __tablename__ = "scan_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    query: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")

    scan: Mapped[ScanRunRecord] = relationship(back_populates="errors")


class DonorRecord(Base):
    __tablename__ = "donors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(255), index=True)
    model: Mapped[str] = mapped_column(String(255), index=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(255), index=True)
    likely_valuable_components: Mapped[str] = mapped_column(Text, default="")
    component_type: Mapped[str] = mapped_column(Text, default="")
    confidence_level: Mapped[str] = mapped_column(String(32), default="uncertain", index=True)
    desirability_score: Mapped[int] = mapped_column(Integer, default=0)
    maximum_worthwhile_delivered_price_gbp: Mapped[float] = mapped_column(Float, default=0)
    ideal_fault_types: Mapped[str] = mapped_column(Text, default="")
    risky_fault_types: Mapped[str] = mapped_column(Text, default="")
    salvage_difficulty: Mapped[str] = mapped_column(String(64), default="")
    package_or_removal_notes: Mapped[str] = mapped_column(Text, default="")
    source_or_verification_note: Mapped[str] = mapped_column(Text, default="")
    general_comments: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (UniqueConstraint("manufacturer", "model", name="uq_donor_manufacturer_model"),)


class SearchTermRecord(Base):
    __tablename__ = "search_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(255), index=True)
    group_name: Mapped[str] = mapped_column(String(255), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    maximum_price: Mapped[float | None] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class SettingRecord(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ImportStateRecord(Base):
    __tablename__ = "import_state"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
