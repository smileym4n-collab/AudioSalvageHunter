from __future__ import annotations

import csv
import html
from dataclasses import dataclass
from pathlib import Path

from .models import Listing, ScoreResult


@dataclass
class ScoredListing:
    listing: Listing
    score: ScoreResult
    is_new: bool
    price_reduction: float | None


def sort_results(results: list[ScoredListing]) -> list[ScoredListing]:
    return sorted(results, key=lambda row: (-row.score.score, row.listing.total_price if row.listing.total_price is not None else 999999))


def money(value: float | None, currency: str = "GBP") -> str:
    if value is None:
        return "unknown"
    return f"{currency} {value:.2f}"


def terminal_report(results: list[ScoredListing], show_all: bool, minimum_score: int) -> str:
    visible = [row for row in sort_results(results) if show_all or row.score.score >= minimum_score]
    if not visible:
        return "No listings met the current display threshold."
    lines: list[str] = []
    for row in visible:
        listing = row.listing
        marker = "NEW" if row.is_new else "SEEN"
        if row.price_reduction:
            marker += f", PRICE DROP GBP {row.price_reduction:.2f}"
        lines.extend(
            [
                f"[{marker}] Score {row.score.score:3d} | {money(listing.total_price, listing.currency or 'GBP')} delivered | {listing.title}",
                f"  URL: {listing.item_url}",
                f"  Condition: {listing.condition or 'unknown'} | Seller: {listing.seller or 'unknown'} | Location: {listing.location or 'unknown'}",
                f"  Price ({listing.price_basis}): {money(listing.price, listing.currency or 'GBP')} | Postage: {money(listing.postage, listing.currency or 'GBP')}{' (not returned by eBay)' if listing.postage_unknown else ''}",
                f"  Buying options: {', '.join(listing.buying_options) if listing.buying_options else 'unknown'}",
                f"  Start: {listing.start_time or 'unknown'} | End: {listing.end_time or 'unknown'}",
                "  Score explanation:",
            ]
        )
        lines.extend(f"    - {reason}" for reason in row.score.reasons)
        lines.append("")
    return "\n".join(lines)


def write_csv(results: list[ScoredListing], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "score",
                "is_new",
                "price_reduction_gbp",
                "item_id",
                "title",
                "item_url",
                "price",
                "postage",
                "total_delivered_price",
                "currency",
                "condition",
                "seller",
                "location",
                "image_url",
                "start_time",
                "end_time",
                "matched_donor",
                "matched_name",
                "matched_confidence",
                "matched_component_types",
                "possible_components",
                "positive_indicators",
                "risk_indicators",
                "score_explanation",
            ]
        )
        for row in sort_results(results):
            listing = row.listing
            writer.writerow(
                [
                    row.score.score,
                    row.is_new,
                    row.price_reduction,
                    listing.item_id,
                    listing.title,
                    listing.item_url,
                    listing.price,
                    listing.postage,
                    listing.total_price,
                    listing.currency,
                    listing.condition,
                    listing.seller,
                    listing.location,
                    listing.image_url,
                    listing.start_time,
                    listing.end_time,
                    row.score.matched_donor,
                    row.score.matched_name,
                    row.score.matched_confidence,
                    "; ".join(row.score.matched_component_types),
                    "; ".join(row.score.possible_components),
                    "; ".join(row.score.positive_indicators),
                    "; ".join(row.score.risk_indicators),
                    " | ".join(row.score.reasons),
                ]
            )


def write_html(results: list[ScoredListing], path: str | Path, show_all: bool, minimum_score: int) -> None:
    visible = [row for row in sort_results(results) if show_all or row.score.score >= minimum_score]
    cards = []
    for row in visible:
        listing = row.listing
        reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in row.score.reasons)
        image = f'<img src="{html.escape(listing.image_url)}" alt="" loading="lazy">' if listing.image_url else ""
        badge = "New" if row.is_new else "Seen"
        if row.price_reduction:
            badge += f" - price drop GBP {row.price_reduction:.2f}"
        cards.append(
            f"""
            <article class="listing">
              <div class="media">{image}</div>
              <div class="body">
                <div class="score">Score {row.score.score}</div>
                <h2><a href="{html.escape(listing.item_url)}">{html.escape(listing.title)}</a></h2>
                <p class="meta">{html.escape(badge)} | {html.escape(money(listing.total_price, listing.currency or "GBP"))} delivered | {html.escape(listing.condition or "unknown")}</p>
                <p class="meta">Seller: {html.escape(listing.seller or "unknown")} | Location: {html.escape(listing.location or "unknown")}</p>
                <p class="meta">Matched donor: {html.escape(row.score.matched_donor or "none")} | Confidence: {html.escape(row.score.matched_confidence or "n/a")}</p>
                <p class="meta">Price basis: {html.escape(listing.price_basis)} | Postage: {html.escape(money(listing.postage, listing.currency or "GBP"))}{html.escape(" (not returned by eBay)" if listing.postage_unknown else "")}</p>
                <p class="meta">Buying options: {html.escape(", ".join(listing.buying_options) if listing.buying_options else "unknown")}</p>
                <p class="meta">Start: {html.escape(listing.start_time or "unknown")} | End: {html.escape(listing.end_time or "unknown")}</p>
                <ul>{reasons}</ul>
              </div>
            </article>
            """
        )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Audio Salvage Hunter Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f6f7f9; color: #1c2530; }}
    header {{ padding: 24px; background: #22313f; color: white; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .listing {{ display: grid; grid-template-columns: 160px 1fr; gap: 18px; padding: 16px; margin-bottom: 16px; background: white; border: 1px solid #d9dee5; border-radius: 8px; }}
    img {{ width: 160px; height: 160px; object-fit: contain; background: #eef1f4; }}
    h2 {{ margin: 0 0 8px; font-size: 20px; }}
    a {{ color: #095aa6; }}
    .score {{ float: right; font-weight: 700; background: #e8f2e7; color: #245b2a; padding: 6px 10px; border-radius: 6px; }}
    .meta {{ color: #52606f; margin: 6px 0; }}
    li {{ margin: 5px 0; }}
    @media (max-width: 700px) {{ .listing {{ grid-template-columns: 1fr; }} .score {{ float: none; display: inline-block; margin-bottom: 8px; }} }}
  </style>
</head>
<body>
  <header><h1>Audio Salvage Hunter Report</h1></header>
  <main>{''.join(cards) if cards else '<p>No listings met the current display threshold.</p>'}</main>
</body>
</html>
"""
    Path(path).write_text(document, encoding="utf-8")
