from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Listing, SeenListing, utc_now_iso


class SeenStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                item_id TEXT PRIMARY KEY,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                best_total_price REAL,
                last_total_price REAL,
                last_score INTEGER NOT NULL,
                title TEXT NOT NULL,
                item_url TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def get(self, item_id: str) -> SeenListing | None:
        row = self.connection.execute("SELECT * FROM seen_listings WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return None
        return SeenListing(
            item_id=row["item_id"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            best_total_price=row["best_total_price"],
            last_total_price=row["last_total_price"],
            last_score=row["last_score"],
        )

    def upsert(self, listing: Listing, score: int) -> None:
        now = utc_now_iso()
        existing = self.get(listing.item_id)
        if existing:
            best = listing.total_price
            if existing.best_total_price is not None and best is not None:
                best = min(existing.best_total_price, best)
            elif existing.best_total_price is not None:
                best = existing.best_total_price
            self.connection.execute(
                """
                UPDATE seen_listings
                SET last_seen_at = ?, best_total_price = ?, last_total_price = ?,
                    last_score = ?, title = ?, item_url = ?
                WHERE item_id = ?
                """,
                (now, best, listing.total_price, score, listing.title, listing.item_url, listing.item_id),
            )
        else:
            self.connection.execute(
                """
                INSERT INTO seen_listings (
                    item_id, first_seen_at, last_seen_at, best_total_price,
                    last_total_price, last_score, title, item_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (listing.item_id, now, now, listing.total_price, listing.total_price, score, listing.title, listing.item_url),
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
